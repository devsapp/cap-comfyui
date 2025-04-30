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
  echo 'export HTTP_PROXY="http://127.0.0.1:8080"' >> ~/.bashrc
  echo 'export HTTPS_PROXY="http://127.0.0.1:8080"' >> ~/.bashrc
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

  # 若 AUTO_LAUNCH_SNAPSHOT_NAME 非空，则当前是 api_mode
  use_api_mode=false
  if [[ -n "${AUTO_LAUNCH_SNAPSHOT_NAME}" ]]; then
      use_api_mode=true
  fi

  # 根据 REGION 判断是否处于国内
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
echo "Mount dir: ${MNT_DIR}"
if [ ! -e "${MNT_DIR}/models" ] || [ ! -e "${MNT_DIR}/snapshots" ] || [ -z "$(find "${MNT_DIR}/snapshots" -type d -mindepth 1 2>/dev/null)" ]; then
  echo "Missing models and snapshots folders in your mount dir"
  # exit 1
  # FIXME: 以下逻辑服务于带comfyui/sd环境的完整镜像；当支持启动阶段从官方源拉取comfyui源码和模型后，将以下逻辑可换为exit 1
  if [ "${BACKEND_TYPE}" = "comfyui" ]; then
    cp -r ${COMFYUI_DIR}/models ${MNT_DIR}/models
    rm -rf ${COMFYUI_DIR}/models
    ln -sf ${MNT_DIR}/models ${COMFYUI_DIR}/models
    ln -sf ${BUILT_IN_DIR}/models/checkpoints/sd-v1-5-inpainting.ckpt ${COMFYUI_DIR}/models/checkpoints/sd-v1-5-inpainting.ckpt
    mkdir -p ${MNT_DIR}/snapshots
    mkdir -p ${MNT_DIR}/input
    mkdir -p ${MNT_DIR}/output
  else
    # SD-WebUI
    cp -r ${SD_DIR}/models ${MNT_DIR}/models
    rm -rf ${SD_DIR}/models
    ln -sf ${MNT_DIR}/models ${SD_DIR}/models
    ln -sf ${BUILT_IN_DIR}/models/checkpoints/sd-v1-5-inpainting.ckpt ${SD_DIR}/models/Stable-diffusion/sd-v1-5-inpainting.ckpt
    mkdir -p ${MNT_DIR}/snapshots
  fi
fi

mkdir -p ${MNT_DIR}/input
mkdir -p ${MNT_DIR}/output
source ${AGENT_DIR}/venv/bin/activate
echo "Using python venv, python path '$(which python)', pip path '$(which pip)'... "

check_and_init_mitmproxy
python ${AGENT_DIR}/main.py