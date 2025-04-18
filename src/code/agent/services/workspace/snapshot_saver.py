import os
from abc import ABC, abstractmethod
from typing import Dict

from utils import file_ops
import constants


class SnapshotSaver(ABC):
    def __init__(self, timer):
        self.timer = timer

    def save(self, snapshot_name: str, remove_old: bool = False, old_snapshot_name: str = None) -> Dict:
        snapshot_path = os.path.join(constants.SNAPSHOT_DIR, snapshot_name)
        os.makedirs(snapshot_path, exist_ok=True)
        stage_cost = {}
        from services.management_service import ManagementService
        from services.management_service import SavingSubStatus
        service = ManagementService()

        service.sub_status = SavingSubStatus.PACKAGING.value
        with self.timer("Compressing snapshot") as t_compress:
            self._compress()
        stage_cost["time_compress"] = round(t_compress.elapsed, 2)

        service.sub_status = SavingSubStatus.UPLOADING.value
        with self.timer(f"Uploading snapshot to {snapshot_path}") as t_upload:
            self._upload(snapshot_path)
        stage_cost["time_upload"] = round(t_upload.elapsed, 2)

        if remove_old and old_snapshot_name is not None:
            old_snapshot_path = os.path.join(constants.SNAPSHOT_DIR, old_snapshot_name)
            with self.timer(f"Clearing old snapshot {old_snapshot_path}") as t_clear:
                self._clear(old_snapshot_path)
            stage_cost["time_clear"] = round(t_clear.elapsed, 2)

        return stage_cost

    @abstractmethod
    def _compress(self):
        """打包"""
        pass

    @abstractmethod
    def _upload(self, snapshot_path: str):
        """上传"""
        pass

    @abstractmethod
    def _clear(self, snapshot_path: str):
        """清理旧工作空间快照"""
        pass


class ComfyUISnapshotSaver(SnapshotSaver):
    def _compress(self):
        file_ops.compress(f"{constants.WORK_DIR}/venv.tar", constants.WORK_DIR, ["venv"])
        file_ops.compress(f"{constants.WORK_DIR}/comfyui.zip", constants.WORK_DIR, ["comfyui"])
        if os.path.exists(f"{constants.WORK_DIR}/.cache"):
            file_ops.compress(f"{constants.WORK_DIR}/.cache.zip", constants.WORK_DIR, [".cache"])

    def _upload(self, snapshot_path: str):
        file_ops.copy(f"{constants.WORK_DIR}/venv.tar", f"{snapshot_path}/venv.tar")
        file_ops.copy(f"{constants.WORK_DIR}/comfyui.zip", f"{snapshot_path}/comfyui.zip")
        cache_path = f"{constants.WORK_DIR}/.cache.zip"
        if os.path.exists(cache_path):
            file_ops.copy(cache_path, f"{snapshot_path}/.cache.zip")

    def _clear(self, snapshot_path: str):
        file_ops.remove(snapshot_path)


class SDSnapshotSaver(SnapshotSaver):
    def _compress(self):
        file_ops.compress(f"{constants.WORK_DIR}/venv.tar", constants.WORK_DIR, ["venv"])
        file_ops.compress(f"{constants.WORK_DIR}/stable-diffusion-webui.zip", constants.WORK_DIR, ["stable-diffusion-webui"])
        if os.path.exists(f"{constants.WORK_DIR}/.cache"):
            file_ops.compress(f"{constants.WORK_DIR}/.cache.zip", constants.WORK_DIR, [".cache"])

    def _upload(self, snapshot_path: str):
        file_ops.copy(f"{constants.WORK_DIR}/venv.tar", f"{snapshot_path}/venv.tar")
        file_ops.copy(f"{constants.WORK_DIR}/stable-diffusion-webui.zip", f"{snapshot_path}/stable-diffusion-webui.zip")
        cache_path = f"{constants.WORK_DIR}/.cache.zip"
        if os.path.exists(cache_path):
            file_ops.copy(cache_path, f"{snapshot_path}/.cache.zip")

    def _clear(self, snapshot_path: str):
        file_ops.remove(snapshot_path)
