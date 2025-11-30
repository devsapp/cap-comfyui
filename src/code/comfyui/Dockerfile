FROM alpine/git:2.36.2 AS codes

WORKDIR /root

# 安装 jq（用于解析 JSON）
RUN apk add --no-cache jq

ENV COMFYUI_DIR="/root/comfyui"

# 1130 版本
RUN git clone https://github.com/comfyanonymous/ComfyUI.git ${COMFYUI_DIR} && \
    cd ${COMFYUI_DIR} && \
    git checkout "v0.3.75"

# 复制插件列表配置文件
COPY src/code/comfyui/custom_nodes.json /tmp/custom_nodes.json

# 批量安装自定义节点插件
# 从 custom_nodes.json 读取插件列表，循环安装启用的插件
RUN cd ${COMFYUI_DIR}/custom_nodes && \
    echo "=== 开始批量安装 ComfyUI 插件 ===" && \
    echo "检查 custom_nodes.json 文件..." && \
    if [ ! -f /tmp/custom_nodes.json ]; then \
        echo "错误: custom_nodes.json 文件不存在！" && \
        exit 1; \
    fi && \
    echo "解析启用的插件..." && \
    ENABLED_PLUGINS=$(jq -r '.custom_nodes[] | select(.enabled == true) | "\(.repository)|\(.version)|\(.id)"' /tmp/custom_nodes.json) && \
    PLUGIN_COUNT=$(echo "$ENABLED_PLUGINS" | grep -v '^$' | wc -l) && \
    echo "找到 ${PLUGIN_COUNT} 个启用的插件" && \
    if [ "${PLUGIN_COUNT}" -eq 0 ]; then \
        echo "警告: 没有找到启用的插件！" && \
        echo "custom_nodes.json 内容预览:" && \
        head -20 /tmp/custom_nodes.json && \
        exit 1; \
    fi && \
    FAILED_COUNT=0 && \
    for plugin in $ENABLED_PLUGINS; do \
        [ -z "$plugin" ] && continue; \
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
            echo "❌ 克隆失败: $repo" && \
            FAILED_COUNT=$((FAILED_COUNT + 1)); \
        fi; \
    done && \
    if [ "${FAILED_COUNT}" -gt 0 ]; then \
        echo ""; \
        echo "错误: ${FAILED_COUNT} 个插件安装失败！" && \
        exit 1; \
    fi && \
    echo ""; \
    echo "=== 插件安装完成 ===" && \
    echo "已安装插件列表:" && \
    ls -1 ${COMFYUI_DIR}/custom_nodes/ | head -20 && \
    echo ""; \
    echo "=== 验证 custom_nodes 目录（codes stage）===" && \
    echo "custom_nodes 目录路径: ${COMFYUI_DIR}/custom_nodes" && \
    if [ ! -d "${COMFYUI_DIR}/custom_nodes" ]; then \
        echo "错误: custom_nodes 目录不存在！" && \
        exit 1; \
    fi && \
    PLUGIN_COUNT=$(ls -1 ${COMFYUI_DIR}/custom_nodes/ 2>/dev/null | wc -l) && \
    echo "目录存在: 是" && \
    echo "插件数量: ${PLUGIN_COUNT}" && \
    if [ "${PLUGIN_COUNT}" -eq 0 ]; then \
        echo "警告: custom_nodes 目录为空！" && \
        exit 1; \
    fi && \
    echo "验证通过: codes stage 中的 custom_nodes 包含 ${PLUGIN_COUNT} 个插件"

FROM python:3.10.16-slim AS models

RUN apt update && apt install -y aria2

# 创建 /models 目录（即使没有模型文件，也要创建空目录以避免 COPY 失败）
RUN mkdir -p /models

# COPY --from=registry.cn-hangzhou.aliyuncs.com/ohyee/fc-demo:fc-comfyui-sd1.5-v1 "/built-in/models/checkpoints/sd-v1-5-inpainting.ckpt" "/models/checkpoints/sd-v1-5-inpainting.ckpt"

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

# 安装 ComfyUI插件 所使用的依赖
# 使用健壮的 PIPInstaller 逻辑来处理依赖冲突
# 注意：custom_nodes 已经包含在上面的 COPY 中，这里只需要设置环境变量
ENV COMFYUI_NODE_DIR="/root/comfyui/custom_nodes"
ENV AGENT_DIR="/root/agent"

# 复制 agent 代码（用于调用 PIPInstaller）
# 注意：需要从项目根目录构建，构建上下文应该是项目根目录
# 如果从 src/code/comfyui/ 构建，需要先复制 agent 代码到构建上下文
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
COPY --from=agent ${AGENT_DIR} ${AGENT_DIR}
# TODO add pip path of venv

# 复制 ComfyUI 主目录（包含 custom_nodes）
COPY --from=codes ${COMFYUI_DIR} ${COMFYUI_DIR}

# 显式复制 custom_nodes 目录（确保被正确复制）
# 如果上面的 COPY 没有正确复制 custom_nodes，这里作为备选方案
COPY --from=codes ${COMFYUI_DIR}/custom_nodes ${COMFYUI_DIR}/custom_nodes

# 显式验证并确保 custom_nodes 被正确复制
# 如果 custom_nodes 不存在，构建应该失败
RUN set -x && \
    echo "========================================" && \
    echo "验证 custom_nodes 是否正确复制" && \
    echo "========================================" && \
    echo "检查 ${COMFYUI_DIR}/custom_nodes 目录..." && \
    if [ ! -d "${COMFYUI_DIR}/custom_nodes" ]; then \
        echo "错误: custom_nodes 目录不存在！" && \
        echo "检查 comfyui 目录内容:" && \
        ls -la ${COMFYUI_DIR}/ | head -20 && \
        exit 1; \
    fi && \
    PLUGIN_COUNT=$(ls -1 ${COMFYUI_DIR}/custom_nodes/ 2>/dev/null | wc -l) && \
    echo "插件数量: ${PLUGIN_COUNT}" && \
    if [ "${PLUGIN_COUNT}" -eq 0 ]; then \
        echo "警告: custom_nodes 目录存在但为空！" && \
        echo "检查目录权限和内容:" && \
        ls -la ${COMFYUI_DIR}/custom_nodes/ && \
        exit 1; \
    fi && \
    echo "前10个插件:" && \
    ls -1 ${COMFYUI_DIR}/custom_nodes/ | head -10 && \
    echo "========================================" && \
    echo "验证通过: custom_nodes 目录存在且包含 ${PLUGIN_COUNT} 个插件"

ENV BACKEND_TYPE="comfyui"
ENTRYPOINT [ "/bin/bash", "-c", "${AGENT_DIR}/entrypoint.bash" ]
