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
        with self.timer("Clearing work dir") as t_clear:
            self._clear()
        stage_cost["time_clear"] = round(t_clear.elapsed, 2)

        with self.timer(f"Downloading snapshot from {snapshot_path}") as t_download:
            self._download(snapshot_path)
        stage_cost["time_download"] = round(t_download.elapsed, 2)

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
