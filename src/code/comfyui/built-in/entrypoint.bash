#!/bin/bash

# 文件目录总览
# - /built-in: 内置文件目录
# -- models: 内置模型，/root/comfyui/models/checkpoints/xxx.safetensors -> /built-in/models/checkpoints/xxx.safetensors

# - /root: 工作目录
# -- agent: agent程序所在目录
# -- comfyui
# --- models: comfyui模型目录，软链接到挂载存储中，/root/comfyui/models -> /mnt/${functionName}/models
# --- ...
# -- venv: 依赖目录

# - /mnt/${functionName}: 挂载目录，NAS or OSS
# -- models: 用户模型本体，/root/comfyui/models -> /mnt/${functionName}/models
# -- input: 输入图片
# -- output: 输出图片
# -- snapshots: 快照目录
# --- 20250101-015959
# ---- comfyui
# ---- venv.tar
# --- 20250102-120159
# ---- comfyui
# ---- venv.tar

echo "Mount dir: ${MNT_DIR}"
echo "Built-in dir: ${BUILT_IN_DIR}"
IMAGE_TAG=$(cat /IMAGE_TAG)
IMAGE_TAG_MNT=$(cat ${MNT_DIR}/IMAGE_TAG 2>/dev/null || echo '')
echo "IMAGE_TAG: [${IMAGE_TAG_MNT}] -> [${IMAGE_TAG}]"

if [ "${IMAGE_TAG}" != "${IMAGE_TAG_MNT}" ]; then
  echo "Do something with Image[${IMAGE_TAG}]..."
  # do something
  echo -n ${IMAGE_TAG} > ${MNT_DIR}/IMAGE_TAG
fi

# 初始化挂载目录
if [ ! -e "${MNT_DIR}/models" ]; then
  cp -r ${COMFYUI_DIR}/models ${MNT_DIR}/models
fi
rm -rf ${COMFYUI_DIR}/models
ln -s ${MNT_DIR}/models ${COMFYUI_DIR}/models
ln -sf ${BUILT_IN_DIR}/models/checkpoints/sd-v1-5-inpainting.ckpt ${COMFYUI_DIR}/models/checkpoints/sd-v1-5-inpainting.ckpt
mkdir -p ${MNT_DIR}/input
mkdir -p ${MNT_DIR}/output
mkdir -p ${MNT_DIR}/snapshots

## 启动(非agent模式)
#source venv/bin/activate
#echo "Using python venv, python path '$(which python)', pip path '$(which pip)'... "
#CLI_ARGS="${CLI_ARGS:---listen 0.0.0.0 --input-directory ${MNT_DIR}/input --output-directory ${MNT_DIR}/output --temp-directory ${MNT_DIR}/output}"
#EXTRA_ARGS="${EXTRA_ARGS:-}"
#export ARGS="${CLI_ARGS} ${EXTRA_ARGS}"
#python comfyui/main.py ${ARGS}

# 启动(agent模式)
source agent/venv/bin/activate
python agent/main.py
