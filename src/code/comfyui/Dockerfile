FROM alpine/git:2.36.2 AS codes

WORKDIR /root

ENV COMFYUI="/root/comfyui"

RUN git clone https://github.com/comfyanonymous/ComfyUI.git ${COMFYUI} && \
    cd ${COMFYUI} && \
    git checkout "v0.3.10"

# add built-in custom-nodes
RUN cd ${COMFYUI}/custom_nodes && \
    git clone https://github.com/ltdrdata/ComfyUI-Manager.git && \
    cd ComfyUI-Manager && \
    git checkout "3.3"

FROM python:3.10.16-slim AS models

RUN apt update && apt install -y aria2

COPY --from=registry.cn-hangzhou.aliyuncs.com/ohyee/fc-demo:fc-comfyui-sd1.5-v1 "/built-in/models/checkpoints/sd-v1-5-inpainting.ckpt" "/models/checkpoints/sd-v1-5-inpainting.ckpt"

FROM python:3.10.16-slim AS snapshots

WORKDIR /root

ENV COMFYUI="/root/comfyui"

COPY --from=codes ${COMFYUI} ${COMFYUI}

# 升级pip并初始化venv虚拟环境
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    python3 -m venv venv

# 安装 PyTorch 及相关包
RUN --mount=type=cache,target=/root/.cache/pip \
    venv/bin/pip install --no-cache-dir torch torchvision torchaudio \
    --extra-index-url https://download.pytorch.org/whl/cu124

# 安装 源码 所使用的依赖
RUN --mount=type=cache,target=/root/.cache/pip \
    find ${COMFYUI} -type f -name requirements.txt | xargs -I {} venv/bin/pip install -r {} --no-cache-dir

# issue: 历史原因，被某插件使用 @ohyee
RUN --mount=type=cache,target=/root/.cache/pip \
    venv/bin/pip install --no-cache-dir onnxruntime-gpu \
    --extra-index-url https://aiinfra.pkgs.visualstudio.com/PublicPackages/_packaging/onnxruntime-cuda-12/pypi/simple/

RUN tar -cf snapshot.tar venv comfyui

FROM python:3.10.16-slim AS base

WORKDIR /root

RUN --mount=type=cache,target=/var/cache/apt \
    apt update && \
    apt install -y \
    rsync vim git curl wget jq ffmpeg \
    gcc g++ unzip build-essential

ENV BUILT_IN_DIR="/built-in"
ENV MNT_DIR="/mnt/auto"
ENV COMFYUI_DIR="/root/comfyui"
ARG IMAGE_TAG="${IMAGE_TAG}"
ENV IMAGE_TAG=${IMAGE_TAG}

COPY --from=models /models ${BUILT_IN_DIR}/models
COPY --from=snapshots /root/snapshot.tar ${BUILT_IN_DIR}/snapshot.tar
COPY built-in/ ${BUILT_IN_DIR}/

RUN chmod +x ${BUILT_IN_DIR}/entrypoint.bash
ENTRYPOINT [ "/bin/bash", "-c", "${BUILT_IN_DIR}/entrypoint.bash" ]
