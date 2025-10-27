from enum import Enum
import os
import socket

TYPE_COMFYUI = 'comfyui'
TYPE_SD = 'sd'
BACKEND_TYPE = os.getenv('BACKEND_TYPE', TYPE_COMFYUI)

# API Mode
USE_API_MODE = bool(os.getenv("AUTO_LAUNCH_SNAPSHOT_NAME"))
AUTO_LAUNCH_SNAPSHOT_NAME = os.getenv("AUTO_LAUNCH_SNAPSHOT_NAME", "latest")

WORK_DIR = os.getenv('WORK_DIR', '/root')
MNT_DIR = os.getenv('MODEL_ASSET_DIR', '/mnt/auto')
VENV_DIR = os.getenv('VENV_DIR', WORK_DIR + '/venv')
VENV_EXECUTABLE = VENV_DIR + '/bin/python'
MODEL_DIR = os.getenv('MODEL_DIR', MNT_DIR + '/models')
SKIP_SNAPSHOT_LOADING = os.getenv('SKIP_SNAPSHOT_LOADING')
# API函数启动时是否跳过加载NAS中的custom_nodes.zip到实例磁盘，若跳过则可能遇到部分插件在多个实例并发读写NAS中插件目录时的冲突情况
SKIP_NODES_LOADING = os.getenv('SKIP_NODES_LOADING', '').lower() == 'true'
SNAPSHOT_DIR = MNT_DIR + '/snapshots'
SNAPSHOT_PATTERN = '%Y%m%d-%H%M%S'
COMFYUI_DIR = os.getenv('COMFYUI_DIR', WORK_DIR + '/comfyui')
COMFYUI_PROCESS_PORT = 8188
COMFYUI_BOOT_CMD = [
    f"{VENV_DIR}/bin/python",
    f"{COMFYUI_DIR}/main.py",
    "--listen",
    "0.0.0.0",
    "--input-directory",
    f"{MNT_DIR}/input",
    "--output-directory",
    f"{MNT_DIR}/output",
    "--temp-directory",
    f"{MNT_DIR}/output",
    "--user-directory",
    f"{MNT_DIR}/output",
    "--disable-metadata"
]
SD_DIR = os.getenv('SD_DIR', WORK_DIR + '/stable-diffusion-webui')
SD_PROCESS_PORT = 7860
SD_BOOT_CMD = [
    f"{VENV_DIR}/bin/python",
    f"{SD_DIR}/webui.py",
    "--listen",
    "--xformers",
    "--enable-insecure-extension-access",
    "--skip-version-check",
    "--no-download-sd-model",
    "--gradio-allowed-path=/"
]
if USE_API_MODE:
    SD_BOOT_CMD.extend(["--nowebui", "--api"])
    SD_PROCESS_PORT = 7861

if BACKEND_TYPE == TYPE_COMFYUI:
    BACKEND_PROCESS_PORT = COMFYUI_PROCESS_PORT
    BOOT_CMD = COMFYUI_BOOT_CMD
else:
    BACKEND_PROCESS_PORT = SD_PROCESS_PORT
    BOOT_CMD = SD_BOOT_CMD
APP_HOST = f"127.0.0.1:{BACKEND_PROCESS_PORT}"

DEFAULT_READINESS_POLL_INTERVAL = 3
DEFAULT_READINESS_TIMEOUT = 900  # 15min waiting for comfyui subprocess start
DEFAULT_LIVENESS_POLL_INTERVAL = 5

# 插件安装相关超时配置
DEFAULT_INSTALL_TIMEOUT = 600  # 10min default timeout for custom nodes installation

INSTANCE_ID = os.getenv("FC_INSTANCE_ID", socket.gethostname())
# OSS
HEADER_KEY_ACCESS_KEY_ID = "x-fc-access-key-id"
HEADER_KEY_ACCESS_KEY_SECRET = "x-fc-access-key-secret"
HEADER_KEY_SECURITY_TOKEN = "x-fc-security-token"
ALIBABA_CLOUD_ACCESS_KEY_ID = os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "")
ALIBABA_CLOUD_ACCESS_KEY_SECRET = os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "")
ALIBABA_CLOUD_SECURITY_TOKEN = os.getenv("ALIBABA_CLOUD_SECURITY_TOKEN", "")
OSS_BUCKET_DOMAIN = os.getenv("OSS_BUCKET_DOMAIN", "")
OSS_KEY_PREFIX = os.getenv("OSS_KEY_PREFIX", "comfyui_serverless_api")
OSS_OUTPUT_DOMAIN = os.getenv("OSS_OUTPUT_DOMAIN", "")
OSS_EXPIRES_IN_SECOND = os.getenv("OSS_EXPIRES_IN_SECOND", "")

PREWARM_PROMPT = os.getenv("PREWARM_PROMPT", "")

# 日志配置
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

class ERROR_CODE(Enum):
    UNCLASSIFY = "UNCLASSIFY"
    INVALID_PARAMS = "INVALID_PARAMS"
    PROMPT_ERROR = "PROMPT_ERROR"
    EXECUTION_FAILED = "EXECUTION_FAILED"
