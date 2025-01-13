import constants
from services.comfyui_process_manager import ComfyuiProcessManager
from services.snapshot_manager import SnapshotManager


def start():
    print(f"Starting comfyui process...")

    SnapshotManager.load()

    process_manager = ComfyuiProcessManager()
    process_manager.start(constants.BOOT_CMD)
    process_manager.wait_until_ready()


def save():
    print(f"Saving comfyui workspace...")

    SnapshotManager.save()
