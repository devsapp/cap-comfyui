from threading import Lock
from enum import Enum
from typing import Dict, Set

import constants
from services.comfyui_process_manager import ComfyuiProcessManager
from services.snapshot_manager import SnapshotManager


class ComfyuiStatus(Enum):
    STOPPED = "Stopped"
    STARTING = "Starting"
    RUNNING = "Running"
    SAVING = "Saving"
    STOPPING = "Stopping"


class ComfyuiService:
    _VALID_TRANSITIONS: Dict[ComfyuiStatus, Set[ComfyuiStatus]] = {
        ComfyuiStatus.STOPPED: {ComfyuiStatus.STARTING},
        ComfyuiStatus.STARTING: {ComfyuiStatus.RUNNING, ComfyuiStatus.STOPPED},
        ComfyuiStatus.RUNNING: {ComfyuiStatus.SAVING, ComfyuiStatus.STOPPING},
        ComfyuiStatus.SAVING: {ComfyuiStatus.RUNNING},
        ComfyuiStatus.STOPPING: {ComfyuiStatus.STOPPED, ComfyuiStatus.RUNNING}
    }

    def __init__(self):
        self._process_mgr = ComfyuiProcessManager()
        self._snapshot_mgr = SnapshotManager()
        self._status = ComfyuiStatus.STOPPED
        self._status_lock = Lock()

    def _transition_to(self, new_status: ComfyuiStatus) -> None:
        with self._status_lock:
            if new_status not in self._VALID_TRANSITIONS[self._status]:
                raise RuntimeError(
                    f"Illegal state transition: {self._status} -> {new_status}"
                )
            self._status = new_status

    @property
    def status(self) -> ComfyuiStatus:
        with self._status_lock:
            return self._status

    def start(self, snapshot_name: str):
        print("Starting comfyui process...")
        self._transition_to(ComfyuiStatus.STARTING)

        try:
            self._snapshot_mgr.load(snapshot_name)
            self._process_mgr.start(constants.BOOT_CMD)
            self._process_mgr.wait_until_ready()
            self._transition_to(ComfyuiStatus.RUNNING)
        except Exception:
            self._transition_to(ComfyuiStatus.STOPPED)
            raise

    def save(self):
        print("Saving comfyui workspace...")
        self._transition_to(ComfyuiStatus.SAVING)

        try:
            self._snapshot_mgr.save()
            self._transition_to(ComfyuiStatus.RUNNING)
        except Exception:
            self._transition_to(ComfyuiStatus.RUNNING)
            raise

    def stop(self):
        print("Stopping comfyui workspace...")
        self._transition_to(ComfyuiStatus.STOPPING)

        try:
            self._process_mgr.stop()
            self._transition_to(ComfyuiStatus.STOPPED)
        except Exception:
            self._transition_to(ComfyuiStatus.RUNNING)
            raise

    def save_and_stop(self):
        print("Saving and Stopping comfyui workspace...")
        self.save()
        self.stop()

    def find_snapshots(self):
        return self._snapshot_mgr.find_valid_snapshots()
