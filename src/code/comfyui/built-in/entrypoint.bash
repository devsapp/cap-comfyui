#!/bin/bash

# 文件目录总览
# - /built-in: 内置文件目录
# -- models: 内置模型，/root/comfyui/models/checkpoints/xxx.safetensors -> /built-in/models/checkpoints/xxx.safetensors

# - /root: 工作目录
# -- comfyui
# -- venv: 依赖目录

# - /mnt/${functionName}: 挂载目录，NAS or OSS
# -- models: 用户模型，/root/comfyui/models -> /mnt/${functionName}/models
# -- snapshots: (comfyui+venv)的快照目录，snapshot-20250101175933.tar
# -- input: 输入图片
# -- output: 输出图片

function set_start_time() {
  START_TIME=$(date '+%s.%N')
}

function show_cost_time() {
  echo "$START_TIME $(date '+%s.%N')" | awk "{printf \"$1, cost %f seconds\n\", \$2 - \$1}"
}

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

if [ -e "${MNT_DIR}/snapshots/snapshot.tar" ]; then
  # 优先使用用户挂载的存储中的快照
  echo "Downloading snapshot..."
  set_start_time
  cp ${MNT_DIR}/snapshots/snapshot.tar .
  show_cost_time "Downloaded snapshot"

  echo "Unpacking snapshot..."
  rm -rf comfyui venv
  set_start_time
  tar -xf snapshot.tar
  show_cost_time  "Unpacked snapshot"
  rm snapshot.tar
fi

mkdir -p ${MNT_DIR}/input
mkdir -p ${MNT_DIR}/output
if [ ! -e "${MNT_DIR}/models" ]; then
  cp -r ${COMFYUI_DIR}/models ${MNT_DIR}/models
fi
rm -rf ${COMFYUI_DIR}/models
ln -s ${MNT_DIR}/models ${COMFYUI_DIR}/models
ln -s ${BUILT_IN_DIR}/models/checkpoints/sd-v1-5-inpainting.ckpt ${COMFYUI_DIR}/models/checkpoints/sd-v1-5-inpainting.ckpt
mkdir -p ${MNT_DIR}/snapshots

source venv/bin/activate
echo "Using python venv, python path '$(which python)', pip path '$(which pip)'... "
CLI_ARGS="${CLI_ARGS:---listen 0.0.0.0 --input-directory ${MNT_DIR}/input --output-directory ${MNT_DIR}/output --temp-directory ${MNT_DIR}/output}"
EXTRA_ARGS="${EXTRA_ARGS:-}"
export ARGS="${CLI_ARGS} ${EXTRA_ARGS}"
python comfyui/main.py ${ARGS}
