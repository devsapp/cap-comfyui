import os
from abc import ABC, abstractmethod
from typing import Dict, Optional

from utils import file_ops
import constants


class SnapshotSaver(ABC):
    def __init__(self, timer):
        self.timer = timer

    def save(self, snapshot_name: str, auto_cleanup: bool = False, cleanup_prefix: Optional[str] = None, max_snapshots: int = 3) -> Dict:
        """
        保存快照，可选择性地自动清理旧快照
        
        Args:
            snapshot_name: 快照名称（如 'dev-20260210-120000'）
            auto_cleanup: 是否自动清理旧快照。默认 False 不清理。
                         只有设置为 True 时，才会触发清理逻辑。
            cleanup_prefix: 要清理的快照前缀（如 'dev'）。
                           只有当 auto_cleanup=True 时才生效。
                           用于匹配要清理的快照（如 'dev-*'）。
            max_snapshots: 当 auto_cleanup=True 时，保留的最大快照数量，默认 3 个
        
        Returns:
            Dict: 各阶段耗时信息，如果执行了清理，会包含 'cleaned_snapshots' 字段
        
        Examples:
            # 不清理旧快照（默认行为，安全）
            save("prod-20260210-120000")
            
            # 自动清理旧的 dev 快照，保留最新 3 个
            save("dev-20260210-120000", auto_cleanup=True, cleanup_prefix="dev", max_snapshots=3)
        """
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

        # 自动清理旧快照（需要显式启用且提供前缀）
        if auto_cleanup and cleanup_prefix:
            with self.timer(f"Cleaning old {cleanup_prefix} snapshots") as t_clean:
                cleaned_count = self._cleanup_old_snapshots(cleanup_prefix, max_snapshots)
            stage_cost["time_clean"] = round(t_clean.elapsed, 2)
            stage_cost["cleaned_snapshots"] = cleaned_count

        return stage_cost
    
    def _cleanup_old_snapshots(self, snapshot_type: str, max_snapshots: int) -> int:
        """
        清理指定类型的旧快照，保留最新的 N 个
        
        Args:
            snapshot_type: 快照类型前缀（如 'dev'）
            max_snapshots: 保留的最大快照数量
        
        Returns:
            int: 清理的快照数量
        """
        from utils.logger import log
        
        # 列出所有该类型的快照
        try:
            all_snapshots = [
                d for d in os.listdir(constants.SNAPSHOT_DIR)
                if d.startswith(f"{snapshot_type}-") and 
                os.path.isdir(os.path.join(constants.SNAPSHOT_DIR, d))
            ]
        except FileNotFoundError:
            return 0
        
        # 如果快照数量未超过限制，不需要清理
        if len(all_snapshots) <= max_snapshots:
            return 0
        
        # 按名称排序（快照名称包含时间戳，名称排序即时间排序）
        all_snapshots.sort()
        
        # 计算需要删除的快照数量
        snapshots_to_remove = all_snapshots[:-max_snapshots]  # 保留最新的 N 个
        
        log("INFO", f"Found {len(all_snapshots)} {snapshot_type} snapshots, keeping latest {max_snapshots}, removing {len(snapshots_to_remove)}")
        
        # 删除旧快照
        for old_snapshot in snapshots_to_remove:
            old_snapshot_path = os.path.join(constants.SNAPSHOT_DIR, old_snapshot)
            try:
                log("INFO", f"Removing old snapshot: {old_snapshot}")
                self._clear(old_snapshot_path)
            except Exception as e:
                log("WARNING", f"Failed to remove snapshot {old_snapshot}: {e}")
        
        return len(snapshots_to_remove)

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
        # 使用 zstd 压缩（级别 10，平衡压缩比和速度）
        from utils.logger import log
        log("INFO", "Starting compression: venv")
        file_ops.compress_with_zstd(f"{constants.WORK_DIR}/venv.tar.zst", constants.WORK_DIR, ["venv"], level=10)
        
        log("INFO", "Starting compression: comfyui")
        file_ops.compress_with_zstd(f"{constants.WORK_DIR}/comfyui.tar.zst", constants.WORK_DIR, ["comfyui"], level=10)
        log("INFO", "Compression completed for all components")

    def _upload(self, snapshot_path: str):
        file_ops.copy(f"{constants.WORK_DIR}/venv.tar.zst", f"{snapshot_path}/venv.tar.zst")
        file_ops.copy(f"{constants.WORK_DIR}/comfyui.tar.zst", f"{snapshot_path}/comfyui.tar.zst")

    def _clear(self, snapshot_path: str):
        file_ops.remove(snapshot_path)


class SDSnapshotSaver(SnapshotSaver):
    def _compress(self):
        # 使用 zstd 压缩（级别 10，平衡压缩比和速度）
        from utils.logger import log
        log("INFO", "Starting compression: venv")
        file_ops.compress_with_zstd(f"{constants.WORK_DIR}/venv.tar.zst", constants.WORK_DIR, ["venv"], level=10)
        log("INFO", "Starting compression: stable-diffusion-webui")
        file_ops.compress_with_zstd(f"{constants.WORK_DIR}/stable-diffusion-webui.tar.zst", constants.WORK_DIR, ["stable-diffusion-webui"], level=10)
        if os.path.exists(f"{constants.WORK_DIR}/.cache"):
            log("INFO", "Starting compression: .cache")
            file_ops.compress_with_zstd(f"{constants.WORK_DIR}/.cache.tar.zst", constants.WORK_DIR, [".cache"], level=10)
        log("INFO", "Compression completed for all components")

    def _upload(self, snapshot_path: str):
        file_ops.copy(f"{constants.WORK_DIR}/venv.tar.zst", f"{snapshot_path}/venv.tar.zst")
        file_ops.copy(f"{constants.WORK_DIR}/stable-diffusion-webui.tar.zst", f"{snapshot_path}/stable-diffusion-webui.tar.zst")
        cache_path = f"{constants.WORK_DIR}/.cache.tar.zst"
        if os.path.exists(cache_path):
            file_ops.copy(cache_path, f"{snapshot_path}/.cache.tar.zst")

    def _clear(self, snapshot_path: str):
        file_ops.remove(snapshot_path)
