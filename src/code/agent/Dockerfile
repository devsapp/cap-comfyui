FROM python:3.10.16-slim

WORKDIR /root

RUN --mount=type=cache,target=/var/cache/apt \
    apt update && \
    apt install -y \
    git curl wget jq ffmpeg gcc g++ build-essential libgl1 libglib2.0-0

ENV WORK_DIR='/root'
ENV COMFYUI_DIR="${WORK_DIR}/comfyui"
ENV SD_DIR="${WORK_DIR}/stable-diffusion-webui"
ENV VENV_DIR="${WORK_DIR}/venv"
ENV AGENT_DIR="${WORK_DIR}/agent"
# 用户登录实例时默认使用comfyui/sd的python环境，工作空间启动前会fallback到默认的python环境
ENV PATH="${VENV_DIR}/bin:$PATH"

# MNT_DIR is initialized in s.yaml, using env var-'MODEL_ASSET_DIR'

RUN pip install --no-cache-dir mitmproxy huggingface_hub[cli]

COPY . ${AGENT_DIR}/

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    python3 -m venv ${AGENT_DIR}/venv

RUN --mount=type=cache,target=/root/.cache/pip \
    ${AGENT_DIR}/venv/bin/pip install -r ${AGENT_DIR}/requirements.txt --no-cache-dir

RUN mkdir -p ~/.pip \
 && cp ${AGENT_DIR}/services/proxy/pip.conf ~/.pip/pip.conf

RUN chmod +x ${AGENT_DIR}/entrypoint.bash
ENTRYPOINT [ "/bin/bash", "-c", "agent/entrypoint.bash" ]
