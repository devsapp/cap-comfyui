#!/bin/bash

# 文件目录总览
# - /root: 工作目录
# -- agent: agent程序所在目录
# -- comfyui
# --- models -> ${MNT_DIR}/models (软链接到用户模型目录)
# --- ...
# -- venv: 依赖目录

# - ${MNT_DIR}: 挂载目录，NAS or OSS
# -- models: 用户模型目录
# --- checkpoints/
# ---- shared/ -> /mnt/shared/models/checkpoints/ (共享模型软链接)
# ---- model1.safetensors (用户自己的模型)
# --- loras/, vae/, embeddings/ ... (同上结构)
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
    if [ ! -e "${MNT_DIR}/snapshots" ] || [ -z "$(find "${MNT_DIR}/snapshots" -type d -mindepth 1 2>/dev/null)" ]; then
        echo "[ERROR] Missing snapshots folder in your mount dir"
        exit 1
    fi
fi

# 配置 shared models - 使用软链接方案
setup_shared_models() {
    local shared_models_dir="/mnt/shared/models"
    local user_models_dir="${MNT_DIR}/models"
    
    echo "[INFO] Setting up shared models ..."
    
    # 确保用户模型目录存在，如果已存在，则跳过；如果不存在，创建目录
    mkdir -p "${user_models_dir}"
    
    # 如果共享模型目录不存在，跳过
    if [ ! -d "${shared_models_dir}" ]; then
        echo "[WARN] Shared models directory ${shared_models_dir} does not exist, skipping"
        return
    fi
    
    # 遍历共享模型目录中的所有子目录
    for shared_subdir in "${shared_models_dir}"/*/ ; do
        # 跳过不存在的情况（如果目录为空）
        [ -e "${shared_subdir}" ] || continue
        
        # 获取目录名称（去掉路径和尾部斜杠）
        local dir_name=$(basename "${shared_subdir}")
        
        # 用户模型中对应的子目录
        local user_subdir="${user_models_dir}/${dir_name}"
        
        # 如果用户模型中没有这个目录，创建它
        if [ ! -d "${user_subdir}" ]; then
            mkdir -p "${user_subdir}"
            echo "[INFO] Created user model directory: ${dir_name}/"
        fi
        
        # 在用户模型子目录中创建 shared/ 软链接
        local shared_link="${user_subdir}/shared"
        
        # 如果链接已存在，先删除
        if [ -e "${shared_link}" ] || [ -L "${shared_link}" ]; then
            rm -f "${shared_link}"
        fi
        
        # 创建软链接
        ln -sf "${shared_subdir}" "${shared_link}"
        echo "[INFO] Created shared link: ${dir_name}/shared/ -> ${shared_subdir}"
    done
    
    echo "[INFO] Shared models setup completed"
}

setup_shared_models

mkdir -p ${MNT_DIR}/input
mkdir -p ${MNT_DIR}/output
source ${AGENT_DIR}/venv/bin/activate
echo "Using python venv, python path '$(which python)', pip path '$(which pip)'... "

# ==================== 网络配置 ====================
setup_network

# git diff 忽略文件权限变化，ComfyUI 中 Windows 可执行文件在 Linux 中自动没有可执行权限，导致有 git diff，影响 ComfyUI 版本升级
git config --global core.fileMode false

python ${AGENT_DIR}/main.py