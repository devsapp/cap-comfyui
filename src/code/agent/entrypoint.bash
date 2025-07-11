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

mkdir -p ${MNT_DIR}/input
mkdir -p ${MNT_DIR}/output
source ${AGENT_DIR}/venv/bin/activate
echo "Using python venv, python path '$(which python)', pip path '$(which pip)'... "

check_and_init_mitmproxy

# git diff 忽略文件权限变化，ComfyUI 中 Windows 可执行文件在 Linux 中自动没有可执行权限，导致有 git diff，影响 ComfyUI 版本升级
git config --global core.fileMode false

python ${AGENT_DIR}/main.py