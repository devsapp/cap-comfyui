import sys
import time
from enum import Enum
from threading import Lock
from typing import Dict, Set

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

    def start(self, snapshot_name: str) -> Dict:
        print(f"Starting backend process using snapshot '{snapshot_name}'...")
        self._transition_to(BackendStatus.STARTING, Action.START)

        try:
            result_map = self._snapshot_mgr.load(snapshot_name)
            with timer("Start process") as t_start_process:
                self._process_mgr.start(constants.BOOT_CMD)
                self._process_mgr.wait_until_ready()
            result_map["time_start_process"] = round(t_start_process.elapsed, 2)
            self._transition_to(BackendStatus.RUNNING, Action.START)
            return result_map
        except Exception:
            self._transition_to(BackendStatus.STOPPED, Action.START)
            raise

    def save(self) -> Dict:
        print("Saving workspace...")
        self._transition_to(BackendStatus.SAVING, Action.SAVE)

        try:
            result_map = self._snapshot_mgr.save()
            self._transition_to(BackendStatus.RUNNING, Action.SAVE)
            return result_map
        except Exception:
            self._transition_to(BackendStatus.RUNNING, Action.SAVE)
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

    def save_and_stop(self) -> Dict:
        print("Saving and Stopping workspace...")
        result_map = self.save()
        stop_result_map = self.stop()
        result_map.update(stop_result_map)
        return result_map

    def find_snapshots(self):
        return self._snapshot_mgr.find_valid_snapshots()

    def shutdown(self):
        print("Executing shutdown after 1s...")
        time.sleep(1)
        sys.exit(0)
