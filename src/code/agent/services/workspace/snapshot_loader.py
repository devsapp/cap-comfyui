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

        service.sub_status = StartingSubStatus.DOWNLOADING
        with self.timer(f"Downloading snapshot from {snapshot_path}") as t_download:
            self._download(snapshot_path)
        stage_cost["time_download"] = round(t_download.elapsed, 2)

        service.sub_status = StartingSubStatus.EXTRACTING
        with self.timer("Extracting dependencies") as t_extract:
            self._extract()
        stage_cost["time_extract"] = round(t_extract.elapsed, 2)

        self._create_symlinks()
        return stage_cost

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


class ComfyUISnapshotLoader(SnapshotLoader):
    def _clear(self):
        file_ops.remove(constants.COMFYUI_DIR)
        file_ops.remove(constants.VENV_DIR)

    def _download(self, snapshot_path: str):
        file_ops.copy(f"{snapshot_path}/comfyui", constants.COMFYUI_DIR)
        file_ops.copy(f"{snapshot_path}/venv.tar", f"{constants.WORK_DIR}/venv.tar")
        cache_path = f"{snapshot_path}/.cache"
        if os.path.exists(cache_path):
            file_ops.copy(cache_path, f"{constants.WORK_DIR}/.cache")

    def _extract(self):
        file_ops.extract(f"{constants.WORK_DIR}/venv.tar")
        file_ops.remove(f"{constants.WORK_DIR}/venv.tar")

    def _create_symlinks(self):
        file_ops.create_symlink(
            source_path=f"{constants.MNT_DIR}/models",
            link_path=f"{constants.COMFYUI_DIR}/models",
            force=True
        )


class SDSnapshotLoader(SnapshotLoader):
    def _clear(self):
        file_ops.remove(constants.SD_DIR)
        file_ops.remove(constants.VENV_DIR)

    def _download(self, snapshot_path: str):
        file_ops.copy(f"{snapshot_path}/stable-diffusion-webui", constants.SD_DIR)
        file_ops.copy(f"{snapshot_path}/venv.tar", f"{constants.WORK_DIR}/venv.tar")
        cache_path = f"{snapshot_path}/.cache"
        if os.path.exists(cache_path):
            file_ops.copy(cache_path, f"{constants.WORK_DIR}/.cache")

    def _extract(self):
        file_ops.extract(f"{constants.WORK_DIR}/venv.tar")
        file_ops.remove(f"{constants.WORK_DIR}/venv.tar")

    def _create_symlinks(self):
        file_ops.create_symlink(
            source_path=f"{constants.MNT_DIR}/models",
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
