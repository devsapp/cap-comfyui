import zipfile
import pytest
import os
import json
import shutil
import tarfile
import io

import constants
from services.workspace.snapshot_loader import ComfyUIDevSnapshotLoader, SDSnapshotLoader, ComfyUIProdSnapshotLoader


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
    constants.MODEL_DIR = str(tmp_path / "mnt/models")
    constants.COMFYUI_DIR = str(tmp_path / "work/comfyui")
    constants.SD_DIR = str(tmp_path / "work/stable-diffusion-webui")
    constants.VENV_DIR = str(tmp_path / "work/venv")

    # 创建必要的目录
    os.makedirs(constants.WORK_DIR, exist_ok=True)
    os.makedirs(constants.MNT_DIR, exist_ok=True)
    os.makedirs(constants.MODEL_DIR, exist_ok=True)
    os.makedirs(os.path.join(constants.MNT_DIR, "custom_nodes"), exist_ok=True)

    return tmp_path


def create_mock_zip(path, content_dir=None, extra_files=None, flat=False):
    """
    创建测试用zip文件
    :param path: zip文件路径
    :param content_dir: 内容目录
    :param extra_files: 额外要添加的文件字典 {"相对路径": "内容"}
    :param flat: 是否将文件直接放在根目录下，而不是在子目录中
    """
    with zipfile.ZipFile(path, 'w') as zf:
        if content_dir:
            # 确保目录存在
            os.makedirs(content_dir, exist_ok=True)

            # 添加测试文件
            test_file = os.path.join(content_dir, "test.txt")
            with open(test_file, 'w') as f:
                f.write("test content")

            arcname = "test.txt" if flat else os.path.join(os.path.basename(content_dir), "test.txt")
            zf.write(test_file, arcname)

            # 添加额外文件
            if extra_files:
                for file_path, content in extra_files.items():
                    full_path = os.path.join(content_dir, file_path)
                    os.makedirs(os.path.dirname(full_path), exist_ok=True)
                    with open(full_path, 'w') as f:
                        if isinstance(content, dict):
                            json.dump(content, f, indent=4)
                        else:
                            f.write(content)
                    arcname = file_path if flat else os.path.join(os.path.basename(content_dir), file_path)
                    zf.write(full_path, arcname)
        else:
            zf.writestr("test.txt", "test content")


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


class TestComfyUIDevSnapshotLoader:
    @pytest.fixture
    def loader(self, mock_timer):
        return ComfyUIDevSnapshotLoader(mock_timer)

    def test_load_snapshot(self, setup_dirs, loader):
        snapshot_path = os.path.join(setup_dirs, "snapshot")
        os.makedirs(snapshot_path)

        # 创建测试文件
        create_mock_tar(os.path.join(snapshot_path, "venv.tar"))
        create_mock_zip(os.path.join(snapshot_path, "comfyui.zip"), content_dir=os.path.join(setup_dirs, "comfyui"))
        create_mock_zip(os.path.join(snapshot_path, ".cache.zip"), content_dir=os.path.join(setup_dirs, ".cache"))

        stage_cost = loader.load(snapshot_path)

        # 验证时间统计
        assert all(key in stage_cost for key in ["time_clear", "time_download", "time_extract"])

        # 验证目录结构
        assert os.path.exists(constants.COMFYUI_DIR)
        assert os.path.exists(os.path.join(constants.COMFYUI_DIR, "test.txt"))

        # 验证软链接
        models_link = os.path.join(constants.COMFYUI_DIR, "models")
        custom_nodes_link = os.path.join(constants.COMFYUI_DIR, "custom_nodes")
        assert os.path.islink(models_link)
        assert os.path.islink(custom_nodes_link)
        assert os.readlink(models_link) == os.path.join(constants.MNT_DIR, "models")
        assert os.readlink(custom_nodes_link) == os.path.join(constants.MNT_DIR, "custom_nodes")


class TestComfyUIProdSnapshotLoader:
    @pytest.fixture
    def loader(self, mock_timer):
        return ComfyUIProdSnapshotLoader(mock_timer)

    def test_load_snapshot(self, setup_dirs, loader):
        snapshot_path = os.path.join(setup_dirs, "snapshot")
        os.makedirs(snapshot_path)

        # 创建测试文件
        create_mock_tar(os.path.join(snapshot_path, "venv.tar"))
        create_mock_zip(os.path.join(snapshot_path, "comfyui.zip"),
                        content_dir=os.path.join(setup_dirs, "comfyui"))
        create_mock_zip(os.path.join(snapshot_path, "custom_nodes.zip"),
                        content_dir=os.path.join(setup_dirs, "custom_nodes"),
                        flat=True)
        create_mock_zip(os.path.join(snapshot_path, ".cache.zip"),
                        content_dir=os.path.join(setup_dirs, ".cache"))

        stage_cost = loader.load(snapshot_path)

        # 验证时间统计
        assert all(key in stage_cost for key in ["time_clear", "time_download", "time_extract"])

        # 验证目录结构
        assert os.path.exists(constants.COMFYUI_DIR)
        assert os.path.exists(os.path.join(constants.COMFYUI_DIR, "test.txt"))

        # 验证软链接
        models_link = os.path.join(constants.COMFYUI_DIR, "models")
        assert os.path.islink(models_link)
        assert os.readlink(models_link) == os.path.join(constants.MNT_DIR, "models")

        # 验证custom_nodes目录
        custom_nodes_dir = os.path.join(constants.COMFYUI_DIR, "custom_nodes")
        assert os.path.exists(custom_nodes_dir)
        assert not os.path.islink(custom_nodes_dir)  # 确保不是软链接
        assert os.path.exists(os.path.join(custom_nodes_dir, "test.txt"))  # 验证custom_nodes内容

    def test_load_snapshot_without_cache(self, setup_dirs, loader):
        """测试没有cache文件的情况"""
        snapshot_path = os.path.join(setup_dirs, "snapshot")
        os.makedirs(snapshot_path)

        create_mock_tar(os.path.join(snapshot_path, "venv.tar"))
        create_mock_zip(os.path.join(snapshot_path, "comfyui.zip"),
                        content_dir=os.path.join(setup_dirs, "comfyui"))
        create_mock_zip(os.path.join(snapshot_path, "custom_nodes.zip"),
                        content_dir=os.path.join(setup_dirs, "custom_nodes"),
                        flat=True)

        stage_cost = loader.load(snapshot_path)

        # 验证时间统计
        assert all(key in stage_cost for key in ["time_clear", "time_download", "time_extract"])

        # 验证目录结构
        assert os.path.exists(constants.COMFYUI_DIR)
        assert os.path.exists(os.path.join(constants.COMFYUI_DIR, "test.txt"))

        # 验证软链接
        models_link = os.path.join(constants.COMFYUI_DIR, "models")
        assert os.path.islink(models_link)
        assert os.readlink(models_link) == os.path.join(constants.MNT_DIR, "models")

        # 验证custom_nodes目录
        custom_nodes_dir = os.path.join(constants.COMFYUI_DIR, "custom_nodes")
        assert os.path.exists(custom_nodes_dir)
        assert not os.path.islink(custom_nodes_dir)
        assert os.path.exists(os.path.join(custom_nodes_dir, "test.txt"))


class TestSDSnapshotLoader:
    @pytest.fixture
    def loader(self, mock_timer):
        return SDSnapshotLoader(mock_timer)

    def test_load_snapshot(self, setup_dirs, loader):
        snapshot_path = os.path.join(setup_dirs, "snapshot")
        os.makedirs(snapshot_path)

        # 创建测试文件
        create_mock_tar(os.path.join(snapshot_path, "venv.tar"))

        # 创建stable-diffusion-webui.zip，包含config.json
        create_mock_zip(
            os.path.join(snapshot_path, "stable-diffusion-webui.zip"),
            content_dir=os.path.join(setup_dirs, "stable-diffusion-webui"),
            extra_files={
                "config.json": {
                    "test_key": "test_value",
                    "outdir_samples": "old_path"
                }
            }
        )

        create_mock_zip(
            os.path.join(snapshot_path, ".cache.zip"),
            content_dir=os.path.join(setup_dirs, ".cache")
        )

        stage_cost = loader.load(snapshot_path)

        # 验证时间统计
        assert all(key in stage_cost for key in ["time_clear", "time_download", "time_extract"])

        # 验证目录结构
        assert os.path.exists(constants.SD_DIR)
        assert os.path.exists(os.path.join(constants.SD_DIR, "test.txt"))

        # 验证软链接
        models_link = os.path.join(constants.SD_DIR, "models")
        assert os.path.islink(models_link)
        assert os.readlink(models_link) == os.path.join(constants.MNT_DIR, "models")

        # 验证配置文件
        config_link = os.path.join(constants.SD_DIR, "config.json")
        assert os.path.islink(config_link)
        assert os.readlink(config_link) == os.path.join(constants.MNT_DIR, "config.json")

        # 验证配置内容
        with open(os.path.join(constants.MNT_DIR, "config.json"), "r") as f:
            new_config = json.load(f)
            assert new_config["outdir_samples"] == f"{constants.MNT_DIR}/output"
            assert new_config["outdir_grids"] == f"{constants.MNT_DIR}/output"
            assert new_config["outdir_save"] == f"{constants.MNT_DIR}/output/saves"
            assert new_config["outdir_init_images"] == f"{constants.MNT_DIR}/input"
            assert new_config["save_init_img"] is True
            assert new_config["test_key"] == "test_value"

    def test_load_snapshot_without_cache(self, setup_dirs, loader):
        """测试没有cache文件的情况"""
        snapshot_path = os.path.join(setup_dirs, "snapshot")
        os.makedirs(snapshot_path)

        # 创建测试文件
        create_mock_tar(os.path.join(snapshot_path, "venv.tar"))
        create_mock_zip(
            os.path.join(snapshot_path, "stable-diffusion-webui.zip"),
            content_dir=os.path.join(setup_dirs, "stable-diffusion-webui"),
            extra_files={
                "config.json": {
                    "test_key": "test_value",
                    "outdir_samples": "old_path"
                }
            }
        )

        stage_cost = loader.load(snapshot_path)

        # 验证时间统计
        assert all(key in stage_cost for key in ["time_clear", "time_download", "time_extract"])

        # 验证目录结构和软链接
        assert os.path.exists(constants.SD_DIR)
        assert os.path.exists(os.path.join(constants.SD_DIR, "test.txt"))
        assert os.path.islink(os.path.join(constants.SD_DIR, "models"))
        assert os.path.islink(os.path.join(constants.SD_DIR, "config.json"))

        # 验证配置内容
        with open(os.path.join(constants.MNT_DIR, "config.json"), "r") as f:
            new_config = json.load(f)
            assert new_config["outdir_samples"] == f"{constants.MNT_DIR}/output"
            assert new_config["test_key"] == "test_value"

    def test_load_snapshot_existing_config(self, setup_dirs, loader):
        """测试已存在配置文件的情况"""
        # 创建已存在的配置文件
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

        snapshot_path = os.path.join(setup_dirs, "snapshot")
        os.makedirs(snapshot_path)

        # 创建测试文件
        create_mock_tar(os.path.join(snapshot_path, "venv.tar"))
        create_mock_zip(
            os.path.join(snapshot_path, "stable-diffusion-webui.zip"),
            content_dir=os.path.join(setup_dirs, "stable-diffusion-webui"),
            extra_files={
                "config.json": {
                    "test_key": "test_value",
                    "outdir_samples": "old_path"
                }
            }
        )

        loader.load(snapshot_path)

        # 验证配置文件未被修改
        with open(os.path.join(constants.MNT_DIR, "config.json"), "r") as f:
            config = json.load(f)
            assert config == existing_config

        # 验证软链接
        config_link = os.path.join(constants.SD_DIR, "config.json")
        assert os.path.islink(config_link)
        assert os.readlink(config_link) == os.path.join(constants.MNT_DIR, "config.json")

        # 验证目录结构
        assert os.path.exists(constants.SD_DIR)
        assert os.path.exists(os.path.join(constants.SD_DIR, "test.txt"))
        assert os.path.islink(os.path.join(constants.SD_DIR, "models"))


@pytest.fixture(autouse=True)
def cleanup(setup_dirs):
    yield
    shutil.rmtree(setup_dirs)
