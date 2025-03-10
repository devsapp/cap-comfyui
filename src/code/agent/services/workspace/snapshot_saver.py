from abc import ABC, abstractmethod
from typing import Dict

from utils import file_ops
import constants


class SnapshotSaver(ABC):
    def __init__(self, timer):
        self.timer = timer

    def save(self, snapshot_path: str) -> Dict:
        stage_cost = {}
        with self.timer("Compressing dependencies") as t_compress:
            self._compress()
        stage_cost["time_compress"] = round(t_compress.elapsed, 2)

        with self.timer(f"Uploading snapshot to {snapshot_path}") as t_upload:
            self._upload(snapshot_path)
        stage_cost["time_upload"] = round(t_upload.elapsed, 2)
        return stage_cost

    @abstractmethod
    def _compress(self):
        """打包"""
        pass

    @abstractmethod
    def _upload(self, snapshot_path: str):
        """上传"""
        pass


class ComfyUISnapshotSaver(SnapshotSaver):
    def _compress(self):
        file_ops.compress(f"{constants.WORK_DIR}/venv.tar", constants.WORK_DIR, ["venv"])

    def _upload(self, snapshot_path: str):
        file_ops.copy(constants.COMFYUI_DIR, f"{snapshot_path}/comfyui")
        file_ops.copy(f"{constants.WORK_DIR}/venv.tar", f"{snapshot_path}/venv.tar")


class SDSnapshotSaver(SnapshotSaver):
    def _compress(self):
        file_ops.compress(f"{constants.WORK_DIR}/venv.tar", constants.WORK_DIR, ["venv"])

    def _upload(self, snapshot_path: str):
        file_ops.copy(constants.SD_DIR, f"{snapshot_path}/stable-diffusion-webui")
        file_ops.copy(f"{constants.WORK_DIR}/venv.tar", f"{snapshot_path}/venv.tar")
        file_ops.copy(f"{constants.WORK_DIR}/.cache", f"{snapshot_path}/.cache")
