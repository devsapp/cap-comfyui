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
    echo "[INFO] Set HF_ENDPOINT=${HF_ENDPOINT}"
    
    # 启动 GitHub 代理守护进程
    if [ -f "/usr/local/bin/github-proxy-daemon" ]; then
      echo "[INFO] Starting GitHub proxy daemon..."
      nohup /usr/local/bin/github-proxy-daemon > /tmp/github_proxy_daemon.log 2>&1 &
      echo "[INFO] GitHub proxy daemon started (logs: /tmp/github_proxy_daemon.log)"
    else
      echo "[WARN] GitHub proxy daemon not found, skipping..."
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
    if [ ! -e "${MNT_DIR}/snapshots" ] || [ -z "$(find "${MNT_DIR}/snapshots" -type d -mindepth 1 2>/dev/null)" ]; then
        echo "[ERROR] Missing snapshots folder in your mount dir"
        exit 1
    fi
fi

# 创建 fuse 设备节点
mknod /dev/fuse c 10 229

# 配置 shared models
# unionfs-fuse -o cow,allow_other \
#   ${MNT_DIR}/models=RW:/mnt/shared/models=RO \
#   /root/comfyui/models
# echo "Using shared models ..."

mkdir -p ${MNT_DIR}/input
mkdir -p ${MNT_DIR}/output
source ${AGENT_DIR}/venv/bin/activate
echo "Using python venv, python path '$(which python)', pip path '$(which pip)'... "

# 设置网络配置（国内区域加速）
# 针对 git 使用 git proxy
# 针对 huggingface 使用 hf mirror
setup_network

# git diff 忽略文件权限变化，ComfyUI 中 Windows 可执行文件在 Linux 中自动没有可执行权限，导致有 git diff，影响 ComfyUI 版本升级
git config --global core.fileMode false

python ${AGENT_DIR}/main.py