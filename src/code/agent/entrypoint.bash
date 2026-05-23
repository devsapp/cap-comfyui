#!/bin/bash

# 文件目录总览
# - /root: 工作目录
# -- agent: agent程序所在目录
# -- comfyui
# --- models: comfyui模型目录，包含平台共享模型和用户模型的软链接
# ----  平台共享模型来自 /mnt/shared/models (优先级低)
# ----  用户模型来自 ${MNT_DIR}/models (优先级高，重名时覆盖平台模型)
# --- ...
# -- venv: 依赖目录

# - ${MNT_DIR}: 挂载目录，NAS or OSS
# -- models: 用户模型本体
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
    
    # 写入 ~/.bashrc（同时满足运行时和登录实例时使用）
    echo 'export HF_ENDPOINT="https://hf-mirror.com"' >> ~/.bashrc
    echo 'export GITHUB_ENDPOINT="https://cap-accor-proxy-qkqnjxeail.ap-southeast-1.fcapp.run/https://github.com/"' >> ~/.bashrc
    echo 'export UV_DEFAULT_INDEX="https://mirrors.aliyun.com/pypi/simple/"' >> ~/.bashrc
    echo 'export UV_LINK_MODE="copy"' >> ~/.bashrc
    echo 'export UV_HTTP_TIMEOUT="300"' >> ~/.bashrc
    
    # 加载环境变量（用于当前 entrypoint.bash 及其子进程）
    source ~/.bashrc

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

# 设置 ComfyUI Manager 配置（仅国内区域 && 非 API 模式）
setup_comfyui_manager_config() {
  # 仅在国内环境 && 非 API_MODE 才执行
  if ! is_domestic_region; then
    echo "[INFO] Non-domestic region, skipping ComfyUI Manager config setup"
    return 0
  fi
  
  if [ -n "${AUTO_LAUNCH_SNAPSHOT_NAME:-}" ]; then
    echo "[INFO] API Mode detected, skipping ComfyUI Manager config setup"
    return 0
  fi
  
  echo "[INFO] Setting up ComfyUI Manager configuration..."
  
  local target_dir=""

  # manager_dir - 新版本 ComfyUI Manager 配置目录（output/__manager）
  local manager_dir="${MNT_DIR}/output/__manager"
  
  # legacy_manager_dir - 旧版本 ComfyUI Manager 配置目录
  local legacy_manager_dir="${MNT_DIR}/output/default/ComfyUI-Manager"
  
  # 优先检查 manager_dir（新版本）
  if [ -f "${manager_dir}/channels.list" ] || [ -f "${manager_dir}/config.ini" ]; then
    echo "[INFO] Found ComfyUI Manager config in ${manager_dir}"
    target_dir="${manager_dir}"
  # 其次检查 legacy_manager_dir（旧版本）
  elif [ -f "${legacy_manager_dir}/channels.list" ] || [ -f "${legacy_manager_dir}/config.ini" ]; then
    echo "[INFO] Found ComfyUI Manager config in ${legacy_manager_dir}"
    target_dir="${legacy_manager_dir}"
  else
    # 两个目录都没有配置文件，默认使用 manager_dir
    echo "[INFO] No existing ComfyUI Manager config found, using default location ${manager_dir}"
    target_dir="${manager_dir}"
  fi
  
  local channels_file="${target_dir}/channels.list"
  local config_file="${target_dir}/config.ini"
  local channels_backup="${channels_file}.backup"
  local config_backup="${config_file}.backup"
  
  # 如果备份文件已存在，说明已经设置过了，直接返回
  if [ -f "${channels_backup}" ] || [ -f "${config_backup}" ]; then
    echo "[INFO] Backup files already exist, skipping ComfyUI Manager config setup"
    return 0
  fi
  
  # 确保目标目录存在
  mkdir -p "${target_dir}"
  
  # 备份 channels.list（如果备份不存在且原文件存在）
  if [ -f "${channels_file}" ] && [ ! -f "${channels_backup}" ]; then
    echo "[INFO] Backing up original channels.list to ${channels_backup}"
    cp "${channels_file}" "${channels_backup}"
  fi
  
  # 备份 config.ini（如果备份不存在且原文件存在）
  if [ -f "${config_file}" ] && [ ! -f "${config_backup}" ]; then
    echo "[INFO] Backing up original config.ini to ${config_backup}"
    cp "${config_file}" "${config_backup}"
  fi
  
  # 拷贝我们的配置文件
  echo "[INFO] Copying custom ComfyUI Manager configuration to ${target_dir}"
  cp "${AGENT_DIR}/services/proxy/comfyui_manager_config/channels.list" "${channels_file}"
  cp "${AGENT_DIR}/services/proxy/comfyui_manager_config/config.ini" "${config_file}"

  echo "[INFO] ComfyUI Manager configuration completed"
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

# ==================== ComfyUI Manager 配置 ====================
setup_comfyui_manager_config

# 使用 exec 让 Python 替换 bash 成为 init 进程，方便健康检查失败时直接退出触发实例轮转
exec python ${AGENT_DIR}/main.py
