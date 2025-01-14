FROM alpine/git:2.36.2 AS codes

WORKDIR /root

ENV COMFYUI_DIR="/root/comfyui"

RUN git clone https://github.com/comfyanonymous/ComfyUI.git ${COMFYUI_DIR} && \
    cd ${COMFYUI_DIR} && \
    git checkout "v0.3.10"

# add built-in custom-nodes
RUN cd ${COMFYUI_DIR}/custom_nodes && \
    git clone https://github.com/ltdrdata/ComfyUI-Manager.git && \
    cd ComfyUI-Manager && \
    git checkout "3.3"

FROM python:3.10.16-slim AS models

RUN apt update && apt install -y aria2

COPY --from=registry.cn-hangzhou.aliyuncs.com/ohyee/fc-demo:fc-comfyui-sd1.5-v1 "/built-in/models/checkpoints/sd-v1-5-inpainting.ckpt" "/models/checkpoints/sd-v1-5-inpainting.ckpt"

FROM python:3.10.16-slim AS dependencies

WORKDIR /root

# 升级pip并初始化venv虚拟环境
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    python3 -m venv venv

# 安装 PyTorch 及相关包
RUN --mount=type=cache,target=/root/.cache/pip \
    venv/bin/pip install --no-cache-dir torch torchvision torchaudio \
    --extra-index-url https://download.pytorch.org/whl/cu124

# issue: 历史原因，被某插件使用 @ohyee
RUN --mount=type=cache,target=/root/.cache/pip \
    venv/bin/pip install --no-cache-dir onnxruntime-gpu \
    --extra-index-url https://aiinfra.pkgs.visualstudio.com/PublicPackages/_packaging/onnxruntime-cuda-12/pypi/simple/

ENV COMFYUI_DIR="/root/comfyui"
COPY --from=codes ${COMFYUI_DIR} ${COMFYUI_DIR}

# 安装 源码 所使用的依赖
RUN --mount=type=cache,target=/root/.cache/pip \
    find ${COMFYUI_DIR} -type f -name requirements.txt | xargs -I {} venv/bin/pip install -r {} --no-cache-dir

FROM agent AS agent

FROM python:3.10.16-slim AS base

WORKDIR /root

RUN --mount=type=cache,target=/var/cache/apt \
    apt update && \
    apt install -y \
    rsync vim git curl wget jq ffmpeg \
    gcc g++ unzip build-essential

ENV WORK_DIR="/root"
ENV BUILT_IN_DIR="/built-in"
ENV COMFYUI_DIR="${WORK_DIR}/comfyui"
ENV VENV_DIR="${WORK_DIR}/venv"
ENV AGENT_DIR="${WORK_DIR}/agent"
# MNT_DIR is initialized in s.yaml
ARG IMAGE_TAG="${IMAGE_TAG}"
ENV IMAGE_TAG=${IMAGE_TAG}

COPY --from=models /models ${BUILT_IN_DIR}/models
COPY --from=codes ${COMFYUI_DIR} ${COMFYUI_DIR}
COPY --from=dependencies ${VENV_DIR} ${VENV_DIR}
COPY --from=agent ${AGENT_DIR} ${AGENT_DIR}
COPY built-in/ ${BUILT_IN_DIR}/
# TODO add pip path of venv

RUN chmod +x ${BUILT_IN_DIR}/entrypoint.bash
ENTRYPOINT [ "/bin/bash", "-c", "${BUILT_IN_DIR}/entrypoint.bash" ]
