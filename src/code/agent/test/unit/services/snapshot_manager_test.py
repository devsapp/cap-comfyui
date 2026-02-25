import io
import tarfile
import pytest
import os
import shutil
from datetime import datetime
from services.workspace.snapshot_manager import SnapshotManager
import constants


@pytest.fixture
def setup_snapshot_files(tmp_path):
    # 创建快照目录结构
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()

    # 创建多个快照目录
    snapshots = [
        "dev-20231201-120000",
        "dev-20231202-115959",
        "dev-20231202-120000",
        "prod-20231202-120000"
    ]

    for snapshot in snapshots:
        snapshot_path = snapshot_dir / snapshot
        snapshot_path.mkdir()

        # 创建comfyui.zip文件
        import zipfile
        comfyui_zip = snapshot_path / "comfyui.zip"
        with zipfile.ZipFile(comfyui_zip, 'w') as zf:
            zf.writestr('comfyui/test.txt', 'test content')

        # 创建venv.tar文件
        tar_path = snapshot_path / "venv.tar"
        with tarfile.open(tar_path, "w") as tar:
            test_content = "This is a test file in venv"
            test_file = io.BytesIO(test_content.encode())
            tarinfo = tarfile.TarInfo(name="venv/test_venv.txt")
            tarinfo.size = len(test_content)
            tar.addfile(tarinfo, test_file)

    # 创建挂载目录和必要的子目录
    mnt_dir = tmp_path / "mnt"
    mnt_dir.mkdir()

    # 创建models目录
    models_dir = mnt_dir / "models"
    models_dir.mkdir()
    (models_dir / "test_model.bin").write_text("test model content")

    # 创建custom_nodes目录
    custom_nodes_dir = mnt_dir / "custom_nodes"
    custom_nodes_dir.mkdir()
    (custom_nodes_dir / "test_node.py").write_text("test node content")

    # 设置常量
    constants.SNAPSHOT_DIR = str(snapshot_dir)
    constants.WORK_DIR = str(tmp_path / "work")
    constants.MNT_DIR = str(mnt_dir)
    constants.MODEL_DIR = str(mnt_dir / "models")
    constants.COMFYUI_DIR = str(tmp_path / "work/comfyui")
    constants.BACKEND_TYPE = constants.TYPE_COMFYUI
    constants.USE_API_MODE = False

    os.makedirs(constants.WORK_DIR, exist_ok=True)

    return tmp_path


def test_load_latest_dev_snapshot(setup_snapshot_files):
    manager = SnapshotManager()
    result = manager.load(SnapshotManager.USE_LATEST_DEV)

    assert result["snapshot"] == "dev-20231202-120000"
    assert manager.snapshot_name == "dev-20231202-120000"

    # 验证模型目录软链接
    models_link = os.path.join(constants.COMFYUI_DIR, "models")
    assert os.path.islink(models_link)
    assert os.readlink(models_link) == os.path.join(constants.MNT_DIR, "models")


def test_load_latest_prod_snapshot(setup_snapshot_files):
    manager = SnapshotManager()
    result = manager.load(SnapshotManager.USE_LATEST_PROD)

    assert result["snapshot"] == "prod-20231202-120000"
    assert manager.snapshot_name == "prod-20231202-120000"


def test_load_specific_snapshot(setup_snapshot_files):
    manager = SnapshotManager()
    result = manager.load("dev-20231202-115959")

    assert result["snapshot"] == "dev-20231202-115959"
    assert manager.snapshot_name == "dev-20231202-115959"


def test_load_nonexistent_snapshot(setup_snapshot_files):
    manager = SnapshotManager()
    with pytest.raises(RuntimeError):
        manager.load("nonexistent")


def test_load_same_snapshot_twice(setup_snapshot_files):
    manager = SnapshotManager()
    first_load = manager.load("dev-20231202-120000")
    second_load = manager.load("dev-20231202-120000")

    assert first_load["snapshot"] == second_load["snapshot"]
    assert manager.snapshot_name == "dev-20231202-120000"


def test_select_latest_snapshot_with_invalid_format(setup_snapshot_files):
    invalid_snapshot = os.path.join(constants.SNAPSHOT_DIR, "invalid_format")
    os.makedirs(invalid_snapshot)

    manager = SnapshotManager()
    latest = manager._select_latest_snapshot(SnapshotManager.TYPE_DEV)

    assert latest == "dev-20231202-120000"


def test_select_latest_snapshot_empty_dir(tmp_path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    constants.SNAPSHOT_DIR = str(empty_dir)

    manager = SnapshotManager()
    latest = manager._select_latest_snapshot(SnapshotManager.TYPE_DEV)

    assert latest is None


def test_save_dev_snapshot(setup_snapshot_files):
    manager = SnapshotManager()
    result = manager.save(SnapshotManager.TYPE_DEV)

    assert "snapshot" in result
    snapshot_name = result["snapshot"]
    assert snapshot_name.startswith("dev-")
    assert manager.snapshot_name == snapshot_name


def test_save_prod_snapshot(setup_snapshot_files):
    manager = SnapshotManager()
    result = manager.save(SnapshotManager.TYPE_PROD)

    assert "snapshot" in result
    snapshot_name = result["snapshot"]
    assert snapshot_name.startswith("prod-")
    assert manager.snapshot_name == snapshot_name


def test_save_invalid_type(setup_snapshot_files):
    manager = SnapshotManager()
    with pytest.raises(RuntimeError):
        manager.save("invalid")


def test_select_latest_dev_skips_incomplete_snapshot(setup_snapshot_files):
    """最新 dev 快照缺少压缩包时，选择阶段直接跳过，选中更早的可用快照"""
    # 删除最新快照的所有压缩包，使其不完整
    latest_path = os.path.join(constants.SNAPSHOT_DIR, "dev-20231202-120000")
    for f in os.listdir(latest_path):
        os.remove(os.path.join(latest_path, f))

    manager = SnapshotManager()
    result = manager.load(SnapshotManager.USE_LATEST_DEV)

    # 应跳过不完整的最新快照，选中 dev-20231202-115959
    assert result["snapshot"] == "dev-20231202-115959"
    assert manager.snapshot_name == "dev-20231202-115959"


def test_select_latest_dev_skips_multiple_incomplete(setup_snapshot_files):
    """多个 dev 快照不完整时，依次跳过直到找到可用的"""
    for name in ["dev-20231202-120000", "dev-20231202-115959"]:
        path = os.path.join(constants.SNAPSHOT_DIR, name)
        for f in os.listdir(path):
            os.remove(os.path.join(path, f))

    manager = SnapshotManager()
    result = manager.load(SnapshotManager.USE_LATEST_DEV)

    # 应选中最早的 dev-20231201-120000
    assert result["snapshot"] == "dev-20231201-120000"
    assert manager.snapshot_name == "dev-20231201-120000"


def test_select_latest_dev_all_incomplete(setup_snapshot_files):
    """所有 dev 快照都不完整时，返回 None，跳过加载"""
    for name in ["dev-20231202-120000", "dev-20231202-115959", "dev-20231201-120000"]:
        path = os.path.join(constants.SNAPSHOT_DIR, name)
        for f in os.listdir(path):
            os.remove(os.path.join(path, f))

    manager = SnapshotManager()
    result = manager.load(SnapshotManager.USE_LATEST_DEV)

    # 没有可用快照，跳过加载
    assert result["snapshot"] is None
    assert manager.snapshot_name is None


def test_select_latest_dev_missing_venv_only(setup_snapshot_files):
    """最新快照只缺 venv 压缩包时，也应跳过"""
    latest_path = os.path.join(constants.SNAPSHOT_DIR, "dev-20231202-120000")
    # 只删除 venv.tar，保留 comfyui.zip
    os.remove(os.path.join(latest_path, "venv.tar"))

    manager = SnapshotManager()
    result = manager.load(SnapshotManager.USE_LATEST_DEV)

    assert result["snapshot"] == "dev-20231202-115959"


def test_select_latest_dev_missing_comfyui_only(setup_snapshot_files):
    """最新快照只缺 comfyui 压缩包时，也应跳过"""
    latest_path = os.path.join(constants.SNAPSHOT_DIR, "dev-20231202-120000")
    # 只删除 comfyui.zip，保留 venv.tar
    os.remove(os.path.join(latest_path, "comfyui.zip"))

    manager = SnapshotManager()
    result = manager.load(SnapshotManager.USE_LATEST_DEV)

    assert result["snapshot"] == "dev-20231202-115959"


def test_load_specific_dev_no_validation(setup_snapshot_files):
    """指定具名 dev 快照时不做完整性检查，缺文件直接报错"""
    latest_path = os.path.join(constants.SNAPSHOT_DIR, "dev-20231202-120000")
    for f in os.listdir(latest_path):
        os.remove(os.path.join(latest_path, f))

    manager = SnapshotManager()
    # 指定具名快照加载，不走回退，应直接抛异常
    with pytest.raises(Exception):
        manager.load("dev-20231202-120000")


def test_select_latest_dev_already_loaded_skips(setup_snapshot_files):
    """最新可用快照已加载时，直接跳过"""
    manager = SnapshotManager()
    manager.cur_snapshot_name = "dev-20231202-120000"

    result = manager.load(SnapshotManager.USE_LATEST_DEV)
    assert result["snapshot"] == "dev-20231202-120000"


def test_is_snapshot_loadable(setup_snapshot_files):
    """_is_snapshot_loadable 正确判断快照完整性"""
    manager = SnapshotManager()

    # 完整快照
    assert manager._is_snapshot_loadable("dev-20231202-120000") is True

    # 删除 venv.tar → 不完整
    os.remove(os.path.join(constants.SNAPSHOT_DIR, "dev-20231202-120000", "venv.tar"))
    assert manager._is_snapshot_loadable("dev-20231202-120000") is False

    # 不存在的快照
    assert manager._is_snapshot_loadable("dev-99999999-999999") is False


@pytest.fixture(autouse=True)
def cleanup(setup_snapshot_files):
    yield
    shutil.rmtree(setup_snapshot_files)
