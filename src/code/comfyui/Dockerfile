FROM alpine/git:2.36.2 AS codes

WORKDIR /root

ENV COMFYUI_DIR="/root/comfyui"

RUN git clone https://github.com/comfyanonymous/ComfyUI.git ${COMFYUI_DIR} && \
    cd ${COMFYUI_DIR} && \
    git checkout "v0.3.75"

# add built-in custom-nodes
RUN cd ${COMFYUI_DIR}/custom_nodes && \
    git clone https://github.com/ltdrdata/ComfyUI-Manager.git && \
    cd ComfyUI-Manager && \
    git checkout "3.39"

FROM python:3.10.16-slim AS dependencies

WORKDIR /root

# 升级pip并初始化venv虚拟环境
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    python3 -m venv venv

# 安装cu128最新PyTorch及相关包
RUN --mount=type=cache,target=/root/.cache/pip \
    venv/bin/pip install --no-cache-dir torch torchvision torchaudio \
    --extra-index-url https://download.pytorch.org/whl/cu128

# 安装 ComfyUI源码 所使用的依赖
# 方式一: pip install动态拉取comfyui源码中的requirements.txt, 缺点：与codes层耦合，源码有新的commit会导致镜像层重新构建
ENV COMFYUI_DIR="/root/comfyui"
COPY --from=codes ${COMFYUI_DIR} ${COMFYUI_DIR}
RUN --mount=type=cache,target=/root/.cache/pip \
   find ${COMFYUI_DIR} -type f -name requirements.txt | xargs -I {} venv/bin/pip install -r {} --no-cache-dir 

# 安装 ComfyUI插件 所使用的依赖; codes层变化只会导致插件依赖重新安装，不会导致torch等基础依赖重新安装
ENV COMFYUI_NODE_DIR="/root/comfyui/custom_nodes"
COPY --from=codes ${COMFYUI_NODE_DIR} ${COMFYUI_NODE_DIR}
RUN --mount=type=cache,target=/root/.cache/pip \
    find ${COMFYUI_NODE_DIR} -type f -name requirements.txt | xargs -I {} venv/bin/pip install -r {} --no-cache-dir

FROM agent AS agent

FROM python:3.10.16-slim AS base

WORKDIR /root

RUN --mount=type=cache,target=/var/cache/apt \
    apt update && \
    apt install -y \
    git curl wget jq ffmpeg gcc g++ build-essential zstd

ENV WORK_DIR="/root"
ENV COMFYUI_DIR="${WORK_DIR}/comfyui"
ENV VENV_DIR="${WORK_DIR}/venv"
ENV AGENT_DIR="${WORK_DIR}/agent"
# MNT_DIR is initialized in s.yaml, using env var-'MODEL_ASSET_DIR'

COPY --from=dependencies ${VENV_DIR} ${VENV_DIR}
COPY --from=codes ${COMFYUI_DIR} ${COMFYUI_DIR}
COPY --from=agent ${AGENT_DIR} ${AGENT_DIR}
# TODO add pip path of venv

ENV BACKEND_TYPE="comfyui"
ENTRYPOINT [ "/bin/bash", "-c", "${AGENT_DIR}/entrypoint.bash" ]
