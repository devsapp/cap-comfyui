import os
from datetime import datetime
from typing import Optional, Dict

import constants
from utils.timer import timer
from utils import file_ops


class SnapshotManager:
    USE_LATEST_DEV = "latest-dev"
    USE_LATEST_PROD = "latest-prod"
    TYPE_DEV = "dev"
    TYPE_PROD = "prod"

    def __init__(self):
        self.cur_snapshot_name: Optional[str] = None

    def load(self, snapshot_name: str) -> Dict:
        """
        加载快照
        Args:
            snapshot_name: 目标快照名称；若为USE_LATEST_XX，则从用户挂载目录中寻找对应类别最近一次快照并加载；若快照已加载则不会重复加载。
        Returns:
            最终使用的快照名称；None表示不加载任何快照，使用镜像中的comfyui/sd环境
        """
        target_snapshot_name = snapshot_name
        if snapshot_name == self.USE_LATEST_DEV:
            target_snapshot_name = self._select_latest_snapshot(self.TYPE_DEV)
        elif snapshot_name == self.USE_LATEST_PROD:
            target_snapshot_name = self._select_latest_snapshot(self.TYPE_PROD)

        if target_snapshot_name == self.cur_snapshot_name:  # 若已加载，则跳过
            return {"snapshot": self.cur_snapshot_name}

        if target_snapshot_name is None:  # 若找不到目标快照，则跳过，使用镜像内快照
            return {"snapshot": self.cur_snapshot_name}

        snapshot_path = os.path.join(constants.SNAPSHOT_DIR, target_snapshot_name)  # 若目标快照目录不存在，则跳过
        if not os.path.exists(snapshot_path):
            raise RuntimeError(f"Workspace snapshot '{target_snapshot_name}' not found")

        # 加载快照
        from services.workspace.snapshot_loader import ComfyUISnapshotLoader
        from services.workspace.snapshot_loader import SDSnapshotLoader
        loader = (
            ComfyUISnapshotLoader(timer) if constants.BACKEND_TYPE == constants.TYPE_COMFYUI
            else SDSnapshotLoader(timer)
        )
        result_map = loader.load(snapshot_path)

        self.cur_snapshot_name = target_snapshot_name
        result_map["snapshot"] = target_snapshot_name
        return result_map

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

    def save(self, snapshot_type: str) -> Dict:
        snapshot_name_suffix = datetime.now().strftime(constants.SNAPSHOT_PATTERN)
        snapshot_name = f"{snapshot_type}-{snapshot_name_suffix}"

        from services.workspace.snapshot_saver import ComfyUISnapshotSaver
        from services.workspace.snapshot_saver import SDSnapshotSaver
        saver = (
            ComfyUISnapshotSaver(timer) if constants.BACKEND_TYPE == constants.TYPE_COMFYUI
            else SDSnapshotSaver(timer)
        )

        result_map = {}
        if snapshot_type == self.TYPE_DEV:
            result_map = saver.save(snapshot_name, remove_old=True, old_snapshot_name=self.cur_snapshot_name)
        elif snapshot_type == self.TYPE_PROD:
            result_map = saver.save(snapshot_name)
        else:
            raise RuntimeError("Unsupported snapshot type")

        self.cur_snapshot_name = snapshot_name
        result_map["snapshot"] = snapshot_name
        return result_map

    def copy(self, snapshot_name: str) -> Dict:
        src_snapshot_name = snapshot_name
        if snapshot_name == self.USE_LATEST_DEV:
            src_snapshot_name = self._select_latest_snapshot(self.TYPE_DEV)
        elif snapshot_name == self.USE_LATEST_PROD:
            src_snapshot_name = self._select_latest_snapshot(self.TYPE_PROD)

        if src_snapshot_name is None:  # 若找不到目标快照，则抛错
            raise RuntimeError(f"Snapshot '{snapshot_name}' not found")

        src_snapshot_path = os.path.join(constants.SNAPSHOT_DIR, src_snapshot_name)  # 若源快照目录不存在，则抛错
        if not os.path.exists(src_snapshot_path):
            raise RuntimeError(f"Snapshot '{src_snapshot_path}' not found")

        snapshot_name_suffix = datetime.now().strftime(constants.SNAPSHOT_PATTERN)
        target_snapshot_name = f"{self.TYPE_PROD}-{snapshot_name_suffix}"
        target_snapshot_path = os.path.join(constants.SNAPSHOT_DIR, target_snapshot_name)

        file_ops.copy(src_snapshot_path, target_snapshot_path)
        return {"snapshot_src": src_snapshot_name, "snapshot_dst": target_snapshot_name}
