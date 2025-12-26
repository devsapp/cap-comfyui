from enum import Enum
from threading import Lock
from typing import Dict, Set, Optional

import constants
from exceptions.exceptions import StateTransitionError
from services.process.comfyui_process_manager import ComfyUIProcessManager
from services.workspace.snapshot_manager import SnapshotManager
from utils.timer import timer


class BackendStatus(Enum):
    STOPPED = "Stopped"
    STARTING = "Starting"
    RUNNING = "Running"
    SAVING = "Saving"
    STOPPING = "Stopping"
    REBOOTING = "Rebooting"


class Action(Enum):
    START = "start"
    STOP = "stop"
    SAVE = "save"
    REBOOT = "reboot"


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
        BackendStatus.RUNNING: {BackendStatus.SAVING, BackendStatus.STOPPING, BackendStatus.REBOOTING},
        BackendStatus.SAVING: {BackendStatus.RUNNING},
        BackendStatus.STOPPING: {BackendStatus.STOPPED, BackendStatus.RUNNING},
        BackendStatus.REBOOTING: {
            BackendStatus.RUNNING,   # 重启成功
            BackendStatus.STOPPED    # 重启失败
        }
    }

    def __init__(self):
        self._process_mgr = ComfyUIProcessManager()  # 管理 ComfyUI 子进程
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
        # 记录调用前是否在 REBOOTING 状态
        was_rebooting = self.status == BackendStatus.REBOOTING
        
        print(f"Starting backend process using snapshot '{snapshot_name}'...")
        # 如果在 REBOOTING 状态，保持 REBOOTING 状态，不转换到 STARTING
        if not was_rebooting:
            self._transition_to(BackendStatus.STARTING, Action.START)
        self.sub_status = StartingSubStatus.DOWNLOADING.value

        try:
            result_map = {}

            # 加载快照逻辑
            if str(constants.SKIP_SNAPSHOT_LOADING).lower() == 'true':
                self._snapshot_mgr.prepare_link()
            else:
                result_map = self._snapshot_mgr.load(snapshot_name)
            
            # 准备共享模型目录（只对 ComfyUI 生效，必须在快照加载后执行）
            if constants.BACKEND_TYPE == constants.TYPE_COMFYUI:
                from services.model.shared_models import setup_shared_models
                setup_shared_models()

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

            # 如果之前在 REBOOTING 状态，保持 REBOOTING 状态（已经在 REBOOTING，不需要转换）
            # 否则转换到 RUNNING
            if not was_rebooting:
                self._transition_to(BackendStatus.RUNNING, Action.START)
            self.sub_status = ""
            return result_map
        except Exception:
            # 如果之前在 REBOOTING 状态，失败时转换到 STOPPED；否则保持原逻辑
            if was_rebooting:
                self._transition_to(BackendStatus.STOPPED, Action.REBOOT)
            else:
                self._transition_to(BackendStatus.STOPPED, Action.START)
            self.sub_status = ""
            raise

    def save(self, snapshot_type: str) -> Dict:
        # 记录调用前是否在 REBOOTING 状态
        was_rebooting = self.status == BackendStatus.REBOOTING
        
        print(f"Saving workspace (type {snapshot_type})...")
        # 如果在 REBOOTING 状态，保持 REBOOTING 状态，不转换到 SAVING
        if not was_rebooting:
            self._transition_to(BackendStatus.SAVING, Action.SAVE)
        self.sub_status = SavingSubStatus.PACKAGING.value

        try:
            result_map = self._snapshot_mgr.save(snapshot_type)
            # 如果之前在 REBOOTING 状态，保持 REBOOTING 状态（已经在 REBOOTING，不需要转换）
            # 否则转换到 RUNNING
            if not was_rebooting:
                self._transition_to(BackendStatus.RUNNING, Action.SAVE)
            self.sub_status = ""
            return result_map
        except Exception:
            # 如果之前在 REBOOTING 状态，失败时保持 REBOOTING；否则转换到 RUNNING
            if was_rebooting:
                # 保持在 REBOOTING 状态，不转换
                pass
            else:
                self._transition_to(BackendStatus.RUNNING, Action.SAVE)
            self.sub_status = ""
            raise

    def stop(self) -> Dict:
        # 记录调用前是否在 REBOOTING 状态
        was_rebooting = self.status == BackendStatus.REBOOTING
        
        print("Stopping workspace...")
        # 如果在 REBOOTING 状态，保持 REBOOTING 状态，不转换到 STOPPING
        if not was_rebooting:
            self._transition_to(BackendStatus.STOPPING, Action.STOP)

        try:
            result_map = {}
            
            with timer("Stop process") as t_stop_process:
                self._process_mgr.stop()
            result_map["time_stop_process"] = round(t_stop_process.elapsed, 2)
            # 如果之前在 REBOOTING 状态，保持 REBOOTING 状态（已经在 REBOOTING，不需要转换）
            # 否则转换到 STOPPED
            if not was_rebooting:
                self._transition_to(BackendStatus.STOPPED, Action.STOP)
            return result_map
        except Exception:
            # 如果之前在 REBOOTING 状态，失败时保持 REBOOTING；否则转换到 RUNNING
            if was_rebooting:
                # 保持在 REBOOTING 状态，不转换
                pass
            else:
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
