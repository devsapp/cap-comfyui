FROM alpine/git:2.36.2 AS codes

WORKDIR /root

ENV COMFYUI_DIR="/root/comfyui"

# 1130 版本
RUN git clone https://github.com/comfyanonymous/ComfyUI.git ${COMFYUI_DIR} && \
    cd ${COMFYUI_DIR} && \
    git checkout "v0.3.75"

# 复制插件列表配置文件
COPY custom_nodes.json /tmp/custom_nodes.json

# 批量安装自定义节点插件
# 从 custom_nodes.json 读取插件列表，循环安装启用的插件
RUN cd ${COMFYUI_DIR}/custom_nodes && \
    echo "=== 开始批量安装 ComfyUI 插件 ===" && \
    for plugin in $(jq -r '.custom_nodes[] | select(.enabled == true) | "\(.repository)|\(.version)|\(.id)"' /tmp/custom_nodes.json); do \
        repo=$(echo $plugin | cut -d'|' -f1); \
        version=$(echo $plugin | cut -d'|' -f2); \
        plugin_id=$(echo $plugin | cut -d'|' -f3); \
        plugin_name=$(basename $repo .git); \
        echo ""; \
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; \
        echo "📦 安装插件: $plugin_name"; \
        echo "   仓库: $repo"; \
        echo "   版本: $version"; \
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; \
        if git clone --quiet $repo $plugin_name 2>&1; then \
            echo "✅ 克隆成功"; \
            if [ -d "$plugin_name" ] && [ "$version" != "latest" ] && [ "$version" != "" ]; then \
                cd $plugin_name && \
                if git checkout "$version" 2>/dev/null; then \
                    echo "✅ 切换到版本: $version"; \
                else \
                    echo "⚠️  警告: 无法切换到版本 $version，使用默认分支"; \
                fi && \
                cd ..; \
            else \
                echo "✅ 使用默认分支"; \
            fi; \
        else \
            echo "❌ 克隆失败: $repo"; \
        fi; \
    done && \
    echo ""; \
    echo "=== 插件安装完成 ===" && \
    echo "已安装插件列表:" && \
    ls -1 ${COMFYUI_DIR}/custom_nodes/ | head -20

FROM python:3.10.16-slim AS models

RUN apt update && apt install -y aria2

# COPY --from=registry.cn-hangzhou.aliyuncs.com/ohyee/fc-demo:fc-comfyui-sd1.5-v1 "/built-in/models/checkpoints/sd-v1-5-inpainting.ckpt" "/models/checkpoints/sd-v1-5-inpainting.ckpt"

FROM python:3.10.16-slim AS dependencies

WORKDIR /root

# 升级pip并初始化venv虚拟环境
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    python3 -m venv venv

# 安装cu124最新PyTorch及相关包
RUN --mount=type=cache,target=/root/.cache/pip \
    venv/bin/pip install --no-cache-dir torch torchvision torchaudio \
    --extra-index-url https://download.pytorch.org/whl/cu128

# issue: 历史原因，被某插件使用 @ohyee
RUN --mount=type=cache,target=/root/.cache/pip \
    venv/bin/pip install --no-cache-dir onnxruntime-gpu \
    --extra-index-url https://aiinfra.pkgs.visualstudio.com/PublicPackages/_packaging/onnxruntime-cuda-12/pypi/simple/

# 安装 ComfyUI源码 所使用的依赖
# pip install动态拉取comfyui源码中的requirements.txt
ENV COMFYUI_DIR="/root/comfyui"
COPY --from=codes ${COMFYUI_DIR} ${COMFYUI_DIR}
RUN --mount=type=cache,target=/root/.cache/pip \
    find ${COMFYUI_DIR} -type f -name requirements.txt | xargs -I {} venv/bin/pip install -r {} --no-cache-dir

# 安装 ComfyUI插件 所使用的依赖; codes层变化只会导致插件依赖重新安装，不会导致torch等基础依赖重新安装
# 使用健壮的 PIPInstaller 逻辑来处理依赖冲突
ENV COMFYUI_NODE_DIR="/root/comfyui/custom_nodes"
ENV AGENT_DIR="/root/agent"
COPY --from=codes ${COMFYUI_NODE_DIR} ${COMFYUI_NODE_DIR}

# 复制 agent 代码（用于调用 PIPInstaller）
# 注意：这里从构建上下文复制 agent 代码，而不是从 agent 镜像
# 因为 dependencies 阶段在 agent 镜像构建之前
COPY src/code/agent ${AGENT_DIR}

# 复制安装脚本
COPY src/code/comfyui/install_custom_nodes.py /root/install_custom_nodes.py

# 使用 PIPInstaller 安装自定义节点依赖
# 这会合并所有 requirements.txt，处理依赖冲突，并执行 install.py 脚本
RUN --mount=type=cache,target=/root/.cache/pip \
    venv/bin/python /root/install_custom_nodes.py

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

ENV BUILT_IN_DIR="/built-in"
COPY --from=models /models ${BUILT_IN_DIR}/models
COPY --from=dependencies ${VENV_DIR} ${VENV_DIR}
COPY --from=codes ${COMFYUI_DIR} ${COMFYUI_DIR}
COPY --from=agent ${AGENT_DIR} ${AGENT_DIR}
# TODO add pip path of venv

ENV BACKEND_TYPE="comfyui"
ENTRYPOINT [ "/bin/bash", "-c", "${AGENT_DIR}/entrypoint.bash" ]
