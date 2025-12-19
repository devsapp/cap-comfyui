#!/bin/bash

# 文件目录总览
# - /root: 工作目录
# -- agent: agent程序所在目录
# -- comfyui
# --- models: comfyui模型目录，软链接到挂载存储中，/root/comfyui/models -> ${MNT_DIR}/models
# --- ...
# -- venv: 依赖目录

# - ${MNT_DIR}: 挂载目录，NAS or OSS
# -- models: 用户模型本体，/root/comfyui/models -> ${MNT_DIR}/models
# -- input: 输入内容，例如图片
# -- output: 输出内容，例如图片
# -- snapshots: 快照目录
# --- 20250101-015959
# ---- comfyui
# ---- venv.tar
# --- 20250102-120159
# ---- comfyui
# ---- venv.tar

# 检查是否为国内区域
is_domestic_region() {
  local domestic_regions=("cn-hangzhou" "cn-shanghai" "cn-shenzhen" "cn-beijing")
  local region="${REGION:-}"
  
  for reg in "${domestic_regions[@]}"; do
    if [[ "${region}" == "${reg}" ]]; then
      return 0
    fi
  done
  return 1
}

# 设置网络配置
setup_network() {
  echo "[INFO] Setting up network configuration..."
  
  # 如果是国内集群，配置加速
  if is_domestic_region; then
    echo "[INFO] Domestic region detected: ${REGION}"
    
    # 设置 HuggingFace 镜像
    export HF_ENDPOINT="https://hf-mirror.com"

    # ComfyUI-Manager 使用
    # 设置 Github 镜像
    export GITHUB_ENDPOINT="https://cap-accor-proxy-qkqnjxeail.ap-southeast-1.fcapp.run/https://github.com/"
    
    # uv 镜像配置
    export UV_DEFAULT_INDEX="https://mirrors.aliyun.com/pypi/simple/"

    # 使用 copy 模式，避免 hardlink 警告（当缓存和目标在不同文件系统时）
    export UV_LINK_MODE="copy"
    
    # 增加超时时间（默认30秒太短）
    export UV_HTTP_TIMEOUT="300"

    # 启动 GitHub 代理监控守护进程
    GITHUB_PROXY_MONITOR="${AGENT_DIR}/services/proxy/github-proxy-monitor.sh"
    if [ -f "$GITHUB_PROXY_MONITOR" ]; then
      echo "[INFO] Starting GitHub proxy monitor..."
      nohup bash "$GITHUB_PROXY_MONITOR" > /tmp/github_proxy_monitor.log 2>&1 &
      echo "[INFO] GitHub proxy monitor started (logs: /tmp/github_proxy_monitor.log)"
    else
      echo "[WARN] GitHub proxy monitor not found at: $GITHUB_PROXY_MONITOR"
    fi
  else
    echo "[INFO] Non-domestic region, skipping network acceleration"
  fi
}


MNT_DIR=${MODEL_ASSET_DIR:="/mnt/auto"}
SKIP_SNAPSHOT_LOADING_LOWER=$(echo "${SKIP_SNAPSHOT_LOADING:-false}" | tr '[:upper:]' '[:lower:]')
echo "[INFO] Configuration:"
echo "  - Mount Directory: ${MNT_DIR}"
echo "  - Skip Snapshot Loading: ${SKIP_SNAPSHOT_LOADING_LOWER}"

if [ "${SKIP_SNAPSHOT_LOADING_LOWER}" != "true" ]; then
    if [ ! -e "${MNT_DIR}/snapshots" ] || [ -z "$(find "${MNT_DIR}/snapshots" -type d -mindepth 1 -maxdepth 1 2>/dev/null)" ]; then
        echo "[ERROR] Missing snapshots folder in your mount dir"
        exit 1
    fi
fi

mkdir -p ${MNT_DIR}/input
mkdir -p ${MNT_DIR}/output
mkdir -p ${MNT_DIR}/output/serverless_api
source ${AGENT_DIR}/venv/bin/activate
echo "Using python venv, python path '$(which python)', pip path '$(which pip)'... "

# ==================== 网络配置 ====================
setup_network

# ==================== 执行 prestart 脚本 ====================
# 执行 shell 脚本（如果有）
PRESTART_DIR="${AGENT_DIR}/sh"
if [ -d "$PRESTART_DIR" ]; then
  echo "[INFO] Running prestart scripts from: $PRESTART_DIR"
  for script in $(find "$PRESTART_DIR" -maxdepth 1 -name "*.sh" -type f | sort); do
    if [ -x "$script" ]; then
      echo "[INFO] Executing prestart script: $(basename "$script")"
      if bash "$script"; then
        echo "[INFO] Prestart script completed: $(basename "$script")"
      else
        echo "[ERROR] Prestart script failed: $(basename "$script")"
        exit 1
      fi
    else
      echo "[WARN] Prestart script is not executable, skipping: $(basename "$script")"
    fi
  done
else
  echo "[INFO] Prestart scripts directory not found: $PRESTART_DIR"
fi

python ${AGENT_DIR}/main.py