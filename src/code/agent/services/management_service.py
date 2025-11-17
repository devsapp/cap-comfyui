from enum import Enum
from threading import Lock
from typing import Dict, Set, Optional
import subprocess
import os

import constants
from exceptions.exceptions import StateTransitionError
from services.process.backend_process_manager import BackendProcessManager
from services.workspace.snapshot_manager import SnapshotManager
from utils.timer import timer


class BackendStatus(Enum):
    STOPPED = "Stopped"
    STARTING = "Starting"
    RUNNING = "Running"
    SAVING = "Saving"
    STOPPING = "Stopping"


class Action(Enum):
    START = "start"
    STOP = "stop"
    SAVE = "save"


class StartingSubStatus(Enum):
    DOWNLOADING = "Downloading"
    EXTRACTING = "Extracting"
    INSTALLING = "Installing"
    BOOTING = "Booting"


class SavingSubStatus(Enum):
    PACKAGING = "Packaging"
    UPLOADING = "Uploading"


def singleton(cls):
    _instances = {}

    def get_instance(*args, **kwargs):
        if cls not in _instances:
            _instances[cls] = cls(*args, **kwargs)
        return _instances[cls]

    return get_instance


@singleton
class ManagementService:
    _VALID_TRANSITIONS: Dict[BackendStatus, Set[BackendStatus]] = {
        BackendStatus.STOPPED: {BackendStatus.STARTING},
        BackendStatus.STARTING: {BackendStatus.RUNNING, BackendStatus.STOPPED},
        BackendStatus.RUNNING: {BackendStatus.SAVING, BackendStatus.STOPPING},
        BackendStatus.SAVING: {BackendStatus.RUNNING},
        BackendStatus.STOPPING: {BackendStatus.STOPPED, BackendStatus.RUNNING}
    }

    def __init__(self):
        self._process_mgr = BackendProcessManager()  # 管理ComfyUI/SD子进程
        self._snapshot_mgr = SnapshotManager()  # 管理实例磁盘空间中的工作空间快照
        self._status = BackendStatus.STOPPED  # 服务进程状态
        self._sub_status = ""  # 服务进程子状态，例如启动过程中的"下载"、"解压"、"服务启动"
        self._latest_action = None  # 最近一次管控行为，包含start、stop、save
        self._status_lock = Lock()

    def _transition_to(self, new_status: BackendStatus, action: Action) -> None:
        with self._status_lock:
            if new_status not in self._VALID_TRANSITIONS[self._status]:
                raise StateTransitionError(self._status, new_status)
            self._status = new_status
            self._latest_action = action

    @property
    def status(self) -> BackendStatus:
        with self._status_lock:
            return self._status

    @property
    def latest_action(self) -> Action:
        with self._status_lock:
            return self._latest_action

    @property
    def sub_status(self) -> str:
        return self._sub_status

    @sub_status.setter
    def sub_status(self, value: str) -> None:
        self._sub_status = value

    @property
    def cur_snapshot_name(self) -> Optional[str]:
        return self._snapshot_mgr.snapshot_name

    # 哨兵对象，表示启动时是否跳过依赖安装流程
    _SKIP_INSTALL_SENTINEL = object()

    def _mount_shared_models(self) -> None:
        """
        使用 unionfs-fuse 将共享模型目录和用户模型目录合并挂载到 ComfyUI models 目录。
        
        挂载结构：
        - user_models_dir (RW): 用户自己的模型目录，可读写
        - shared_models_dir (RO): 共享的模型目录，只读
        - comfyui_models_dir: ComfyUI 使用的模型目录（挂载点）
        
        使用 copy-on-write (cow) 模式：
        - 读取时：优先从用户目录读取，如果不存在则从共享目录读取
        - 写入时：所有写入都发生在用户目录，共享目录保持只读
        """
        # 定义目录路径
        user_models_dir = f"{constants.MNT_DIR}/models"
        shared_models_dir = "/mnt/shared/models"
        comfyui_models_dir = f"{constants.COMFYUI_DIR}/models"
        
        # 检查并创建 shared_models_dir
        if not os.path.exists(shared_models_dir):
            print(f"Warning: Shared models directory {shared_models_dir} does not exist, creating empty directory")
            os.makedirs(shared_models_dir, exist_ok=True)
        elif not os.listdir(shared_models_dir):
            print(f"Warning: Shared models directory {shared_models_dir} is empty")
        
        # 确保挂载点目录存在
        os.makedirs(comfyui_models_dir, exist_ok=True)
        os.makedirs(user_models_dir, exist_ok=True)

        # 执行 unionfs-fuse 挂载：将用户模型目录（RW）和共享模型目录（RO）合并到 ComfyUI 模型目录
        # nonempty: 允许挂载到非空目录（原目录内容会被隐藏，但不会被删除）
        # cow: copy-on-write 模式
        unionfs_cmd = [
            "unionfs-fuse",
            "-o", "cow,nonempty",
            f"{user_models_dir}=RW:{shared_models_dir}=RO",
            comfyui_models_dir
        ]
        print(f"Mounting shared models: {' '.join(unionfs_cmd)}")
        subprocess.run(unionfs_cmd, check=True)
        print(f"Successfully mounted: {user_models_dir}(RW) + {shared_models_dir}(RO) -> {comfyui_models_dir}")

    def install_custom_nodes(self, nodes_map: Optional[Dict] = None, timeout: int = constants.DEFAULT_INSTALL_TIMEOUT) -> Dict:
        """
        安装自定义节点的依赖包。
        
        Args:
            nodes_map: 控制插件依赖的安装行为。
                - None: 尝试安装所有在 `custom_nodes` 目录中找到的可用插件。
                - 字典: 具体的安装内容由字典决定：
                    - 非空字典 (例: {'NodeA': 'v1'}): 只安装字典中指定的有效插件。
                    - 空字典 ({}): 启动安装流程，但不安装任何插件。
            timeout: 安装超时时间（秒），默认使用 constants.DEFAULT_INSTALL_TIMEOUT（10分钟）。
        
        Returns:
            Dict: install_all 的返回结果，包含 baseline、dependencies 和 scripts
        """
        from services.pip.pip_installer import PIPInstaller
        installer = PIPInstaller()
        return installer.install_all(timeout=timeout, nodes_map=nodes_map)

    def start(self, snapshot_name: str, nodes_map: Optional[Dict] = _SKIP_INSTALL_SENTINEL) -> Dict:
        """
        启动ComfyUI服务。

        Args:
            snapshot_name: 要加载的快照名称。
            nodes_map: 控制插件依赖的安装行为。它的值决定了是否以及如何执行安装。

                - 不提供此参数 (默认行为):
                  完全跳过安装流程。不会创建 `PIPInstaller` 实例，也不会有任何安装相关的操作和计时。通过内部的哨兵对象实现。

                - 提供 `None`:
                  执行安装流程，并尝试安装所有在 `custom_nodes` 目录中找到的可用插件。

                - 提供一个字典 (`dict`):
                  执行安装流程。具体的安装内容由字典决定：
                    - 非空字典 (例: `{'NodeA': 'v1'}`): 只安装字典中指定的有效插件。
                    - 空字典 (`{}`): 启动安装流程，但不安装任何插件。这个场景可用于获取环境的依赖基线(`install_baseline`)而不执行任何实际安装。
        """
        print(f"Starting backend process using snapshot '{snapshot_name}'...")
        self._transition_to(BackendStatus.STARTING, Action.START)
        self.sub_status = StartingSubStatus.DOWNLOADING.value

        try:
            result_map = {}

            # 加载快照逻辑
            if str(constants.SKIP_SNAPSHOT_LOADING).lower() == 'true':
                self._snapshot_mgr.prepare_link()
            else:
                result_map = self._snapshot_mgr.load(snapshot_name)

            # 挂载共享模型目录到 ComfyUI models 目录
            self._mount_shared_models()

            # 安装缺失插件依赖
            if nodes_map is not self._SKIP_INSTALL_SENTINEL:
                self.sub_status = StartingSubStatus.INSTALLING.value
                with timer("Install custom_nodes packages") as t_install_process:
                    install_result = self.install_custom_nodes(nodes_map)
                    result_map.update(install_result)
                result_map["time_install_process"] = round(t_install_process.elapsed, 2)

            # 启动ComfyUI服务子进程
            self.sub_status = StartingSubStatus.BOOTING.value
            with timer("Start process") as t_start_process:
                self._process_mgr.start(constants.BOOT_CMD)
                self._process_mgr.wait_until_ready()
            result_map["time_start_process"] = round(t_start_process.elapsed, 2)

            self._transition_to(BackendStatus.RUNNING, Action.START)
            self.sub_status = ""
            return result_map
        except Exception:
            self._transition_to(BackendStatus.STOPPED, Action.START)
            self.sub_status = ""
            raise

    def save(self, snapshot_type: str) -> Dict:
        print(f"Saving workspace (type {snapshot_type})...")
        self._transition_to(BackendStatus.SAVING, Action.SAVE)
        self.sub_status = SavingSubStatus.PACKAGING.value

        try:
            result_map = self._snapshot_mgr.save(snapshot_type)
            self._transition_to(BackendStatus.RUNNING, Action.SAVE)
            self.sub_status = ""
            return result_map
        except Exception:
            self._transition_to(BackendStatus.RUNNING, Action.SAVE)
            self.sub_status = ""
            raise

    def stop(self) -> Dict:
        print("Stopping workspace...")
        self._transition_to(BackendStatus.STOPPING, Action.STOP)

        try:
            result_map = {}
            with timer("Stop process") as t_stop_process:
                self._process_mgr.stop()
            result_map["time_stop_process"] = round(t_stop_process.elapsed, 2)
            self._transition_to(BackendStatus.STOPPED, Action.STOP)
            return result_map
        except Exception:
            self._transition_to(BackendStatus.RUNNING, Action.STOP)
            raise

    def save_and_stop(self, snapshot_type: str) -> Dict:
        print(f"Saving and Stopping workspace (type {snapshot_type})...")
        result_map = self.save(snapshot_type)
        stop_result_map = self.stop()
        result_map.update(stop_result_map)
        return result_map

    @property
    def SKIP_INSTALL_SENTINEL(self):
        return self._SKIP_INSTALL_SENTINEL
