from enum import Enum
from threading import Lock
from typing import Dict, Set, Optional

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
        self._process_mgr = BackendProcessManager()
        self._snapshot_mgr = SnapshotManager()
        self._status = BackendStatus.STOPPED
        self._sub_status = ""
        self._latest_action = None
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

    def start(self, snapshot_name: str) -> Dict:
        print(f"Starting backend process using snapshot '{snapshot_name}'...")
        self._transition_to(BackendStatus.STARTING, Action.START)
        self.sub_status = StartingSubStatus.DOWNLOADING

        try:
            result_map = self._snapshot_mgr.load(snapshot_name)
            self.sub_status = StartingSubStatus.BOOTING
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
        self.sub_status = SavingSubStatus.PACKAGING

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
