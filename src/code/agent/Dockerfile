ARG COMFYUI_IMAGE=comfyui:v0304
FROM ${COMFYUI_IMAGE} AS comfyui_source

FROM python:3.10.16-slim

WORKDIR /root

RUN --mount=type=cache,target=/var/cache/apt \
    # 本地构建时可取消注释以使用阿里云镜像源加速
    sed -i 's@deb.debian.org@mirrors.aliyun.com@g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's@deb.debian.org@mirrors.aliyun.com@g' /etc/apt/sources.list && \
    apt update && \
    apt install -y \
    git curl wget jq ffmpeg gcc g++ build-essential libgl1 libglib2.0-0 iputils-ping \
    procps vim unzip zstd

# 安装 ossutil
RUN curl -o ossutil-2.1.2-linux-amd64.zip https://gosspublic.alicdn.com/ossutil/v2/2.1.2/ossutil-2.1.2-linux-amd64.zip && \
    unzip ossutil-2.1.2-linux-amd64.zip && \
    cd ossutil-2.1.2-linux-amd64 && \
    chmod 755 ossutil && \
    mv ossutil /usr/local/bin/ && \
    ln -s /usr/local/bin/ossutil /usr/bin/ossutil && \
    cd .. && \
    rm -rf ossutil-2.1.2-linux-amd64 ossutil-2.1.2-linux-amd64.zip

# 下载 transparent-background 模型
RUN mkdir ~/.transparent-background && \
    cd ~/.transparent-background && \
    wget https://github.com/plemeri/transparent-background/releases/download/1.2.12/ckpt_base.pth && \
    wget https://github.com/plemeri/transparent-background/releases/download/1.2.12/ckpt_fast.pth && \
    wget https://github.com/plemeri/transparent-background/releases/download/1.2.12/ckpt_base_nightly.pth

ENV WORK_DIR='/root'
ENV COMFYUI_DIR="${WORK_DIR}/comfyui"
ENV SD_DIR="${WORK_DIR}/stable-diffusion-webui"
ENV VENV_DIR="${WORK_DIR}/venv"
ENV AGENT_DIR="${WORK_DIR}/agent"
# 用户登录实例时默认使用comfyui/sd的python环境，工作空间启动前会fallback到默认的python环境
ENV PATH="${VENV_DIR}/bin:$PATH"

# MNT_DIR is initialized in s.yaml, using env var-'MODEL_ASSET_DIR'

RUN pip install --no-cache-dir huggingface_hub[cli] modelscope

COPY . ${AGENT_DIR}/

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    python3 -m venv ${AGENT_DIR}/venv

RUN --mount=type=cache,target=/root/.cache/pip \
    ${AGENT_DIR}/venv/bin/pip install -r ${AGENT_DIR}/requirements.txt --no-cache-dir

RUN mkdir -p ~/.pip \
 && cp ${AGENT_DIR}/services/proxy/pip.conf ~/.pip/pip.conf \
 && cp ${AGENT_DIR}/services/proxy/gitconfig.conf ~/.gitconfig

# 设置 GitHub 代理监控脚本执行权限
RUN chmod +x ${AGENT_DIR}/services/proxy/github-proxy-monitor.sh

ENV BUILTIN_NODES_DIR="/root/built-in/custom_nodes"

# 从 comfyui 镜像拷贝内置插件到 built-in 目录
COPY --from=comfyui_source /root/comfyui/custom_nodes ${BUILTIN_NODES_DIR}

RUN chmod +x ${AGENT_DIR}/entrypoint.bash
ENTRYPOINT [ "/bin/bash", "-c", "agent/entrypoint.bash" ]
