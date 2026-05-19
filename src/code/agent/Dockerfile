ARG COMFYUI_IMAGE=cap-demo-public-registry.cn-hangzhou.cr.aliyuncs.com/aliyunfc/funart-comfyui:v1.6.5
FROM ${COMFYUI_IMAGE} AS comfyui_source_raw

# 确保 built-in/custom_nodes 目录存在（某些版本的源镜像可能缺少该路径）
FROM comfyui_source_raw AS comfyui_source
RUN mkdir -p /root/built-in/custom_nodes

FROM python:3.10.16-slim

WORKDIR /root

RUN --mount=type=cache,target=/var/cache/apt \
    # 本地构建时需使用阿里镜像源加速
    sed -i 's@deb.debian.org@mirrors.aliyun.com@g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's@deb.debian.org@mirrors.aliyun.com@g' /etc/apt/sources.list && \
    apt update && \
    apt install -y \
    git curl wget jq ffmpeg gcc g++ build-essential libgl1 libglib2.0-0 iputils-ping \
    procps vim unzip zstd

# 安装 cuda-toolkit-12-8: https://developer.nvidia.com/cuda-12-8-0-download-archive?target_os=Linux&target_arch=x86_64&Distribution=Debian&target_version=12&target_type=deb_local
# RUN wget https://developer.download.nvidia.com/compute/cuda/12.8.0/local_installers/cuda-repo-debian12-12-8-local_12.8.0-570.86.10-1_amd64.deb && \
#     dpkg -i cuda-repo-debian12-12-8-local_12.8.0-570.86.10-1_amd64.deb && \
#     cp /var/cuda-repo-debian12-12-8-local/cuda-*-keyring.gpg /usr/share/keyrings/ && \
#     apt-get update && \
#     apt-get -y install cuda-toolkit-12-8 && \
#     rm -f cuda-repo-debian12-12-8-local_12.8.0-570.86.10-1_amd64.deb

# 安装 ossutil
RUN curl -o ossutil-2.1.2-linux-amd64.zip https://gosspublic.alicdn.com/ossutil/v2/2.1.2/ossutil-2.1.2-linux-amd64.zip && \
    unzip ossutil-2.1.2-linux-amd64.zip && \
    cd ossutil-2.1.2-linux-amd64 && \
    chmod 755 ossutil && \
    mv ossutil /usr/local/bin/ && \
    ln -s /usr/local/bin/ossutil /usr/bin/ossutil && \
    cd .. && \
    rm -rf ossutil-2.1.2-linux-amd64 ossutil-2.1.2-linux-amd64.zip

# 下载 transparent-background 模型（拆分层以利用 Docker 缓存，避免大文件下载中断后全部重来）
RUN mkdir -p ~/.transparent-background
RUN wget --retry-connrefused --tries=3 -P ~/.transparent-background \
    https://github.com/plemeri/transparent-background/releases/download/1.2.12/ckpt_base.pth
RUN wget --retry-connrefused --tries=3 -P ~/.transparent-background \
    https://github.com/plemeri/transparent-background/releases/download/1.2.12/ckpt_fast.pth
RUN wget --retry-connrefused --tries=3 -P ~/.transparent-background \
    https://github.com/plemeri/transparent-background/releases/download/1.2.12/ckpt_base_nightly.pth


# 下载 rembg 模型
RUN mkdir ~/.rembg && \
    cd ~/.rembg && \
    wget https://huggingface.co/tomjackson2023/rembg/resolve/main/u2net.onnx

# 从 comfyui 镜像拷贝内置插件到 built-in 目录
COPY --from=comfyui_source /root/built-in/custom_nodes /root/built-in/custom_nodes

# 写入内置插件版本号，供启动时版本检查使用
# 版本号需随内置插件列表的实质性变化（增删插件、升级版本）而更新
RUN echo "1.6.5" > /root/built-in/version.txt

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

RUN chmod +x ${AGENT_DIR}/entrypoint.bash
ENTRYPOINT [ "/bin/bash", "-c", "agent/entrypoint.bash" ]
