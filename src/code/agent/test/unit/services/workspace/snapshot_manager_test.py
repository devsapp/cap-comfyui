import io
import os
import tarfile
import zipfile

import pytest

import constants
from services.workspace.snapshot_manager import SnapshotManager


def _make_snapshot(snapshot_dir, name):
    """Create a valid snapshot directory with required archives."""
    path = os.path.join(snapshot_dir, name)
    os.makedirs(path, exist_ok=True)

    with zipfile.ZipFile(os.path.join(path, "comfyui.zip"), "w") as zf:
        zf.writestr("comfyui/test.txt", "test")

    with tarfile.open(os.path.join(path, "venv.tar"), "w") as tar:
        data = b"venv content"
        info = tarfile.TarInfo(name="venv/test.txt")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))


@pytest.fixture
def setup_versioned(tmp_path):
    """Set up a versioned snapshot directory layout."""
    mnt_dir = str(tmp_path / "mnt")
    versioned_dir = os.path.join(mnt_dir, "snapshots", "v0.3.77")
    legacy_dir = os.path.join(mnt_dir, "snapshots")

    os.makedirs(versioned_dir, exist_ok=True)
    os.makedirs(legacy_dir, exist_ok=True)

    constants.MNT_DIR = mnt_dir
    constants.SNAPSHOT_DIR = versioned_dir
    constants.COMFYUI_VERSION = "v0.3.77"
    constants.WORK_DIR = str(tmp_path / "work")
    constants.COMFYUI_DIR = str(tmp_path / "work" / "comfyui")
    constants.BACKEND_TYPE = constants.TYPE_COMFYUI
    constants.USE_API_MODE = False
    constants.MODEL_DIR = os.path.join(mnt_dir, "models")

    os.makedirs(constants.WORK_DIR, exist_ok=True)
    os.makedirs(constants.MODEL_DIR, exist_ok=True)
    os.makedirs(os.path.join(mnt_dir, "custom_nodes"), exist_ok=True)

    return tmp_path, versioned_dir, legacy_dir


class TestVersionedSnapshotDir:
    """Tests for version-prefixed snapshot directory behavior."""

    def test_find_snapshots_in_versioned_dir(self, setup_versioned):
        _, versioned_dir, _ = setup_versioned
        _make_snapshot(versioned_dir, "dev-20240101-120000")
        _make_snapshot(versioned_dir, "dev-20240102-120000")

        manager = SnapshotManager()
        snapshots = manager.find_valid_snapshots(SnapshotManager.TYPE_DEV)

        assert snapshots == ["dev-20240102-120000", "dev-20240101-120000"]

    def test_find_snapshots_ignores_other_type(self, setup_versioned):
        _, versioned_dir, _ = setup_versioned
        _make_snapshot(versioned_dir, "dev-20240101-120000")
        _make_snapshot(versioned_dir, "prod-20240101-120000")

        manager = SnapshotManager()
        dev_snapshots = manager.find_valid_snapshots(SnapshotManager.TYPE_DEV)
        prod_snapshots = manager.find_valid_snapshots(SnapshotManager.TYPE_PROD)

        assert dev_snapshots == ["dev-20240101-120000"]
        assert prod_snapshots == ["prod-20240101-120000"]

    def test_versioned_dir_empty_falls_back_to_legacy(self, setup_versioned):
        _, versioned_dir, legacy_dir = setup_versioned
        _make_snapshot(legacy_dir, "dev-20240101-120000")

        manager = SnapshotManager()
        snapshots = manager.find_valid_snapshots(SnapshotManager.TYPE_DEV)

        assert snapshots == ["dev-20240101-120000"]

    def test_versioned_dir_has_snapshots_ignores_legacy(self, setup_versioned):
        _, versioned_dir, legacy_dir = setup_versioned
        _make_snapshot(versioned_dir, "dev-20240102-120000")
        _make_snapshot(legacy_dir, "dev-20240101-120000")

        manager = SnapshotManager()
        snapshots = manager.find_valid_snapshots(SnapshotManager.TYPE_DEV)

        assert snapshots == ["dev-20240102-120000"]
        assert "dev-20240101-120000" not in snapshots

    def test_no_fallback_when_comfyui_version_unset(self, setup_versioned):
        """When COMFYUI_VERSION is empty, legacy fallback is disabled."""
        _, versioned_dir, legacy_dir = setup_versioned
        constants.COMFYUI_VERSION = ""
        _make_snapshot(legacy_dir, "dev-20240101-120000")

        manager = SnapshotManager()
        snapshots = manager.find_valid_snapshots(SnapshotManager.TYPE_DEV)

        # SNAPSHOT_DIR still points to versioned path (empty), no fallback
        assert snapshots == []


class TestLoadPathFallback:
    """Tests for load() falling back to legacy path when snapshot not in versioned dir."""

    def test_load_from_versioned_dir(self, setup_versioned):
        _, versioned_dir, _ = setup_versioned
        _make_snapshot(versioned_dir, "dev-20240101-120000")

        manager = SnapshotManager()
        result = manager.load("dev-20240101-120000")

        assert result["snapshot"] == "dev-20240101-120000"
        assert manager.snapshot_name == "dev-20240101-120000"

    def test_load_fallback_to_legacy_path(self, setup_versioned):
        _, versioned_dir, legacy_dir = setup_versioned
        _make_snapshot(legacy_dir, "dev-20240101-120000")

        manager = SnapshotManager()
        result = manager.load("dev-20240101-120000")

        assert result["snapshot"] == "dev-20240101-120000"

    def test_load_nonexistent_raises(self, setup_versioned):
        manager = SnapshotManager()
        with pytest.raises(RuntimeError, match="not found"):
            manager.load("dev-99999999-999999")

    def test_load_no_legacy_fallback_without_version(self, setup_versioned):
        """Without COMFYUI_VERSION, load does not attempt legacy fallback."""
        _, versioned_dir, legacy_dir = setup_versioned
        constants.COMFYUI_VERSION = ""
        _make_snapshot(legacy_dir, "dev-20240101-120000")

        manager = SnapshotManager()
        with pytest.raises(RuntimeError, match="not found"):
            manager.load("dev-20240101-120000")


class TestCrossVersionProtection:
    """Tests ensuring snapshots from one version don't leak into another."""

    def test_different_version_dirs_are_isolated(self, tmp_path):
        mnt_dir = str(tmp_path / "mnt")
        v077_dir = os.path.join(mnt_dir, "snapshots", "v0.3.77")
        v164_dir = os.path.join(mnt_dir, "snapshots", "v0.16.4")
        os.makedirs(v077_dir, exist_ok=True)
        os.makedirs(v164_dir, exist_ok=True)

        _make_snapshot(v077_dir, "dev-20240101-120000")
        _make_snapshot(v164_dir, "dev-20240102-120000")

        constants.MNT_DIR = mnt_dir
        constants.COMFYUI_VERSION = "v0.3.77"
        constants.SNAPSHOT_DIR = v077_dir
        constants.WORK_DIR = str(tmp_path / "work")
        constants.COMFYUI_DIR = str(tmp_path / "work" / "comfyui")
        constants.BACKEND_TYPE = constants.TYPE_COMFYUI
        constants.USE_API_MODE = False
        constants.MODEL_DIR = os.path.join(mnt_dir, "models")
        os.makedirs(constants.WORK_DIR, exist_ok=True)
        os.makedirs(constants.MODEL_DIR, exist_ok=True)

        manager = SnapshotManager()
        snapshots = manager.find_valid_snapshots(SnapshotManager.TYPE_DEV)

        assert "dev-20240101-120000" in snapshots
        assert "dev-20240102-120000" not in snapshots

    def test_save_writes_to_versioned_dir(self, setup_versioned):
        _, versioned_dir, _ = setup_versioned

        manager = SnapshotManager()
        result = manager.save(SnapshotManager.TYPE_DEV, snapshot_name="dev-20240103-120000")

        assert result["snapshot"] == "dev-20240103-120000"
        assert os.path.exists(os.path.join(versioned_dir, "dev-20240103-120000"))


class TestSnapshotLoadable:
    """Tests for _is_snapshot_loadable with zstd and legacy formats."""

    def test_zstd_format_loadable(self, setup_versioned):
        _, versioned_dir, _ = setup_versioned
        path = os.path.join(versioned_dir, "dev-20240101-120000")
        os.makedirs(path, exist_ok=True)

        open(os.path.join(path, "comfyui.tar.zst"), "w").close()
        open(os.path.join(path, "venv.tar.zst"), "w").close()

        manager = SnapshotManager()
        assert manager._is_snapshot_loadable("dev-20240101-120000") is True

    def test_mixed_format_loadable(self, setup_versioned):
        _, versioned_dir, _ = setup_versioned
        path = os.path.join(versioned_dir, "dev-20240101-120000")
        os.makedirs(path, exist_ok=True)

        open(os.path.join(path, "comfyui.tar.zst"), "w").close()
        open(os.path.join(path, "venv.tar"), "w").close()

        manager = SnapshotManager()
        assert manager._is_snapshot_loadable("dev-20240101-120000") is True

    def test_missing_venv_not_loadable(self, setup_versioned):
        _, versioned_dir, _ = setup_versioned
        path = os.path.join(versioned_dir, "dev-20240101-120000")
        os.makedirs(path, exist_ok=True)

        open(os.path.join(path, "comfyui.tar.zst"), "w").close()

        manager = SnapshotManager()
        assert manager._is_snapshot_loadable("dev-20240101-120000") is False

    def test_missing_app_not_loadable(self, setup_versioned):
        _, versioned_dir, _ = setup_versioned
        path = os.path.join(versioned_dir, "dev-20240101-120000")
        os.makedirs(path, exist_ok=True)

        open(os.path.join(path, "venv.tar.zst"), "w").close()

        manager = SnapshotManager()
        assert manager._is_snapshot_loadable("dev-20240101-120000") is False

    def test_nonexistent_dir_not_loadable(self, setup_versioned):
        manager = SnapshotManager()
        assert manager._is_snapshot_loadable("does-not-exist") is False
