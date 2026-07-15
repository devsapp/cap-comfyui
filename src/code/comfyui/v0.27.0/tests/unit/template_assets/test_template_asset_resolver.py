import errno
import hashlib
import importlib.util
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


PLUGIN_DIR = (
    Path(__file__).resolve().parents[3]
    / "custom_nodes"
    / "FunArt-ComfyUI-v027-Template-Assets"
)
MODULE_PATH = PLUGIN_DIR / "template_asset_resolver.py"
SPEC = importlib.util.spec_from_file_location("v027_template_asset_resolver", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

TemplateAssetError = MODULE.TemplateAssetError
TemplateAssetResolver = MODULE.TemplateAssetResolver
PNG_BYTES = b"\x89PNG\r\n\x1a\nverified-template-input"


@pytest.fixture
def resolver(tmp_path):
    asset_root = tmp_path / "bundled"
    asset_root.mkdir()
    (asset_root / "template.png").write_bytes(PNG_BYTES)

    manifest = {
        "schema_version": 1,
        "source": {"revision": "test-revision"},
        "assets": [
            {
                "filename": "template.png",
                "url": "https://example.invalid/template.png",
                "sha256": hashlib.sha256(PNG_BYTES).hexdigest(),
                "size": len(PNG_BYTES),
                "mime_type": "image/png",
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return TemplateAssetResolver(manifest_path, asset_root)


def test_finds_only_allowlisted_supported_load_inputs(resolver):
    prompt = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "template.png"}},
        "2": {"class_type": "LoadImageMask", "inputs": {"image": "template.png [input]"}},
        "3": {"class_type": "LoadImage", "inputs": {"image": "private.png"}},
        "4": {"class_type": "OtherNode", "inputs": {"image": "template.png"}},
    }

    assert resolver.find_prompt_inputs(prompt) == ("template.png",)


def test_provisions_independent_tenant_files(resolver, tmp_path):
    tenant_a = tmp_path / "input" / "users" / "user-a"
    tenant_b = tmp_path / "input" / "users" / "user-b"

    path_a = resolver.ensure_input("template.png", tenant_a)
    path_b = resolver.ensure_input("template.png", tenant_b)

    assert Path(path_a).read_bytes() == PNG_BYTES
    assert Path(path_b).read_bytes() == PNG_BYTES
    assert path_a != path_b
    assert os.stat(path_a).st_ino != os.stat(path_b).st_ino


def test_existing_tenant_file_always_wins(resolver, tmp_path):
    tenant = tmp_path / "tenant"
    tenant.mkdir()
    existing = tenant / "template.png"
    existing.write_bytes(b"user-owned")

    assert resolver.ensure_input("template.png", tenant) == str(existing)
    assert existing.read_bytes() == b"user-owned"


@pytest.mark.parametrize(
    "filename",
    ["private.png", "../template.png", "/tmp/template.png", "folder/template.png"],
)
def test_rejects_untrusted_or_unsafe_names(resolver, tmp_path, filename):
    with pytest.raises(TemplateAssetError, match="not allowlisted"):
        resolver.ensure_input(filename, tmp_path / "tenant")


def test_rejects_symlink_instead_of_following_it(resolver, tmp_path):
    tenant = tmp_path / "tenant"
    tenant.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    (tenant / "template.png").symlink_to(outside)

    with pytest.raises(TemplateAssetError, match="non-regular"):
        resolver.ensure_input("template.png", tenant)
    assert outside.read_bytes() == b"outside"


def test_detects_tampered_bundled_asset(resolver, tmp_path):
    (tmp_path / "bundled" / "template.png").write_bytes(
        b"\x89PNG\r\n\x1a\ntampered-template-input"
    )

    with pytest.raises(TemplateAssetError, match="invalid size|failed SHA256"):
        resolver.ensure_input("template.png", tmp_path / "tenant")


def test_wraps_filesystem_errors_as_template_asset_errors(resolver, tmp_path, monkeypatch):
    def deny_directory_creation(*args, **kwargs):
        raise PermissionError("read only")

    monkeypatch.setattr(MODULE.os, "makedirs", deny_directory_creation)

    with pytest.raises(TemplateAssetError, match="Unable to provision"):
        resolver.ensure_input("template.png", tmp_path / "tenant")


def test_concurrent_provisioning_never_leaves_partial_files(resolver, tmp_path):
    tenant = tmp_path / "tenant"

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(
            executor.map(
                lambda _: resolver.ensure_input("template.png", tenant),
                range(16),
            )
        )

    assert len(set(results)) == 1
    assert Path(results[0]).read_bytes() == PNG_BYTES
    assert list(tenant.glob(".*.tmp")) == []


def test_falls_back_to_atomic_noreplace_rename_when_mount_rejects_hardlinks(
    resolver, tmp_path, monkeypatch
):
    def reject_hardlink(*args, **kwargs):
        raise OSError(errno.EOPNOTSUPP, "hard links unsupported")

    def rename_noreplace(source, destination):
        if os.path.exists(destination):
            raise FileExistsError(destination)
        os.rename(source, destination)

    monkeypatch.setattr(MODULE.os, "link", reject_hardlink)
    monkeypatch.setattr(
        MODULE.TemplateAssetResolver,
        "_rename_noreplace",
        staticmethod(rename_noreplace),
    )
    destination = resolver.ensure_input("template.png", tmp_path / "tenant")

    assert Path(destination).read_bytes() == PNG_BYTES
    assert list(Path(destination).parent.glob(".*.tmp")) == []


def test_rejects_non_object_manifest(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("[]", encoding="utf-8")

    with pytest.raises(TemplateAssetError, match="Unsupported official template"):
        TemplateAssetResolver(manifest_path, tmp_path)


def test_production_manifest_is_pinned_to_v027_template_release():
    manifest = json.loads(
        (PLUGIN_DIR / "official_template_inputs.json").read_text(encoding="utf-8")
    )
    revision = manifest["source"]["revision"]

    assert manifest["source"]["workflow_templates_version"] == "0.11.1"
    assert revision == "5fac06d8edf9760e3a124a1b3ffdf4744d2f29b7"
    assert {asset["filename"] for asset in manifest["assets"]} == {
        "api_nano_banana_pro_input_image_1.png",
        "api_nano_banana_pro_input_image_2.png",
    }
    assert all(f"/{revision}/input/" in asset["url"] for asset in manifest["assets"])
