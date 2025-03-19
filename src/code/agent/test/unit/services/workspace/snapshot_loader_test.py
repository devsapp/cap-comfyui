import pytest
import os
import json
import shutil
import tarfile
import io

import constants
from services.workspace.snapshot_loader import ComfyUISnapshotLoader, SDSnapshotLoader


class MockTimer:
    def __init__(self, name):
        self.name = name
        self.elapsed = 1.5

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.fixture
def setup_dirs(tmp_path):
    # 设置基础目录
    constants.WORK_DIR = str(tmp_path / "work")
    constants.MNT_DIR = str(tmp_path / "mnt")
    constants.COMFYUI_DIR = str(tmp_path / "work/comfyui")
    constants.SD_DIR = str(tmp_path / "work/stable-diffusion-webui")
    constants.VENV_DIR = str(tmp_path / "work/venv")

    # 创建必要的目录
    os.makedirs(constants.WORK_DIR, exist_ok=True)
    os.makedirs(constants.MNT_DIR, exist_ok=True)
    os.makedirs(os.path.join(constants.MNT_DIR, "models"), exist_ok=True)

    return tmp_path


def create_mock_tar(path):
    """创建一个有效的测试用 tar 文件"""
    with tarfile.open(path, "w:gz") as tar:
        test_content = b"Test venv content"
        test_file = io.BytesIO(test_content)
        tarinfo = tarfile.TarInfo(name="venv/test.txt")
        tarinfo.size = len(test_content)
        tar.addfile(tarinfo, test_file)


@pytest.fixture
def mock_timer():
    return lambda x: MockTimer(x)


class TestComfyUISnapshotLoader:
    @pytest.fixture
    def loader(self, mock_timer):
        return ComfyUISnapshotLoader(mock_timer)

    def test_load_snapshot(self, setup_dirs, loader):
        # 创建测试快照
        snapshot_path = os.path.join(setup_dirs, "snapshot")
        os.makedirs(os.path.join(snapshot_path, "comfyui"))
        os.makedirs(os.path.join(snapshot_path, ".cache"))

        # 创建有效的 tar 文件
        tar_path = os.path.join(snapshot_path, "venv.tar")
        create_mock_tar(tar_path)

        # 在 comfyui 目录中创建一些测试文件
        with open(os.path.join(snapshot_path, "comfyui/test.txt"), "w") as f:
            f.write("test content")

        # 执行加载
        stage_cost = loader.load(snapshot_path)

        # 验证返回的时间统计
        assert "time_clear" in stage_cost
        assert "time_download" in stage_cost
        assert "time_extract" in stage_cost

        # 验证目录结构
        assert os.path.exists(constants.COMFYUI_DIR)
        assert os.path.exists(os.path.join(constants.COMFYUI_DIR, "test.txt"))
        assert os.path.islink(os.path.join(constants.COMFYUI_DIR, "models"))
        assert os.readlink(os.path.join(constants.COMFYUI_DIR, "models")) == \
               os.path.join(constants.MNT_DIR, "models")


class TestSDSnapshotLoader:
    @pytest.fixture
    def loader(self, mock_timer):
        return SDSnapshotLoader(mock_timer)

    def test_load_snapshot(self, setup_dirs, loader):
        # 创建测试快照
        snapshot_path = os.path.join(setup_dirs, "snapshot")
        sd_path = os.path.join(snapshot_path, "stable-diffusion-webui")
        os.makedirs(sd_path)

        # 创建测试配置文件
        config = {
            "test_key": "test_value",
            "outdir_samples": "old_path",
        }
        with open(os.path.join(sd_path, "config.json"), "w") as f:
            json.dump(config, f)

        # 创建有效的 tar 文件
        tar_path = os.path.join(snapshot_path, "venv.tar")
        create_mock_tar(tar_path)

        # 执行加载
        stage_cost = loader.load(snapshot_path)

        # 验证返回的时间统计
        assert "time_clear" in stage_cost
        assert "time_download" in stage_cost
        assert "time_extract" in stage_cost

        # 验证配置文件
        mnt_config_path = os.path.join(constants.MNT_DIR, "config.json")
        assert os.path.exists(mnt_config_path)

        with open(mnt_config_path, "r") as f:
            new_config = json.load(f)
            assert new_config["outdir_samples"] == f"{constants.MNT_DIR}/output"
            assert new_config["test_key"] == "test_value"  # 保留原有配置

        # 验证软链接
        assert os.path.islink(os.path.join(constants.SD_DIR, "models"))
        assert os.path.islink(os.path.join(constants.SD_DIR, "config.json"))

    def test_load_snapshot_existing_config(self, setup_dirs, loader):
        # 创建已存在的配置文件
        existing_config = {"existing": "config"}
        with open(os.path.join(constants.MNT_DIR, "config.json"), "w") as f:
            json.dump(existing_config, f)

        # 创建测试快照
        snapshot_path = os.path.join(setup_dirs, "snapshot")
        sd_path = os.path.join(snapshot_path, "stable-diffusion-webui")
        os.makedirs(sd_path)

        # 创建有效的 tar 文件
        tar_path = os.path.join(snapshot_path, "venv.tar")
        create_mock_tar(tar_path)

        # 执行加载
        loader.load(snapshot_path)

        # 验证现有配置未被修改
        with open(os.path.join(constants.MNT_DIR, "config.json"), "r") as f:
            config = json.load(f)
            assert config == existing_config

    def test_load_snapshot_config_update(self, setup_dirs, loader):
        """测试配置文件更新和软链接创建"""
        # 创建测试快照
        snapshot_path = os.path.join(setup_dirs, "snapshot")
        sd_path = os.path.join(snapshot_path, "stable-diffusion-webui")
        os.makedirs(sd_path)

        # 创建原始配置文件
        original_config = {
            "test_key": "test_value",
            "outdir_samples": "old_path",
            "outdir_grids": "old_grid_path",
            "outdir_save": "old_save_path",
            "outdir_init_images": "old_init_path",
            "save_init_img": False
        }
        with open(os.path.join(sd_path, "config.json"), "w") as f:
            json.dump(original_config, f)

        # 创建有效的 tar 文件
        tar_path = os.path.join(snapshot_path, "venv.tar")
        create_mock_tar(tar_path)

        # 执行加载
        loader.load(snapshot_path)

        # 验证配置文件
        mnt_config_path = os.path.join(constants.MNT_DIR, "config.json")
        sd_config_path = os.path.join(constants.SD_DIR, "config.json")

        # 验证配置文件存在
        assert os.path.exists(mnt_config_path)
        assert os.path.exists(sd_config_path)

        # 验证软链接正确创建
        assert os.path.islink(sd_config_path)
        assert os.readlink(sd_config_path) == mnt_config_path

        # 验证配置内容
        with open(mnt_config_path, "r") as f:
            new_config = json.load(f)

        # 验证更新的配置字段
        assert new_config["outdir_samples"] == f"{constants.MNT_DIR}/output"
        assert new_config["outdir_grids"] == f"{constants.MNT_DIR}/output"
        assert new_config["outdir_save"] == f"{constants.MNT_DIR}/output/saves"
        assert new_config["outdir_init_images"] == f"{constants.MNT_DIR}/input"
        assert new_config["save_init_img"] is True

        # 验证原有配置保持不变
        assert new_config["test_key"] == "test_value"

    def test_load_snapshot_existing_config_not_modified(self, setup_dirs, loader):
        """测试已存在的配置文件不被修改"""
        # 创建已存在的配置文件，包含完整的配置
        existing_config = {
            "existing": "config",
            "outdir_samples": "/custom/path",
            "outdir_grids": "/custom/grid/path",
            "outdir_save": "/custom/save/path",
            "outdir_init_images": "/custom/init/path",
            "save_init_img": False
        }
        with open(os.path.join(constants.MNT_DIR, "config.json"), "w") as f:
            json.dump(existing_config, f)

        # 创建测试快照
        snapshot_path = os.path.join(setup_dirs, "snapshot")
        sd_path = os.path.join(snapshot_path, "stable-diffusion-webui")
        os.makedirs(sd_path)

        # 创建原始配置文件
        with open(os.path.join(sd_path, "config.json"), "w") as f:
            json.dump({"test_key": "test_value"}, f)

        # 创建有效的 tar 文件
        tar_path = os.path.join(snapshot_path, "venv.tar")
        create_mock_tar(tar_path)

        # 执行加载
        loader.load(snapshot_path)

        # 验证软链接
        sd_config_path = os.path.join(constants.SD_DIR, "config.json")
        assert os.path.islink(sd_config_path)
        assert os.readlink(sd_config_path) == os.path.join(constants.MNT_DIR, "config.json")

        # 验证现有配置未被修改
        with open(os.path.join(constants.MNT_DIR, "config.json"), "r") as f:
            config = json.load(f)
            assert config == existing_config


@pytest.fixture(autouse=True)
def cleanup(setup_dirs):
    yield
    shutil.rmtree(setup_dirs)
