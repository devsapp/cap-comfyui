from enum import Enum
import os
import socket

TYPE_COMFYUI = 'comfyui'
TYPE_SD = 'sd'
BACKEND_TYPE = os.getenv('BACKEND_TYPE', TYPE_COMFYUI)

# ComfyUI 模式配置：'cpu' 或 'gpu'
COMFYUI_MODE = os.getenv('COMFYUI_MODE', 'gpu').lower()

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

# 共享存储中的输入目录（NAS 中的 input 目录），issue: https://aliyuque.antfin.com/lnpq52/cc8sut/slcnbzw0t7q9snbb
MNT_INPUT_DIR = os.getenv('MNT_INPUT_DIR', f"{MNT_DIR}/input")

# 根据 COMFYUI_MODE 配置输入目录和启动命令
if COMFYUI_MODE == 'cpu':
    # CPU模式：输入目录默认使用 MNT_INPUT_DIR
    INPUT_DIR = os.getenv('INPUT_DIR', MNT_INPUT_DIR)
    COMFYUI_BOOT_CMD = [
        f"{VENV_DIR}/bin/python",
        f"{COMFYUI_DIR}/main.py",
        "--cpu",
        "--listen",
        "0.0.0.0",
        "--input-directory",
        INPUT_DIR,
        "--output-directory",
        f"{MNT_DIR}/output",
        "--temp-directory",
        f"{MNT_DIR}/output",
        "--user-directory",
        f"{MNT_DIR}/output",
        "--disable-metadata"
    ]
else:
    # GPU模式：线上服务输入目录默认使用 COMFYUI_DIR/input(实例磁盘)，项目开发默认使用 MNT_INPUT_DIR
    if USE_API_MODE:
        INPUT_DIR = os.getenv('INPUT_DIR', f"{COMFYUI_DIR}/input")
    else:
        INPUT_DIR = os.getenv('INPUT_DIR', MNT_INPUT_DIR)
    COMFYUI_BOOT_CMD = [
        f"{VENV_DIR}/bin/python",
        f"{COMFYUI_DIR}/main.py",
        "--listen",
        "0.0.0.0",
        "--input-directory",
        INPUT_DIR,
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

# PreStop 相关配置
PRESTOP_TIMEOUT = int(os.getenv("PRESTOP_TIMEOUT", "580"))  # preStop 超时时间，默认 580 秒（留 20 秒缓冲）

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

# GPU 函数的 URL，当 COMFYUI_MODE="cpu" 时使用
GPU_FUNCTION_URL = os.getenv("GPU_FUNCTION_URL", "")

# HTTP Header 常量
HEADER_SNAPSHOT_NAME = "X-FunArt-Snapshot"
HEADER_FC_INVOCATION_TYPE = "X-FC-Invocation-Type"

# 是否禁用工作流保存,默认允许保存
DISABLE_FLOW_SAVE = os.getenv('DISABLE_WORKFLOW_SAVE', '').lower() == 'true'

# 日志配置
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

class ERROR_CODE(Enum):
    UNCLASSIFY = "UNCLASSIFY"
    INVALID_PARAMS = "INVALID_PARAMS"
    PROMPT_ERROR = "PROMPT_ERROR"
    EXECUTION_FAILED = "EXECUTION_FAILED"
