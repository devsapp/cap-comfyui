import os
import time
from enum import Enum
from threading import Lock
from typing import Dict, List, Set, Optional

import constants
from exceptions.exceptions import StateTransitionError
from services.process.comfyui_process_manager import ComfyUIProcessManager
from services.workspace.snapshot_manager import SnapshotManager
from utils.timer import timer


class BackendStatus(Enum):
    RUNNING = "Running"
    SAVING = "Saving"
    REBOOTING = "Rebooting"
    REBOOT_FAILED = "RebootFailed"


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
        BackendStatus.RUNNING: {BackendStatus.SAVING, BackendStatus.REBOOTING},
        BackendStatus.SAVING: {BackendStatus.RUNNING},  # 只能转回 RUNNING
        BackendStatus.REBOOTING: {BackendStatus.RUNNING, BackendStatus.REBOOT_FAILED},
        BackendStatus.REBOOT_FAILED: set()  # 终态，不能转换到其他状态
    }

    def __init__(self):
        self._process_mgr = ComfyUIProcessManager()  # 管理 ComfyUI 子进程
        self._snapshot_mgr = SnapshotManager()  # 管理实例磁盘空间中的工作空间快照
        self._status = BackendStatus.RUNNING  # 服务进程状态，实例启动后默认为 RUNNING
        self._sub_status = ""  # 服务进程子状态，例如启动过程中的"下载"、"解压"、"服务启动"
        self._status_lock = Lock()
        self._is_stopped = False  # 标记是否已主动停止（用于 PreStop 判断）
        self._init_time = time.time()  # 实例创建时间，用于 PreStop 过滤短命实例

    def _transition_to(self, new_status: BackendStatus) -> None:
        with self._status_lock:
            if new_status not in self._VALID_TRANSITIONS[self._status]:
                raise StateTransitionError(self._status, new_status)
            self._status = new_status

    @property
    def status(self) -> BackendStatus:
        with self._status_lock:
            return self._status

    @property
    def sub_status(self) -> str:
        return self._sub_status

    @sub_status.setter
    def sub_status(self, value: str) -> None:
        self._sub_status = value

    @property
    def cur_snapshot_name(self) -> Optional[str]:
        return self._snapshot_mgr.snapshot_name

    def clone_custom_nodes(
        self,
        nodes_map: Dict,
        timeout: int = constants.DEFAULT_INSTALL_TIMEOUT,
        conflict_strategy: str = "skip",
        max_retries: Optional[int] = None,
        clone_timeout: Optional[float] = None,
        custom_nodes_dirs: Optional[List] = None,
    ) -> Dict:
        """
        将 nodes_map 中的自定义节点源码 git clone 到 custom_nodes 目录。

        Args:
            nodes_map:         key=插件名，value=含 source、version 等的配置。调用方须保证为非空字典。
            timeout:           全局超时秒数，默认使用 constants.DEFAULT_INSTALL_TIMEOUT。
            conflict_strategy: "skip" | "override"，决定目录已存在时的处理策略，默认 "skip"。
            max_retries:       单个插件 clone 失败后的最大重试次数，None 表示使用 GitCloner 默认值。
            clone_timeout:     单次 clone 命令的超时秒数，None 表示使用 GitCloner 默认值。
            custom_nodes_dirs: 存放插件的父目录列表，用于冲突检测。None = 使用默认目录。

        Returns:
            Dict: clone_all 的返回结果，包含 details 和 summary。
        """
        from services.git.git_cloner import GitCloner, MAX_CLONE_RETRIES, CLONE_TIMEOUT
        cloner = GitCloner()
        return cloner.clone_all(
            nodes_map=nodes_map,
            timeout=timeout,
            conflict_strategy=conflict_strategy,
            max_retries=max_retries if max_retries is not None else MAX_CLONE_RETRIES,
            clone_timeout=clone_timeout if clone_timeout is not None else CLONE_TIMEOUT,
            custom_nodes_dirs=custom_nodes_dirs,
        )

    def install_custom_nodes(self, nodes_map: Optional[Dict] = None, timeout: int = constants.DEFAULT_INSTALL_TIMEOUT, custom_nodes_dirs: Optional[List] = None) -> Dict:
        """
        安装自定义节点的依赖包。
        
        Args:
            nodes_map: 控制插件依赖的安装行为。
                - None: 尝试安装所有在 `custom_nodes` 目录中找到的可用插件。
                - 字典: 具体的安装内容由字典决定：
                    - 非空字典 (例: {'NodeA': 'v1'}): 只安装字典中指定的有效插件。
                    - 空字典 ({}): 启动安装流程，但不安装任何插件。
            timeout: 安装超时时间（秒），默认使用 constants.DEFAULT_INSTALL_TIMEOUT（10分钟）。
            custom_nodes_dirs: 存放插件的父目录列表。None = 使用默认的 custom_nodes 目录。
        
        Returns:
            Dict: install_all 的返回结果，包含 baseline、dependencies 和 scripts
        """
        from services.pip.pip_installer import PIPInstaller
        installer = PIPInstaller()
        return installer.install_all(timeout=timeout, nodes_map=nodes_map, custom_nodes_dirs=custom_nodes_dirs)

    def start(self, snapshot_name: str, nodes_map: Optional[Dict] = constants.SKIP_INSTALL_SENTINEL) -> Dict:
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
        self.sub_status = StartingSubStatus.DOWNLOADING.value

        try:
            result_map = {}

            # 加载快照逻辑
            if str(constants.SKIP_SNAPSHOT_LOADING).lower() == 'true':
                pass
                # self._snapshot_mgr.prepare_link()
            else:
                result_map = self._snapshot_mgr.load(snapshot_name)
            
            # 准备共享模型目录（只对 ComfyUI 生效，必须在快照加载后执行）
            if constants.BACKEND_TYPE == constants.TYPE_COMFYUI:
                from services.custom_nodes.builtin_custom_nodes import setup_builtin_custom_nodes
                from services.model.shared_models import setup_shared_models
                setup_builtin_custom_nodes()
                setup_shared_models()

            # 线上服务(API模式)无条件跳过插件安装，只有项目开发时才需要
            if constants.USE_API_MODE:
                nodes_map = constants.SKIP_INSTALL_SENTINEL

            # clone + install 插件依赖
            if nodes_map is not constants.SKIP_INSTALL_SENTINEL:
                self.sub_status = StartingSubStatus.INSTALLING.value
                with timer("Install custom_nodes packages") as t_install_process:
                    custom_nodes_dirs = [os.path.join(constants.COMFYUI_DIR, "custom_nodes"), constants.BUILTIN_DELTA_NODES_DIR]
                    if isinstance(nodes_map, dict) and nodes_map:
                        clone_result = self.clone_custom_nodes(nodes_map, custom_nodes_dirs=custom_nodes_dirs, timeout=300)
                        result_map["clone_result"] = clone_result
                    install_result = self.install_custom_nodes(nodes_map, custom_nodes_dirs=custom_nodes_dirs) # 默认15min超时时间
                    result_map.update(install_result)
                result_map["time_install_process"] = round(t_install_process.elapsed, 2)

            # ComfyUI v0.16.4+ sqlite 数据库目录（相对于 comfyui 源码根目录）
            os.makedirs(f"{constants.COMFYUI_DIR}/user", exist_ok=True)

            # 启动ComfyUI服务子进程
            self.sub_status = StartingSubStatus.BOOTING.value
            with timer("Start process") as t_start_process:
                self._process_mgr.start(constants.BOOT_CMD)
                self._process_mgr.wait_until_ready()
            result_map["time_start_process"] = round(t_start_process.elapsed, 2)

            self.sub_status = ""
            return result_map
        except Exception:
            self.sub_status = ""
            raise

    def save(self, snapshot_type: str) -> Dict:
        """
        保存工作空间快照。
        
        状态转换：
        - RUNNING → SAVING → RUNNING（成功或失败都返回）
        
        注意：只能在 RUNNING 状态下调用此方法
        """
        print(f"Saving workspace (type {snapshot_type})...")
        self._transition_to(BackendStatus.SAVING)
        self.sub_status = SavingSubStatus.PACKAGING.value

        try:
            result_map = self._snapshot_mgr.save(snapshot_type)
            # 保存成功，转回 RUNNING
            self._transition_to(BackendStatus.RUNNING)
            self.sub_status = ""
            return result_map
        except Exception:
            # 保存失败，也转回 RUNNING
            try:
                self._transition_to(BackendStatus.RUNNING)
            except Exception:
                pass  # 如果状态转换失败，保持当前状态
            self.sub_status = ""
            raise

    def stop(self) -> Dict:
        """
        停止ComfyUI服务进程（原子操作，不涉及状态转换）。
        """
        print("Stopping workspace...")

        result_map = {}
        
        with timer("Stop process") as t_stop_process:
            self._process_mgr.stop()
        result_map["time_stop_process"] = round(t_stop_process.elapsed, 2)
        
        # 设置停止标志，PreStop 钩子会检查此标志来决定是否执行兜底保存
        self._is_stopped = True
        
        return result_map

    def save_and_stop(self, snapshot_type: str) -> Dict:
        print(f"Saving and Stopping workspace (type {snapshot_type})...")
        result_map = self.save(snapshot_type)
        stop_result_map = self.stop()
        result_map.update(stop_result_map)
        return result_map

