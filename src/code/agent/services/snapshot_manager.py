import time
import os
from datetime import datetime

from utils import file_ops
import constants


class SnapshotManager:
    @staticmethod
    def load():
        snapshot_path = SnapshotManager._select_snapshot()
        if snapshot_path is not None:
            # 下载
            print(f"Downloading snapshot...")
            start_time = time.time()
            file_ops.copy(snapshot_path + "/comfyui", constants.WORK_DIR + "/comfyui")
            file_ops.copy(snapshot_path + "/venv.tar", constants.WORK_DIR + "/venv.tar")
            execution_time = time.time() - start_time
            print(f"Downloaded snapshot from {snapshot_path}, cost: {execution_time} s")

            # 解压
            print(f"Extracting dependencies...")
            start_time = time.time()
            file_ops.extract(constants.WORK_DIR + "/venv.tar")
            execution_time = time.time() - start_time
            print(f"Extracted dependencies, cost {execution_time} s")
            file_ops.remove(constants.WORK_DIR + "/venv.tar")

    @staticmethod
    def save():
        snapshot_name = datetime.now().strftime(constants.SNAPSHOT_PATTERN)
        snapshot_path = os.path.join(constants.SNAPSHOT_DIR, snapshot_name)
        os.makedirs(snapshot_path, exist_ok=True)

        # 打包
        print(f"Compressing dependencies...")
        start_time = time.time()
        file_ops.compress(constants.WORK_DIR + "/venv.tar", constants.WORK_DIR, ["venv"])
        execution_time = time.time() - start_time
        print(f"Compressed dependencies, cost {execution_time} s")

        # 上传
        print(f"Uploading snapshot...")
        start_time = time.time()
        file_ops.copy(constants.WORK_DIR + "/comfyui", snapshot_path + "/comfyui")
        file_ops.copy(constants.WORK_DIR + "/venv.tar", snapshot_path + "/venv.tar")
        execution_time = time.time() - start_time
        print(f"Uploaded snapshot to {snapshot_path}, cost: {execution_time} s")

    @staticmethod
    def _select_snapshot(snapshot_name=None):
        """
        获取所选快照目录路径

        Args:
            snapshot_name (str, optional): 指定的快照名称, 格式符合SNAPSHOT_PATTERN. 默认值None表示获取最近的快照

        Returns:
            str or None: 所选快照目录的路径，如果未找到则返回None
        """

        # 如果指定了具体快照名称，直接返回对应快照的路径
        if snapshot_name:
            snapshot_path = os.path.join(constants.SNAPSHOT_DIR, snapshot_name)
            return snapshot_path if os.path.isdir(snapshot_path) else None

        # 查找最近一次快照的路径
        try:
            folders = [
                f for f in os.listdir(constants.SNAPSHOT_DIR)
                if os.path.isdir(os.path.join(constants.SNAPSHOT_DIR, f))
            ]
        except OSError:
            return None

        latest_snapshot_name = None
        latest_dt = None

        for folder in folders:
            try:
                dt = datetime.strptime(folder, constants.SNAPSHOT_PATTERN)
                if latest_dt is None or dt > latest_dt:
                    latest_dt = dt
                    latest_snapshot_name = folder
            except ValueError:
                continue

        return os.path.join(constants.SNAPSHOT_DIR, latest_snapshot_name)

