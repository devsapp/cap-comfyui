"""Provision trusted v0.33.1 workflow-template inputs into the active tenant directory.

The v0.33.1 workflow-template package ships workflow JSON and previews, but not
the input PNGs referenced by the Nano Banana Pro template. The matching assets
are pinned and verified while the image is built. At request time this module
only copies those bundled, public assets into the current tenant's input
directory; it never reads the default user's input or another tenant's files.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import shutil
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional


_DEFAULT_MANIFEST = Path(__file__).with_name("official_template_inputs.json")
_DEFAULT_ASSET_ROOT = Path(__file__).with_name("bundled_template_assets")
_SUPPORTED_NODE_INPUTS = {
    "LoadImage": ("image",),
    "LoadImageMask": ("image",),
}
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class TemplateAssetError(RuntimeError):
    """Raised when a trusted template asset cannot be provisioned safely."""


@dataclass(frozen=True)
class TemplateAsset:
    filename: str
    sha256: str
    size: int
    mime_type: str


class TemplateAssetResolver:
    """Resolve an exact allowlist of bundled template inputs for one tenant."""

    def __init__(
        self,
        manifest_path: os.PathLike[str] | str = _DEFAULT_MANIFEST,
        asset_root: os.PathLike[str] | str = _DEFAULT_ASSET_ROOT,
    ) -> None:
        self._manifest_path = Path(manifest_path)
        self._asset_root = Path(asset_root)
        self._assets = self._load_manifest()
        self._verified_sources: set[str] = set()
        # Fixed lock striping bounds memory on long-lived multi-tenant workers.
        self._locks = tuple(threading.Lock() for _ in range(64))

    @property
    def known_filenames(self) -> frozenset[str]:
        return frozenset(self._assets)

    def is_known_input(self, value: object) -> bool:
        name = self._canonical_input_name(value)
        return name in self._assets if name is not None else False

    def find_prompt_inputs(self, prompt: object) -> tuple[str, ...]:
        """Return trusted template filenames referenced by supported load nodes."""
        if not isinstance(prompt, Mapping):
            return ()

        found: set[str] = set()
        for node in prompt.values():
            if not isinstance(node, Mapping):
                continue

            input_names = _SUPPORTED_NODE_INPUTS.get(node.get("class_type"))
            inputs = node.get("inputs")
            if input_names is None or not isinstance(inputs, Mapping):
                continue

            for input_name in input_names:
                candidate = self._canonical_input_name(inputs.get(input_name))
                if candidate in self._assets:
                    found.add(candidate)

        return tuple(sorted(found))

    def ensure_prompt_inputs(
        self,
        prompt: object,
        tenant_input_dir: os.PathLike[str] | str,
    ) -> tuple[str, ...]:
        return self.ensure_inputs(self.find_prompt_inputs(prompt), tenant_input_dir)

    def ensure_inputs(
        self,
        filenames: Iterable[str],
        tenant_input_dir: os.PathLike[str] | str,
    ) -> tuple[str, ...]:
        provisioned = []
        for filename in sorted(set(filenames)):
            provisioned.append(self.ensure_input(filename, tenant_input_dir))
        return tuple(provisioned)

    def ensure_input(
        self,
        filename: str,
        tenant_input_dir: os.PathLike[str] | str,
    ) -> str:
        """Copy one trusted asset without overwriting a tenant-owned file."""
        try:
            return self._ensure_input(filename, tenant_input_dir)
        except TemplateAssetError:
            raise
        except OSError as exc:
            raise TemplateAssetError(
                f"Unable to provision official template input: {filename!r}"
            ) from exc

    def _ensure_input(
        self,
        filename: str,
        tenant_input_dir: os.PathLike[str] | str,
    ) -> str:
        canonical_name = self._canonical_input_name(filename)
        asset = self._assets.get(canonical_name or "")
        if asset is None:
            raise TemplateAssetError(f"Template input is not allowlisted: {filename!r}")

        tenant_root = os.path.abspath(os.fspath(tenant_input_dir))
        os.makedirs(tenant_root, mode=0o700, exist_ok=True)
        destination = os.path.abspath(os.path.join(tenant_root, asset.filename))
        if os.path.commonpath((tenant_root, destination)) != tenant_root:
            raise TemplateAssetError(f"Template input escapes tenant directory: {asset.filename}")

        tenant_root_real = os.path.realpath(tenant_root)
        destination_parent_real = os.path.realpath(os.path.dirname(destination))
        if os.path.commonpath((tenant_root_real, destination_parent_real)) != tenant_root_real:
            raise TemplateAssetError(f"Template input parent escapes tenant directory: {asset.filename}")

        lock = self._lock_for(destination)
        with lock:
            if os.path.lexists(destination):
                if os.path.isfile(destination) and not os.path.islink(destination):
                    return destination
                raise TemplateAssetError(
                    f"Refusing to replace non-regular tenant input: {asset.filename}"
                )

            source = self._verified_source(asset)
            temporary = self._copy_to_temporary_file(source, tenant_root, asset.filename)
            try:
                # A same-directory hard link gives atomic, no-clobber publication.
                # The temporary file is already an independent copy of the bundle.
                self._publish_no_clobber(temporary, destination)
            except FileExistsError:
                if not (os.path.isfile(destination) and not os.path.islink(destination)):
                    raise TemplateAssetError(
                        f"Tenant input appeared with an unsafe type: {asset.filename}"
                    )
            except OSError as exc:
                raise TemplateAssetError(
                    f"Unable to publish template input atomically: {asset.filename}"
                ) from exc
            finally:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass

        return destination

    def _load_manifest(self) -> dict[str, TemplateAsset]:
        try:
            payload = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise TemplateAssetError(
                f"Unable to load official template manifest: {self._manifest_path}"
            ) from exc

        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != 1
            or not isinstance(payload.get("assets"), list)
        ):
            raise TemplateAssetError("Unsupported official template manifest schema")

        assets: dict[str, TemplateAsset] = {}
        for raw_asset in payload["assets"]:
            try:
                filename = raw_asset["filename"]
                sha256 = raw_asset["sha256"]
                size = raw_asset["size"]
                mime_type = raw_asset["mime_type"]
            except (KeyError, TypeError) as exc:
                raise TemplateAssetError("Malformed official template asset entry") from exc

            if self._canonical_input_name(filename) != filename:
                raise TemplateAssetError(f"Unsafe official template filename: {filename!r}")
            if not isinstance(sha256, str) or len(sha256) != 64:
                raise TemplateAssetError(f"Invalid SHA256 for official template asset: {filename}")
            if not isinstance(size, int) or size <= 0:
                raise TemplateAssetError(f"Invalid size for official template asset: {filename}")
            if mime_type != "image/png":
                raise TemplateAssetError(f"Unsupported template asset MIME type: {mime_type!r}")
            if filename in assets:
                raise TemplateAssetError(f"Duplicate official template asset: {filename}")

            assets[filename] = TemplateAsset(filename, sha256.lower(), size, mime_type)

        return assets

    def _verified_source(self, asset: TemplateAsset) -> str:
        source = os.path.abspath(os.path.join(os.fspath(self._asset_root), asset.filename))
        asset_root = os.path.abspath(os.fspath(self._asset_root))
        if os.path.commonpath((asset_root, source)) != asset_root:
            raise TemplateAssetError(f"Bundled asset escapes asset root: {asset.filename}")

        if source in self._verified_sources:
            return source
        if not os.path.isfile(source) or os.path.islink(source):
            raise TemplateAssetError(f"Bundled template input is missing: {asset.filename}")
        if os.path.getsize(source) != asset.size:
            raise TemplateAssetError(f"Bundled template input has invalid size: {asset.filename}")

        digest = hashlib.sha256()
        with open(source, "rb") as source_file:
            signature = source_file.read(len(_PNG_SIGNATURE))
            if signature != _PNG_SIGNATURE:
                raise TemplateAssetError(f"Bundled template input is not a PNG: {asset.filename}")
            digest.update(signature)
            for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
                digest.update(chunk)

        if digest.hexdigest() != asset.sha256:
            raise TemplateAssetError(f"Bundled template input failed SHA256: {asset.filename}")

        self._verified_sources.add(source)
        return source

    @staticmethod
    def _copy_to_temporary_file(source: str, tenant_root: str, filename: str) -> str:
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{filename}.", suffix=".tmp", dir=tenant_root
        )
        try:
            with os.fdopen(descriptor, "wb") as destination_file:
                with open(source, "rb") as source_file:
                    shutil.copyfileobj(source_file, destination_file, length=1024 * 1024)
                destination_file.flush()
                os.fsync(destination_file.fileno())
            os.chmod(temporary, 0o600)
            return temporary
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise

    def _lock_for(self, path: str) -> threading.Lock:
        return self._locks[hash(path) % len(self._locks)]

    @staticmethod
    def _publish_no_clobber(temporary: str, destination: str) -> None:
        try:
            os.link(temporary, destination)
            return
        except FileExistsError:
            raise
        except OSError as exc:
            unsupported = {
                errno.EPERM,
                errno.EXDEV,
                getattr(errno, "ENOTSUP", errno.EOPNOTSUPP),
                errno.EOPNOTSUPP,
            }
            if exc.errno not in unsupported:
                raise

        # Linux renameat2(RENAME_NOREPLACE) is also atomic and no-clobber on
        # mounts that support renames but intentionally disable hard links.
        TemplateAssetResolver._rename_noreplace(temporary, destination)

    @staticmethod
    def _rename_noreplace(source: str, destination: str) -> None:
        at_fdcwd = -100
        rename_noreplace = 1
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise OSError(errno.ENOSYS, "renameat2 is unavailable")

        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        result = renameat2(
            at_fdcwd,
            os.fsencode(source),
            at_fdcwd,
            os.fsencode(destination),
            rename_noreplace,
        )
        if result == 0:
            return

        error_number = ctypes.get_errno()
        if error_number == errno.EEXIST:
            raise FileExistsError(error_number, os.strerror(error_number), destination)
        raise OSError(error_number, os.strerror(error_number), destination)

    @staticmethod
    def _canonical_input_name(value: object) -> Optional[str]:
        if not isinstance(value, str) or not value or "\x00" in value:
            return None
        if value.endswith(" [input]"):
            value = value[:-8]
        elif value.endswith("[output]") or value.endswith("[temp]"):
            return None
        if not value or value in {".", ".."}:
            return None
        if os.path.isabs(value) or "/" in value or "\\" in value:
            return None
        return value


_default_resolver: Optional[TemplateAssetResolver] = None
_default_resolver_lock = threading.Lock()


def get_default_resolver() -> TemplateAssetResolver:
    global _default_resolver
    if _default_resolver is None:
        with _default_resolver_lock:
            if _default_resolver is None:
                _default_resolver = TemplateAssetResolver()
    return _default_resolver


__all__ = [
    "TemplateAsset",
    "TemplateAssetError",
    "TemplateAssetResolver",
    "get_default_resolver",
]
