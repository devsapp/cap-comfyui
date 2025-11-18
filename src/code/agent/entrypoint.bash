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

# - /mnt/shared/models: 共享模型目录（只读）
# -- checkpoints/, loras/, vae/, ... (由平台或管理员维护)
init_mitmproxy(){
  echo 'export NO_PROXY="127.0.0.1,mirrors.aliyun.com,ghfast.top,ghgo.xyz,ghp.ci,ghproxy.com,hf-mirror.com,deb.debian.org,www.modelscope.cn"'>> ~/.bashrc
  echo 'export no_proxy="127.0.0.1,mirrors.aliyun.com,ghfast.top,ghgo.xyz,ghp.ci,ghproxy.com,hf-mirror.com,deb.debian.org,www.modelscope.cn"'>> ~/.bashrc

  echo 'export HTTP_PROXY="http://127.0.0.1:8080"' >> ~/.bashrc
  echo 'export http_proxy="http://127.0.0.1:8080"' >> ~/.bashrc

  echo 'export HTTPS_PROXY="http://127.0.0.1:8080"' >> ~/.bashrc
  echo 'export https_proxy="http://127.0.0.1:8080"' >> ~/.bashrc

  echo 'export HF_ENDPOINT="https://hf-mirror.com"' >> ~/.bashrc

  echo 'export REQUESTS_CA_BUNDLE="/etc/ssl/certs/ca-certificates.crt"'>> ~/.bashrc
  echo 'export SSL_CERT_FILE="/etc/ssl/certs/ca-certificates.crt"'>> ~/.bashrc
  echo 'export CURL_CA_BUNDLE="/etc/ssl/certs/ca-certificates.crt"'>> ~/.bashrc

  source ~/.bashrc

#  mitmdump -s ${AGENT_DIR}/services/proxy/mirror_proxy.py &
  mitmdump -s ${AGENT_DIR}/services/proxy/mirror_proxy.py >> /root/agent/mitmproxy.log 2>> /root/agent/mitmproxy_error.log &

  sleep 5
#  cp ~/.mitmproxy/mitmproxy-ca-cert.cer /usr/local/share/ca-certificates/
  cp ~/.mitmproxy/mitmproxy-ca-cert.pem /usr/local/share/ca-certificates/mitmproxy.crt
  update-ca-certificates
  git config --global http.sslCAInfo /usr/local/share/ca-certificates/mitmproxy.crt
}

check_and_init_mitmproxy(){
  echo "Check and init mitmproxy..."

  # 根据AUTO_LAUNCH_SNAPSHOT_NAME是否为空来判断当前函数是否use_api_mode
  use_api_mode=false
  if [[ -n "${AUTO_LAUNCH_SNAPSHOT_NAME}" ]]; then
      use_api_mode=true
  fi

  # 根据当前REGION判断是否处于国内
  domestic_regions=("cn-hangzhou" "cn-shanghai" "cn-shenzhen" "cn-beijing")
  region="${REGION}"
  is_domestic=false
  for reg in "${domestic_regions[@]}"; do
      if [[ "${region}" == "${reg}" ]]; then
          is_domestic=true
          break
      fi
  done

  if [[ ${use_api_mode} == false ]] && [[ ${is_domestic} == true ]]; then
      echo "Init mitmproxy..."
      init_mitmproxy
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

check_and_init_mitmproxy

# git diff 忽略文件权限变化，ComfyUI 中 Windows 可执行文件在 Linux 中自动没有可执行权限，导致有 git diff，影响 ComfyUI 版本升级
git config --global core.fileMode false

python ${AGENT_DIR}/main.py