import os
from abc import ABC, abstractmethod
from typing import Dict

import constants
from utils import file_ops


class SnapshotLoader(ABC):
    def __init__(self, timer):
        self.timer = timer

    def load(self, snapshot_path: str) -> Dict:
        stage_cost = {}
        from services.management_service import ManagementService
        from services.management_service import StartingSubStatus
        service = ManagementService()
        with self.timer("Clearing work dir") as t_clear:
            self._clear()
        stage_cost["time_clear"] = round(t_clear.elapsed, 2)

        service.sub_status = StartingSubStatus.DOWNLOADING.value
        with self.timer(f"Downloading snapshot from {snapshot_path}") as t_download:
            self._download(snapshot_path)
        stage_cost["time_download"] = round(t_download.elapsed, 2)

        service.sub_status = StartingSubStatus.EXTRACTING.value
        with self.timer("Extracting snapshot") as t_extract:
            self._extract()
        stage_cost["time_extract"] = round(t_extract.elapsed, 2)

        self._create_symlinks()
        return stage_cost

    def prepare_link(self):
        with self.timer("Creating symbolic link"):
            self._create_symlinks()

    @abstractmethod
    def _clear(self):
        """清理工作目录"""
        pass

    @abstractmethod
    def _download(self, snapshot_path: str):
        """下载快照"""
        pass

    @abstractmethod
    def _extract(self):
        """解压依赖"""
        pass

    @abstractmethod
    def _create_symlinks(self):
        """创建相关目录软链接"""
        pass


class ComfyUIDevSnapshotLoader(SnapshotLoader):
    def _clear(self):
        file_ops.remove(constants.COMFYUI_DIR)
        file_ops.remove(constants.VENV_DIR)

    def _download(self, snapshot_path: str):
        file_ops.copy(f"{snapshot_path}/venv.tar", f"{constants.WORK_DIR}/venv.tar")
        file_ops.copy(f"{snapshot_path}/comfyui.zip", f"{constants.WORK_DIR}/comfyui.zip")
        cache_path = f"{snapshot_path}/.cache.zip"
        if os.path.exists(cache_path):
            file_ops.copy(cache_path, f"{constants.WORK_DIR}/.cache.zip")

    def _extract(self):
        file_ops.extract(f"{constants.WORK_DIR}/venv.tar")
        file_ops.remove(f"{constants.WORK_DIR}/venv.tar")
        file_ops.extract(f"{constants.WORK_DIR}/comfyui.zip")
        file_ops.remove(f"{constants.WORK_DIR}/comfyui.zip")
        # cache_path = f"{constants.WORK_DIR}/.cache.zip"
        # if os.path.exists(cache_path):
        #     file_ops.extract(cache_path)
        #     file_ops.remove(cache_path)

    def _create_symlinks(self):
        file_ops.create_symlink(
            source_path=f"{constants.MODEL_DIR}",
            link_path=f"{constants.COMFYUI_DIR}/models",
            force=True
        )
        file_ops.create_symlink(
            source_path=f"{constants.MNT_DIR}/custom_nodes",
            link_path=f"{constants.COMFYUI_DIR}/custom_nodes",
            force=True
        )
        file_ops.create_symlink(
            source_path=f"{constants.MNT_DIR}/.cache",
            link_path=f"{constants.COMFYUI_DIR}/.cache",
            force=True
        )


class ComfyUIProdSnapshotLoader(SnapshotLoader):
    def _clear(self):
        file_ops.remove(constants.COMFYUI_DIR)
        file_ops.remove(constants.VENV_DIR)

    def _download(self, snapshot_path: str):
        file_ops.copy(f"{snapshot_path}/venv.tar", f"{constants.WORK_DIR}/venv.tar")
        file_ops.copy(f"{snapshot_path}/comfyui.zip", f"{constants.WORK_DIR}/comfyui.zip")
        cache_path = f"{snapshot_path}/.cache.zip"
        if os.path.exists(cache_path):
            file_ops.copy(cache_path, f"{constants.WORK_DIR}/.cache.zip")
        file_ops.copy(f"{snapshot_path}/custom_nodes.zip", f"{constants.WORK_DIR}/custom_nodes.zip")

    def _extract(self):
        file_ops.extract(f"{constants.WORK_DIR}/venv.tar")
        file_ops.remove(f"{constants.WORK_DIR}/venv.tar")
        file_ops.extract(f"{constants.WORK_DIR}/comfyui.zip")
        file_ops.remove(f"{constants.WORK_DIR}/comfyui.zip")
        cache_path = f"{constants.WORK_DIR}/.cache.zip"
        # if os.path.exists(cache_path):
        #     file_ops.extract(cache_path)
        #     file_ops.remove(cache_path)
        file_ops.remove(f"{constants.COMFYUI_DIR}/custom_nodes")  # 解压时不会强制覆盖，需手动删除解压时会产生冲突的文件
        file_ops.extract(f"{constants.WORK_DIR}/custom_nodes.zip", output_dir=f"{constants.COMFYUI_DIR}/custom_nodes")
        file_ops.remove(f"{constants.WORK_DIR}/custom_nodes.zip")

    def _create_symlinks(self):
        file_ops.create_symlink(
            source_path=f"{constants.MODEL_DIR}",
            link_path=f"{constants.COMFYUI_DIR}/models",
            force=True
        )
        file_ops.create_symlink(
            source_path=f"{constants.MNT_DIR}/.cache",
            link_path=f"{constants.WORK_DIR}/.cache",
            force=True
        )


class SDSnapshotLoader(SnapshotLoader):
    def _clear(self):
        file_ops.remove(constants.SD_DIR)
        file_ops.remove(constants.VENV_DIR)

    def _download(self, snapshot_path: str):
        file_ops.copy(f"{snapshot_path}/venv.tar", f"{constants.WORK_DIR}/venv.tar")
        file_ops.copy(f"{snapshot_path}/stable-diffusion-webui.zip", f"{constants.WORK_DIR}/stable-diffusion-webui.zip")
        cache_path = f"{snapshot_path}/.cache.zip"
        if os.path.exists(cache_path):
            file_ops.copy(cache_path, f"{constants.WORK_DIR}/.cache.zip")

    def _extract(self):
        file_ops.extract(f"{constants.WORK_DIR}/venv.tar")
        file_ops.remove(f"{constants.WORK_DIR}/venv.tar")
        file_ops.extract(f"{constants.WORK_DIR}/stable-diffusion-webui.zip")
        file_ops.remove(f"{constants.WORK_DIR}/stable-diffusion-webui.zip")
        cache_path = f"{constants.WORK_DIR}/.cache.zip"
        if os.path.exists(cache_path):
            file_ops.extract(cache_path)
            file_ops.remove(cache_path)

    def _create_symlinks(self):
        file_ops.create_symlink(
            source_path=f"{constants.MODEL_DIR}",
            link_path=f"{constants.SD_DIR}/models",
            force=True
        )

        config_path = f"{constants.MNT_DIR}/config.json"
        origin_config_path = f"{constants.SD_DIR}/config.json"
        if not os.path.exists(config_path):
            print(f'Init config.json in MNT_DIR: {constants.MNT_DIR}')
            # 基于工作空间快照中的config.json作修改后写入挂载目录
            import json
            with open(origin_config_path, "r") as f:
                config = json.load(f)
            config.update({
                "outdir_samples": f"{constants.MNT_DIR}/output",  # 单图输出目录
                "outdir_grids": f"{constants.MNT_DIR}/output",  # 网格图输出目录
                "outdir_save": f"{constants.MNT_DIR}/output/saves",  # Save按钮保存图输出目录
                "outdir_init_images": f"{constants.MNT_DIR}/input",  # 图生图输入图片存储目录
                "save_init_img": True  # 图生图上传图片时是否自动保存输入图片
            })
            with open(config_path, "w") as f:
                json.dump(config, f, indent=4)

        # 将SD目录下的config.json替换为软链接
        file_ops.create_symlink(
            source_path=config_path,
            link_path=origin_config_path,
            force=True
        )
