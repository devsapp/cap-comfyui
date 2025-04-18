import os
import pytest
import shutil

import constants
from services.workspace.snapshot_saver import SDSnapshotSaver, ComfyUISnapshotSaver


@pytest.fixture
def setup_dirs(tmp_path):
    """设置测试环境目录"""
    constants.WORK_DIR = str(tmp_path / "work")
    constants.SNAPSHOT_DIR = str(tmp_path / "snapshots")

    # 创建必要的目录
    os.makedirs(constants.WORK_DIR, exist_ok=True)
    os.makedirs(constants.SNAPSHOT_DIR, exist_ok=True)
    os.makedirs(os.path.join(constants.WORK_DIR, "venv"))
    os.makedirs(os.path.join(constants.WORK_DIR, "stable-diffusion-webui"))
    os.makedirs(os.path.join(constants.WORK_DIR, "comfyui"))
    os.makedirs(os.path.join(constants.WORK_DIR, ".cache"))

    # 创建一些测试文件
    with open(os.path.join(constants.WORK_DIR, "venv/test.txt"), "w") as f:
        f.write("test venv content")
    with open(os.path.join(constants.WORK_DIR, "stable-diffusion-webui/test.txt"), "w") as f:
        f.write("test sd content")
    with open(os.path.join(constants.WORK_DIR, "comfyui/test.txt"), "w") as f:
        f.write("test comfy content")

    return tmp_path


class MockTimer:
    def __init__(self, name):
        self.name = name
        self.elapsed = 1.5

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.fixture
def mock_timer():
    return lambda x: MockTimer(x)


@pytest.fixture(autouse=True)
def cleanup(setup_dirs):
    yield
    shutil.rmtree(setup_dirs)


class TestSDSnapshotSaver:
    @pytest.fixture
    def saver(self, mock_timer):
        return SDSnapshotSaver(mock_timer)

    def test_save_snapshot(self, setup_dirs, saver):
        """测试保存SD快照基本功能"""
        snapshot_name = "test_snapshot"
        stage_cost = saver.save(snapshot_name)

        # 验证时间统计
        assert all(key in stage_cost for key in ["time_compress", "time_upload"])
        assert "time_clear" not in stage_cost

        # 验证生成的文件
        snapshot_path = os.path.join(constants.SNAPSHOT_DIR, snapshot_name)
        assert os.path.exists(os.path.join(snapshot_path, "venv.tar"))
        assert os.path.exists(os.path.join(snapshot_path, "stable-diffusion-webui.zip"))

    def test_save_snapshot_with_cache(self, setup_dirs, saver):
        """测试保存带缓存的快照"""
        snapshot_name = "test_snapshot"
        with open(os.path.join(constants.WORK_DIR, ".cache/test.txt"), "w") as f:
            f.write("test cache")

        stage_cost = saver.save(snapshot_name)

        snapshot_path = os.path.join(constants.SNAPSHOT_DIR, snapshot_name)
        assert os.path.exists(os.path.join(snapshot_path, ".cache.zip"))

    def test_save_with_remove_old(self, setup_dirs, saver):
        """测试保存快照并删除旧快照"""
        # 创建旧快照
        old_name = "old_snapshot"
        old_path = os.path.join(constants.SNAPSHOT_DIR, old_name)
        os.makedirs(old_path)
        with open(os.path.join(old_path, "test.txt"), "w") as f:
            f.write("old snapshot")

        # 保存新快照并删除旧的
        new_name = "new_snapshot"
        stage_cost = saver.save(new_name, remove_old=True, old_snapshot_name=old_name)

        # 验证旧快照被删除
        assert not os.path.exists(old_path)
        # 验证清理时间统计
        assert "time_clear" in stage_cost


class TestComfyUISnapshotSaver:
    @pytest.fixture
    def saver(self, mock_timer):
        return ComfyUISnapshotSaver(mock_timer)

    def test_save_snapshot(self, setup_dirs, saver):
        """测试保存ComfyUI开发版快照"""
        snapshot_name = "test_snapshot"
        stage_cost = saver.save(snapshot_name)

        # 验证时间统计
        assert all(key in stage_cost for key in ["time_compress", "time_upload"])

        # 验证生成的文件
        snapshot_path = os.path.join(constants.SNAPSHOT_DIR, snapshot_name)
        assert os.path.exists(os.path.join(snapshot_path, "venv.tar"))
        assert os.path.exists(os.path.join(snapshot_path, "comfyui.zip"))

    def test_save_snapshot_with_cache(self, setup_dirs, saver):
        """测试保存带缓存的ComfyUI开发版快照"""
        snapshot_name = "test_snapshot"
        # 创建缓存文件
        with open(os.path.join(constants.WORK_DIR, ".cache/test.txt"), "w") as f:
            f.write("test cache")

        stage_cost = saver.save(snapshot_name)

        snapshot_path = os.path.join(constants.SNAPSHOT_DIR, snapshot_name)
        assert os.path.exists(os.path.join(snapshot_path, ".cache.zip"))
