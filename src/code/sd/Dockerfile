FROM alpine/git:2.36.2 AS codes

WORKDIR /root

ENV SD_DIR="/root/stable-diffusion-webui"
ENV REPO_DIR="${SD_DIR}/repositories"

RUN git clone https://github.com/AUTOMATIC1111/stable-diffusion-webui.git ${SD_DIR} && \
    cd ${SD_DIR} && \
    git checkout "v1.10.1"

# repositories
RUN git clone https://github.com/Stability-AI/stablediffusion.git ${REPO_DIR}/stable-diffusion-stability-ai && \
    cd ${REPO_DIR}/stable-diffusion-stability-ai && \
    git reset --hard cf1d67a6fd5ea1aa600c4df58e5b47da45f6bdbf

RUN git clone https://github.com/Stability-AI/generative-models.git ${REPO_DIR}/generative-models && \
    cd ${REPO_DIR}/generative-models && \
    git reset --hard 45c443b316737a4ab6e40413d7794a7f5657c19f

RUN git clone https://github.com/salesforce/BLIP.git ${REPO_DIR}/BLIP && \
    cd ${REPO_DIR}/BLIP && \
    git reset --hard 48211a1594f1321b00f14c9f7a5b4813144b2fb9

RUN git clone https://github.com/crowsonkb/k-diffusion.git ${REPO_DIR}/k-diffusion && \
    cd ${REPO_DIR}/k-diffusion && \
    git reset --hard ab527a9a6d347f364e3d185ba6d714e22d80cb3c

RUN git clone https://github.com/AUTOMATIC1111/stable-diffusion-webui-assets ${REPO_DIR}/stable-diffusion-webui-assets && \
    cd ${REPO_DIR}/stable-diffusion-webui-assets && \
    git reset --hard 6f7db241d2f8ba7457bac5ca9753331f0c266917

FROM python:3.10.16-slim AS models

RUN apt update && apt install -y aria2

COPY --from=registry.cn-hangzhou.aliyuncs.com/ohyee/fc-demo:fc-comfyui-sd1.5-v1 "/built-in/models/checkpoints/sd-v1-5-inpainting.ckpt" "/models/checkpoints/sd-v1-5-inpainting.ckpt"

FROM python:3.10.16-slim AS dependencies

WORKDIR /root

# 升级pip并初始化venv虚拟环境
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    python3 -m venv venv

# 安装cu124最新PyTorch及相关包，需锁版本与requirements.txt中一致
RUN --mount=type=cache,target=/root/.cache/pip \
    venv/bin/pip install --no-cache-dir torch==2.6.0 torchvision==0.21.0 xformers \
    --extra-index-url https://download.pytorch.org/whl/cu124

# 安装 源码 所使用的依赖
# issue: 安装低版本transformers依赖(例如4.15.0)时, 其依赖项tokenizers需要rust环境
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    venv/bin/pip install --no-cache-dir -r requirements.txt

FROM agent AS agent

FROM python:3.10.16-slim AS base

WORKDIR /root

RUN --mount=type=cache,target=/var/cache/apt \
    apt update && \
    apt install -y \
    git curl wget jq ffmpeg gcc g++ build-essential libgl1 libglib2.0-0 zstd

ENV WORK_DIR='/root'
ENV SD_DIR="${WORK_DIR}/stable-diffusion-webui"
ENV VENV_DIR="${WORK_DIR}/venv"
ENV AGENT_DIR="${WORK_DIR}/agent"
# MNT_DIR is initialized in s.yaml, using env var-'MODEL_ASSET_DIR'

ENV BUILT_IN_DIR="/built-in"
COPY --from=models /models ${BUILT_IN_DIR}/models
COPY --from=dependencies ${VENV_DIR} ${VENV_DIR}
COPY --from=codes ${SD_DIR} ${SD_DIR}
COPY .cache ${WORK_DIR}/.cache
# 仅首次运行时才会自动生成config.json，为了保证制作的base工作空间快照的正确性，需要手动拷贝包含默认配置的config.json
COPY config.json ${SD_DIR}/config.json
COPY --from=agent ${AGENT_DIR} ${AGENT_DIR}
# TODO add pip path of venv

ENV BACKEND_TYPE="sd"
ENTRYPOINT [ "/bin/bash", "-c", "${AGENT_DIR}/entrypoint.bash" ]
