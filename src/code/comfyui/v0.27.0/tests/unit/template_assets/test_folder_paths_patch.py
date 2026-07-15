import importlib
import os
import sys
import types
from pathlib import Path


PLUGIN_DIR = (
    Path(__file__).resolve().parents[3]
    / "custom_nodes"
    / "FunArt-ComfyUI-v027-Template-Assets"
)
PACKAGE_NAME = "v027_template_assets_test_package"


package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(PLUGIN_DIR)]
sys.modules[PACKAGE_NAME] = package
patch_module = importlib.import_module(f"{PACKAGE_NAME}.folder_paths_patch")


class FakeResolver:
    def __init__(self):
        self.calls = []

    def is_known_input(self, filename):
        return filename == "template.png"

    @property
    def known_filenames(self):
        return frozenset({"template.png"})

    def ensure_inputs(self, filenames, input_directory):
        return tuple(self.ensure_input(filename, input_directory) for filename in filenames)

    def ensure_input(self, filename, input_directory):
        self.calls.append((filename, input_directory))
        Path(input_directory, filename).write_bytes(b"provisioned")


def _fake_folder_paths(input_directory):
    module = types.SimpleNamespace()
    module.input_directory = str(Path(input_directory).parents[1]) if "users" in Path(input_directory).parts else str(input_directory)
    module.get_input_directory = lambda: input_directory
    module.get_directory_by_type = lambda type_name: (
        module.get_input_directory() if type_name == "input" else None
    )

    def get_annotated_filepath(name, default_dir=None):
        if name.endswith(" [input]"):
            name = name[:-8]
            base_dir = module.get_input_directory()
        elif name.endswith(" [output]"):
            name = name[:-9]
            base_dir = str(Path(input_directory).parent / "output")
        else:
            base_dir = default_dir or module.get_input_directory()
        return os.path.join(os.fspath(base_dir), name)

    module.get_annotated_filepath = get_annotated_filepath
    module.exists_annotated_filepath = lambda name: os.path.exists(
        get_annotated_filepath(name)
    )
    return module


def test_validation_provisions_only_the_current_tenant(monkeypatch, tmp_path):
    resolver = FakeResolver()
    user_a = tmp_path / "input" / "users" / "user-a"
    user_a.mkdir(parents=True)
    folder_paths = _fake_folder_paths(user_a)
    monkeypatch.setitem(sys.modules, "folder_paths", folder_paths)
    monkeypatch.setattr(patch_module, "get_default_resolver", lambda: resolver)

    assert patch_module.install_template_asset_patch() is True
    assert folder_paths.exists_annotated_filepath("template.png") is True
    assert resolver.calls == [("template.png", str(user_a))]
    assert (user_a / "template.png").read_bytes() == b"provisioned"


def test_dynamic_input_directory_is_resolved_at_each_call(monkeypatch, tmp_path):
    resolver = FakeResolver()
    current = {"path": tmp_path / "input" / "users" / "user-a"}
    current["path"].mkdir(parents=True)
    folder_paths = _fake_folder_paths(current["path"])
    folder_paths.get_input_directory = lambda: current["path"]
    monkeypatch.setitem(sys.modules, "folder_paths", folder_paths)
    monkeypatch.setattr(patch_module, "get_default_resolver", lambda: resolver)

    patch_module.install_template_asset_patch()
    assert folder_paths.exists_annotated_filepath("template.png") is True

    current["path"] = tmp_path / "input" / "users" / "user-b"
    current["path"].mkdir(parents=True)
    assert folder_paths.exists_annotated_filepath("template.png") is True

    assert resolver.calls == [
        ("template.png", str(tmp_path / "input" / "users" / "user-a")),
        ("template.png", str(tmp_path / "input" / "users" / "user-b")),
    ]


def test_output_annotation_and_unknown_files_are_never_provisioned(monkeypatch, tmp_path):
    resolver = FakeResolver()
    tenant = tmp_path / "input" / "users" / "user-a"
    tenant.mkdir(parents=True)
    folder_paths = _fake_folder_paths(tenant)
    monkeypatch.setitem(sys.modules, "folder_paths", folder_paths)
    monkeypatch.setattr(patch_module, "get_default_resolver", lambda: resolver)

    patch_module.install_template_asset_patch()
    assert folder_paths.exists_annotated_filepath("template.png [output]") is False
    assert folder_paths.exists_annotated_filepath("private.png") is False
    assert resolver.calls == []


def test_view_input_directory_provisions_previews_for_new_tenant(monkeypatch, tmp_path):
    resolver = FakeResolver()
    tenant = tmp_path / "input" / "users" / "user-a"
    tenant.mkdir(parents=True)
    folder_paths = _fake_folder_paths(tenant)
    monkeypatch.setitem(sys.modules, "folder_paths", folder_paths)
    monkeypatch.setattr(patch_module, "get_default_resolver", lambda: resolver)

    patch_module.install_template_asset_patch()
    assert folder_paths.get_directory_by_type("input") == tenant
    assert resolver.calls == [("template.png", str(tenant))]
    assert (tenant / "template.png").read_bytes() == b"provisioned"


def test_rejects_malformed_tenant_directory(monkeypatch, tmp_path):
    resolver = FakeResolver()
    base = tmp_path / "input"
    base.mkdir()
    folder_paths = _fake_folder_paths(base)
    folder_paths.input_directory = str(base)
    folder_paths.get_input_directory = lambda: str(base / "users" / "user-a" / ".." / "user-b")
    monkeypatch.setitem(sys.modules, "folder_paths", folder_paths)
    monkeypatch.setattr(patch_module, "get_default_resolver", lambda: resolver)

    patch_module.install_template_asset_patch()
    assert folder_paths.exists_annotated_filepath("template.png") is False
    assert resolver.calls == []


def test_rejects_tenant_symlink_to_sibling(monkeypatch, tmp_path):
    resolver = FakeResolver()
    base = tmp_path / "input"
    users = base / "users"
    user_b = users / "user-b"
    user_b.mkdir(parents=True)
    user_a = users / "user-a"
    user_a.symlink_to(user_b, target_is_directory=True)
    folder_paths = _fake_folder_paths(user_a)
    folder_paths.input_directory = str(base)
    monkeypatch.setitem(sys.modules, "folder_paths", folder_paths)
    monkeypatch.setattr(patch_module, "get_default_resolver", lambda: resolver)

    patch_module.install_template_asset_patch()
    assert folder_paths.exists_annotated_filepath("template.png") is False
    assert resolver.calls == []
    assert not (user_b / "template.png").exists()


def test_patch_is_idempotent_across_duplicate_plugin_paths(monkeypatch, tmp_path):
    folder_paths = _fake_folder_paths(tmp_path)
    monkeypatch.setitem(sys.modules, "folder_paths", folder_paths)

    assert patch_module.install_template_asset_patch() is True
    assert patch_module.install_template_asset_patch() is False
