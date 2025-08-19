FROM python:3.10.16-slim

WORKDIR /root

RUN --mount=type=cache,target=/var/cache/apt \
    apt update && \
    apt install -y \
    git curl wget jq ffmpeg gcc g++ build-essential libgl1 libglib2.0-0 iputils-ping procps software-properties-common

# 安装 cuda-toolkit12-4: https://developer.nvidia.com/cuda-12-4-0-download-archive?target_os=Linux&target_arch=x86_64&Distribution=Debian&target_version=10&target_type=deb_local
RUN wget https://developer.download.nvidia.com/compute/cuda/12.4.0/local_installers/cuda-repo-debian10-12-4-local_12.4.0-550.54.14-1_amd64.deb && \
    dpkg -i cuda-repo-debian10-12-4-local_12.4.0-550.54.14-1_amd64.deb && \
    cp /var/cuda-repo-debian10-12-4-local/cuda-*-keyring.gpg /usr/share/keyrings && \
    add-apt-repository contrib && \
    apt-get update && \
    apt-get -y install cuda-toolkit-12-4

ENV WORK_DIR='/root'
ENV COMFYUI_DIR="${WORK_DIR}/comfyui"
ENV SD_DIR="${WORK_DIR}/stable-diffusion-webui"
ENV VENV_DIR="${WORK_DIR}/venv"
ENV AGENT_DIR="${WORK_DIR}/agent"
# 用户登录实例时默认使用comfyui/sd的python环境，工作空间启动前会fallback到默认的python环境
ENV PATH="${VENV_DIR}/bin:$PATH"

# MNT_DIR is initialized in s.yaml, using env var-'MODEL_ASSET_DIR'

RUN pip install --no-cache-dir mitmproxy huggingface_hub[cli] modelscope

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
