import io
import tarfile

import pytest
import os
import shutil
from services.comfyui_process import start, save, _select_snapshot
import constants


@pytest.fixture
def setup_snapshot_files(tmp_path):
    # 创建快照目录结构
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()

    # 创建多个快照目录
    snapshots = [
        "20231201-120000",
        "20231202-115959",
        "20231202-120000"
    ]

    for snapshot in snapshots:
        snapshot_path = snapshot_dir / snapshot
        snapshot_path.mkdir()

        (snapshot_path / "comfyui").mkdir()
        (snapshot_path / "comfyui/test.txt").write_text("test content")
        tar_path = snapshot_path / "venv.tar"
        with tarfile.open(tar_path, "w") as tar:
            test_content = "This is a test file in venv"
            test_file = io.BytesIO(test_content.encode())

            tarinfo = tarfile.TarInfo(name="test_venv.txt")
            tarinfo.size = len(test_content)

            tar.addfile(tarinfo, test_file)

    constants.SNAPSHOT_DIR = str(snapshot_dir)
    constants.WORK_DIR = str(tmp_path / "work")
    os.makedirs(constants.WORK_DIR, exist_ok=True)

    return tmp_path


def test_select_snapshot_latest(setup_snapshot_files):
    result = _select_snapshot()
    assert result == os.path.join(constants.SNAPSHOT_DIR, "20231202-120000")


def test_select_snapshot_specific(setup_snapshot_files):
    result = _select_snapshot("20231202-115959")
    assert result == os.path.join(constants.SNAPSHOT_DIR, "20231202-115959")


def test_select_snapshot_nonexistent(setup_snapshot_files):
    result = _select_snapshot("20231204-120000")
    assert result is None


def test_select_snapshot_invalid_format(setup_snapshot_files):
    invalid_snapshot = os.path.join(constants.SNAPSHOT_DIR, "invalid_format")
    os.makedirs(invalid_snapshot)

    result = _select_snapshot()
    assert result == os.path.join(constants.SNAPSHOT_DIR, "20231202-120000")


def test_start_with_real_files(setup_snapshot_files):
    start()

    copied_file_comfyui = os.path.join(constants.WORK_DIR, "comfyui", "test.txt")
    assert os.path.exists(copied_file_comfyui)
    with open(copied_file_comfyui, 'r') as f:
        assert f.read() == "test content"

    copied_file_venv = os.path.join(constants.WORK_DIR, "venv.tar")
    assert not os.path.exists(copied_file_venv)

    extracted_file = os.path.join(constants.WORK_DIR, "test_venv.txt")
    assert os.path.exists(extracted_file)


def test_save_with_real_files(setup_snapshot_files):
    comfyui_dir = os.path.join(constants.WORK_DIR, "comfyui")
    venv_dir = os.path.join(constants.WORK_DIR, "venv")
    os.makedirs(comfyui_dir)
    os.makedirs(venv_dir)
    with open(os.path.join(comfyui_dir, "test.txt"), 'w') as f:
        f.write("comfyui test content")
    with open(os.path.join(venv_dir, "test.txt"), 'w') as f:
        f.write("venv test content")

    save()

    latest_snapshot = _select_snapshot()
    assert latest_snapshot is not None
    assert latest_snapshot is not "20231202-120000"

    copied_comfyui_file = os.path.join(latest_snapshot, "comfyui", "test.txt")
    assert os.path.exists(copied_comfyui_file)
    with open(copied_comfyui_file, 'r') as f:
        assert f.read() == "comfyui test content"

    copied_venv_tar = os.path.join(latest_snapshot, "venv.tar")
    assert os.path.exists(copied_venv_tar)


@pytest.fixture(autouse=True)
def cleanup(setup_snapshot_files):
    yield
    # 测试后清理临时文件
    shutil.rmtree(setup_snapshot_files)
