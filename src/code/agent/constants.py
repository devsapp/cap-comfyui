import os

WORK_DIR = os.getenv('WORK_DIR', '/root')
MNT_DIR = os.getenv('MNT_DIR', '/mnt/auto')
COMFYUI_DIR = os.getenv('COMFYUI_DIR', WORK_DIR + '/comfyui')
VENV_DIR = os.getenv('VENV_DIR', WORK_DIR + '/venv')
SNAPSHOT_DIR = MNT_DIR + '/snapshots'
SNAPSHOT_PATTERN = '%Y%m%d-%H%M%S'

COMFYUI_PROCESS_PORT = 8188
COMFYUI_HOST = f"http://127.0.0.1:{COMFYUI_PROCESS_PORT}"
DEFAULT_READINESS_POLL_INTERVAL = 3
DEFAULT_READINESS_TIMEOUT = 120
BOOT_CMD = [f"{VENV_DIR}/bin/python", f"{COMFYUI_DIR}/main.py", "--listen", "0.0.0.0"]
# CLI_ARGS="--listen 0.0.0.0 --input-directory ${MNT_DIR}/input --output-directory ${MNT_DIR}/output --temp-directory ${MNT_DIR}/output}"
