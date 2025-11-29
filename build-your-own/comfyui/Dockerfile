# =============================================================================
# 自定义 ComfyUI 镜像构建文件
# =============================================================================
# 你可以根据需要修改 ComfyUI 版本、添加自定义节点、预置模型等
# =============================================================================

# 第一阶段：获取 ComfyUI 源码和自定义节点
FROM alpine/git:2.36.2 AS codes

WORKDIR /root

ENV COMFYUI_DIR="/root/comfyui"

# 克隆 ComfyUI 主项目
# 🔧 自定义点 1: 修改 ComfyUI 版本
# 你可以修改下面的版本号来使用不同的 ComfyUI 版本
RUN git clone https://github.com/comfyanonymous/ComfyUI.git ${COMFYUI_DIR} && \
    cd ${COMFYUI_DIR} && \
    git checkout "v0.3.50"  # 在这里修改版本号

# 安装 ComfyUI-Manager（推荐保留，用于管理插件）
RUN cd ${COMFYUI_DIR}/custom_nodes && \
    git clone https://github.com/ltdrdata/ComfyUI-Manager.git && \
    cd ComfyUI-Manager && \
    git checkout "3.5"

# 🔧 自定义点 2: 添加你需要的自定义节点
# 取消下面的注释并修改为你需要的插件
# 示例：添加 Nunchaku 加速插件
#RUN cd ${COMFYUI_DIR}/custom_nodes && \
#    git clone https://github.com/mit-han-lab/ComfyUI-nunchaku && \
#    cd ComfyUI-nunchaku && \
#    git checkout "v0.2.0"

# 示例：添加其他常用插件
#RUN cd ${COMFYUI_DIR}/custom_nodes && \
#    git clone https://github.com/Fannovel16/comfyui_controlnet_aux && \
#    git clone https://github.com/cubiq/ComfyUI_IPAdapter_plus

# 示例：从本地添加自定义节点
# COPY ./custom-nodes/your-custom-node ${COMFYUI_DIR}/custom_nodes/your-custom-node

FROM python:3.10.16-slim AS models

RUN apt update && apt install -y aria2

FROM python:3.10.16-slim AS dependencies

WORKDIR /root

# 升级pip并初始化venv虚拟环境
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    python3 -m venv venv

# 安装cu124最新PyTorch及相关包
RUN --mount=type=cache,target=/root/.cache/pip \
    venv/bin/pip install --no-cache-dir torch torchvision torchaudio \
    --extra-index-url https://download.pytorch.org/whl/cu124

RUN --mount=type=cache,target=/root/.cache/pip \
    venv/bin/pip install --no-cache-dir onnxruntime-gpu \
    --extra-index-url https://aiinfra.pkgs.visualstudio.com/PublicPackages/_packaging/onnxruntime-cuda-12/pypi/simple/

# 安装 ComfyUI源码 所使用的依赖
ENV COMFYUI_DIR="/root/comfyui"
COPY --from=codes ${COMFYUI_DIR} ${COMFYUI_DIR}
RUN --mount=type=cache,target=/root/.cache/pip \
    find ${COMFYUI_DIR} -type f -name requirements.txt | xargs -I {} venv/bin/pip install -r {} --no-cache-dir

# 安装 ComfyUI插件 所使用的依赖; codes层变化只会导致插件依赖重新安装，不会导致torch等基础依赖重新安装
ENV COMFYUI_NODE_DIR="/root/comfyui/custom_nodes"
COPY --from=codes ${COMFYUI_NODE_DIR} ${COMFYUI_NODE_DIR}
RUN --mount=type=cache,target=/root/.cache/pip \
    find ${COMFYUI_NODE_DIR} -type f -name requirements.txt | xargs -I {} venv/bin/pip install -r {} --no-cache-dir

FROM agent:latest AS agent

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

#ENV BUILT_IN_DIR="/built-in"
#COPY --from=models /models ${BUILT_IN_DIR}/models
COPY --from=dependencies ${VENV_DIR} ${VENV_DIR}
COPY --from=codes ${COMFYUI_DIR} ${COMFYUI_DIR}
COPY --from=agent ${AGENT_DIR} ${AGENT_DIR}

# 配置 pip
RUN mkdir -p ~/.pip \
 && cp ${AGENT_DIR}/services/proxy/pip.conf ~/.pip/pip.conf

ENV BACKEND_TYPE="comfyui"
ENTRYPOINT [ "/bin/bash", "-c", "${AGENT_DIR}/entrypoint.bash" ]
