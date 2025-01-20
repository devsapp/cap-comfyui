import time
import os
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

from utils import file_ops
import constants


class SnapshotManager:
    USE_LATEST = "latest"

    def __init__(self):
        self.cur_snapshot_name: Optional[str] = None

    @contextmanager
    def timer(self, operation: str):
        print(f"{operation} ...")
        start_time = time.time()
        try:
            yield
        finally:
            execution_time = time.time() - start_time
            print(f"{operation} finished, cost: {execution_time:.2f}s")

    def load(self, snapshot_name: str) -> Optional[str]:
        """
        加载快照
        Args:
            snapshot_name: 目标快照名称；若为USE_LATEST，则从用户挂载目录中寻找最近一次快照并加载；若快照已加载则不会重复加载。
        Returns:
            最终使用的快照名称；None表示不加载任何快照，使用镜像中的comfyui环境
        """
        target_snapshot_name = (
            self._select_latest_snapshot() if snapshot_name == self.USE_LATEST
            else snapshot_name
        )

        if target_snapshot_name == self.cur_snapshot_name:
            return target_snapshot_name

        if target_snapshot_name is None:
            return self.cur_snapshot_name

        snapshot_path = os.path.join(constants.SNAPSHOT_DIR, target_snapshot_name)
        if not os.path.exists(snapshot_path):
            return self.cur_snapshot_name

        # 清理工作目录
        with self.timer("Clearing work dir"):
            file_ops.remove(constants.WORK_DIR + "/comfyui")
            file_ops.remove(constants.WORK_DIR + "/venv")

        # 下载快照
        with self.timer(f"Downloading snapshot from {snapshot_path}"):
            file_ops.copy(snapshot_path + "/comfyui", constants.WORK_DIR + "/comfyui")
            file_ops.copy(snapshot_path + "/venv.tar", constants.WORK_DIR + "/venv.tar")

        # 解压依赖
        with self.timer("Extracting dependencies"):
            file_ops.extract(constants.WORK_DIR + "/venv.tar")
            file_ops.remove(constants.WORK_DIR + "/venv.tar")

        self.cur_snapshot_name = target_snapshot_name
        return target_snapshot_name

    def _select_latest_snapshot(self):
        """
        获取最近一次快照名称

        Returns:
            str or None: 所选快照目录的名称，如果不存在任何快照目录则返回None
        """
        snapshots = self.find_valid_snapshots()
        if not snapshots:
            return None
        else:
            return snapshots[0]

    def find_valid_snapshots(self):
        """
        获取所有符合规范的快照目录列表

        Returns:
            list[str]: 按时间排序的有效快照目录名称列表
        """
        if not os.path.exists(constants.SNAPSHOT_DIR):
            return []

        try:
            folders = (f for f in os.scandir(constants.SNAPSHOT_DIR) if f.is_dir())

            # 过滤出符合日期格式的文件夹名
            valid_snapshots = [
                f.name for f in folders
                if self._is_valid_snapshot_name(f.name)
            ]

            # 按时间戳排序
            return sorted(valid_snapshots, reverse=True)

        except OSError:
            return []

    def _is_valid_snapshot_name(self, folder_name):
        try:
            datetime.strptime(folder_name, constants.SNAPSHOT_PATTERN)
            return True
        except ValueError:
            return False

    def save(self) -> str:
        snapshot_name = datetime.now().strftime(constants.SNAPSHOT_PATTERN)
        snapshot_path = os.path.join(constants.SNAPSHOT_DIR, snapshot_name)
        os.makedirs(snapshot_path, exist_ok=True)

        # 打包
        with self.timer("Compressing dependencies"):
            file_ops.compress(constants.WORK_DIR + "/venv.tar", constants.WORK_DIR, ["venv"])

        # 上传
        with self.timer(f"Uploading snapshot to {snapshot_path}"):
            file_ops.copy(constants.WORK_DIR + "/comfyui", snapshot_path + "/comfyui")
            file_ops.copy(constants.WORK_DIR + "/venv.tar", snapshot_path + "/venv.tar")

        self.cur_snapshot_name = snapshot_name
        return snapshot_name
