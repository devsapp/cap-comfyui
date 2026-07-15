"""Resolve pinned official template inputs through tenant-aware folder paths."""

import os

from .template_asset_resolver import TemplateAssetError, get_default_resolver


_PATCH_MARKER = "_funart_v027_template_assets_patch_installed"
_original_get_annotated_filepath = None
_original_exists_annotated_filepath = None
_original_get_directory_by_type = None


def _current_input_directory(folder_paths) -> str:
    # The Multi-User plugin replaces this function with a DynamicPathProxy.
    # Resolve it at call time so load order cannot pin the default tenant.
    return os.fspath(folder_paths.get_input_directory())


def _trusted_input_directory(folder_paths, value: object):
    """Return a canonical tenant input root, rejecting malformed user paths."""
    try:
        raw_directory = os.fspath(value)
        raw_base = os.fspath(folder_paths.input_directory)
    except (AttributeError, TypeError):
        return None

    # MultiUser directories are either the base input directory (default user)
    # or exactly <base>/users/<single user id>. Reject traversal/nested IDs
    # before normalising so an abnormal request header cannot escape its tenant.
    if os.path.normpath(raw_directory) != raw_directory:
        return None

    directory = os.path.abspath(raw_directory)
    base = os.path.abspath(raw_base)
    directory_real = os.path.realpath(directory)
    base_real = os.path.realpath(base)
    if directory_real == base_real:
        return directory

    relative = os.path.relpath(directory, base)
    parts = relative.split(os.sep)
    if len(parts) != 2 or parts[0] != "users" or parts[1] in {"", ".", ".."}:
        return None
    users_real = os.path.realpath(os.path.join(base, "users"))
    if users_real != os.path.join(base_real, "users"):
        return None
    if directory_real != os.path.join(users_real, parts[1]):
        return None
    return directory


def _trusted_input_for_path(folder_paths, path: str):
    input_directory = _trusted_input_directory(
        folder_paths, _current_input_directory(folder_paths)
    )
    if input_directory is None:
        return None, None
    absolute_path = os.path.abspath(os.fspath(path))
    if os.path.commonpath((input_directory, absolute_path)) != input_directory:
        return None, input_directory

    relative_path = os.path.relpath(absolute_path, input_directory)
    resolver = get_default_resolver()
    if not resolver.is_known_input(relative_path):
        return None, input_directory
    return relative_path, input_directory


def _ensure_trusted_input(folder_paths, path: str) -> None:
    try:
        filename, input_directory = _trusted_input_for_path(folder_paths, path)
        if filename is None or input_directory is None:
            return
        get_default_resolver().ensure_input(filename, input_directory)
    except TemplateAssetError as exc:
        # Preserve ComfyUI's normal validation contract while providing a
        # precise server-side cause for image/build diagnostics.
        print(f"[FunArt-v0.27-Template-Assets] Provisioning failed: {exc}")


def _ensure_all_trusted_inputs(folder_paths, input_directory: object) -> None:
    try:
        trusted_directory = _trusted_input_directory(folder_paths, input_directory)
        if trusted_directory is None:
            return
        resolver = get_default_resolver()
        resolver.ensure_inputs(resolver.known_filenames, trusted_directory)
    except TemplateAssetError as exc:
        print(f"[FunArt-v0.27-Template-Assets] Provisioning failed: {exc}")


def install_template_asset_patch() -> bool:
    """Install idempotent wrappers around ComfyUI's annotated input helpers."""
    global _original_get_annotated_filepath
    global _original_exists_annotated_filepath
    global _original_get_directory_by_type

    import folder_paths  # type: ignore

    if getattr(folder_paths, _PATCH_MARKER, False):
        return False

    _original_get_annotated_filepath = folder_paths.get_annotated_filepath
    _original_exists_annotated_filepath = folder_paths.exists_annotated_filepath
    _original_get_directory_by_type = folder_paths.get_directory_by_type

    def get_annotated_filepath(name: str, default_dir=None) -> str:
        path = _original_get_annotated_filepath(name, default_dir)
        if not os.path.exists(path):
            _ensure_trusted_input(folder_paths, path)
        return path

    def exists_annotated_filepath(name) -> bool:
        if _original_exists_annotated_filepath(name):
            return True
        path = _original_get_annotated_filepath(name)
        _ensure_trusted_input(folder_paths, path)
        return _original_exists_annotated_filepath(name)

    def get_directory_by_type(type_name: str):
        directory = _original_get_directory_by_type(type_name)
        if type_name == "input" and directory is not None:
            # /view uses this helper directly. Provision before it tests the
            # file so a newly opened official template also renders previews.
            _ensure_all_trusted_inputs(folder_paths, directory)
        return directory

    folder_paths.get_annotated_filepath = get_annotated_filepath
    folder_paths.exists_annotated_filepath = exists_annotated_filepath
    folder_paths.get_directory_by_type = get_directory_by_type
    setattr(folder_paths, _PATCH_MARKER, True)
    print("[FunArt-v0.27-Template-Assets] ✅ Tenant-aware template inputs enabled")
    return True


__all__ = ["install_template_asset_patch"]
