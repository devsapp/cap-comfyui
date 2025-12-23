import os
from datetime import datetime
from typing import Optional, Dict

import constants
from utils.timer import timer
from utils.logger import log


class SnapshotManager:
    USE_LATEST_DEV = "latest-dev"
    USE_LATEST_PROD = "latest-prod"
    TYPE_DEV = "dev"
    TYPE_PROD = "prod"

    def __init__(self):
        self.cur_snapshot_name: Optional[str] = None

    @property
    def snapshot_name(self) -> Optional[str]:
        return self.cur_snapshot_name

    @snapshot_name.setter
    def snapshot_name(self, value: Optional[str]) -> None:
        self.cur_snapshot_name = value

    def load(self, snapshot_name: str) -> Dict:
        """
        加载快照。

        Args:
            snapshot_name (str): 目标快照名称。
                若为USE_LATEST_XX，则从用户挂载目录中寻找对应类别最近一次快照并加载。
                若快照已加载或找不到对应快照，则直接跳过。

        Returns:
            Dict: 快照名称及各阶段耗时信息。
        """
        target_snapshot_name = snapshot_name
        if snapshot_name == self.USE_LATEST_DEV:
            target_snapshot_name = self._select_latest_snapshot(self.TYPE_DEV)
        elif snapshot_name == self.USE_LATEST_PROD:
            target_snapshot_name = self._select_latest_snapshot(self.TYPE_PROD)

        if target_snapshot_name == self.cur_snapshot_name:  # 若已加载，则跳过
            return {"snapshot": self.cur_snapshot_name}

        if target_snapshot_name is None:  # 若找不到目标快照，则跳过
            return {"snapshot": self.cur_snapshot_name}

        snapshot_path = os.path.join(constants.SNAPSHOT_DIR, target_snapshot_name)  # 若目标快照目录不存在，则跳过
        if not os.path.exists(snapshot_path):
            raise RuntimeError(f"Workspace snapshot '{target_snapshot_name}' not found")

        # 加载快照
        from services.workspace.snapshot_loader import ComfyUIDevSnapshotLoader
        from services.workspace.snapshot_loader import ComfyUIProdSnapshotLoader
        from services.workspace.snapshot_loader import SDSnapshotLoader
        if constants.BACKEND_TYPE == constants.TYPE_COMFYUI:
            if constants.USE_API_MODE:
                loader = ComfyUIProdSnapshotLoader(timer)
            else:
                loader = ComfyUIDevSnapshotLoader(timer)
        else:
            loader = SDSnapshotLoader(timer)

        result_map = loader.load(snapshot_path)

        self.cur_snapshot_name = target_snapshot_name
        result_map["snapshot"] = target_snapshot_name
        return result_map

    def save(self, snapshot_type: str, snapshot_name: Optional[str] = None) -> Dict:
        """
        保存快照。

        Args:
            snapshot_type (str): 目标快照类型。可选值"dev"和"prod"
            snapshot_name (str, optional): 指定快照名称。如果不提供，则自动生成。
                                           用于 preStop 场景下主进程预先生成名称。

        Returns:
            Dict: 已保存的快照名称及各阶段耗时信息。
        """

        if snapshot_name is None:
            snapshot_name_suffix = datetime.utcnow().strftime(constants.SNAPSHOT_PATTERN)
            snapshot_name = f"{snapshot_type}-{snapshot_name_suffix}"

        from services.workspace.snapshot_saver import ComfyUISnapshotSaver
        from services.workspace.snapshot_saver import SDSnapshotSaver
        saver = (
            ComfyUISnapshotSaver(timer) if constants.BACKEND_TYPE == constants.TYPE_COMFYUI
            else SDSnapshotSaver(timer)
        )

        if snapshot_type == self.TYPE_DEV:
            result_map = saver.save(snapshot_name, remove_old=True, old_snapshot_name=self.cur_snapshot_name)
        elif snapshot_type == self.TYPE_PROD:
            result_map = saver.save(snapshot_name)
        else:
            raise RuntimeError("Unsupported snapshot type")

        self.cur_snapshot_name = snapshot_name
        result_map["snapshot"] = snapshot_name
        return result_map

    def cleanup_incomplete_save(self, snapshot_name: str) -> None:
        """
        清理未完成的快照保存。
        在 preStop 超时时调用，清理临时压缩文件和未完成的快照目录。
        
        Args:
            snapshot_name: 要清理的快照名称。
        """
        from utils import file_ops
        
        log("INFO", f"Starting cleanup of incomplete save: {snapshot_name}")
        
        # 清理工作目录中的临时压缩文件
        temp_files = [
            f"{constants.WORK_DIR}/venv.tar.zst",
            f"{constants.WORK_DIR}/comfyui.tar.zst",
        ]
        
        for temp_file in temp_files:
            if os.path.exists(temp_file):
                try:
                    file_ops.remove(temp_file)
                except Exception as e:
                    log("WARNING", f"Failed to clean up temp file {temp_file}: {e}")
        
        # 清理未完成的快照目录
        incomplete_snapshot_path = os.path.join(constants.SNAPSHOT_DIR, snapshot_name)
        if os.path.exists(incomplete_snapshot_path):
            try:
                file_ops.remove(incomplete_snapshot_path)
                log("INFO", f"Cleaned up incomplete snapshot directory: {incomplete_snapshot_path}")
            except Exception as e:
                log("ERROR", f"Failed to clean up incomplete snapshot {incomplete_snapshot_path}: {e}")
        
        log("INFO", "Cleanup of incomplete save completed")

    def prepare_link(self):
        """
        跳过快照加载时，仍需在启动时创建到NAS/OSS的软链接，适用于通过镜像发布的场景。
        """
        from services.workspace.snapshot_loader import ComfyUIDevSnapshotLoader
        from services.workspace.snapshot_loader import ComfyUIProdSnapshotLoader
        from services.workspace.snapshot_loader import SDSnapshotLoader
        if constants.BACKEND_TYPE == constants.TYPE_COMFYUI:
            if constants.USE_API_MODE:
                loader = ComfyUIProdSnapshotLoader(timer)
            else:
                loader = ComfyUIDevSnapshotLoader(timer)
        else:
            loader = SDSnapshotLoader(timer)

        loader.prepare_link()

    def _select_latest_snapshot(self, snapshot_type: str):
        """
        获取最近一次快照名称

        Returns:
            str or None: 所选快照目录的名称，如果不存在任何快照目录则返回None
        """
        snapshots = self.find_valid_snapshots(snapshot_type)
        if not snapshots:
            return None
        else:
            return snapshots[0]

    def find_valid_snapshots(self, snapshot_type: str):
        """
        获取所有符合规范的快照目录列表

        Returns:
            list[str]: 按时间排序的有效快照目录名称列表
        """
        if not os.path.exists(constants.SNAPSHOT_DIR):
            return []

        try:
            folders = (f for f in os.scandir(constants.SNAPSHOT_DIR) if f.is_dir())

            # 过滤出符合格式的文件夹名
            valid_snapshots = [
                f.name for f in folders
                if self._is_valid_snapshot_name(snapshot_type, f.name)
            ]

            # 按时间戳排序
            return sorted(valid_snapshots, reverse=True)

        except OSError:
            return []

    def _is_valid_snapshot_name(self, snapshot_type: str, folder_name: str) -> bool:
        # 检查前缀
        prefix = f"{snapshot_type}-"
        if not folder_name.startswith(prefix):
            return False

        # 移除前缀后检查日期时间格式
        datetime_part = folder_name[len(prefix):]
        try:
            datetime.strptime(datetime_part, constants.SNAPSHOT_PATTERN)
            return True
        except ValueError:
            return False
