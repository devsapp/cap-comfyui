FROM alpine/git:2.36.2 AS codes

WORKDIR /root

# 安装 jq（用于解析 JSON）
RUN apk add --no-cache jq

ENV COMFYUI_DIR="/root/comfyui"

RUN git clone https://github.com/comfyanonymous/ComfyUI.git ${COMFYUI_DIR} && \
    cd ${COMFYUI_DIR} && \
    git checkout "v0.3.75"

# 复制插件列表配置文件
COPY src/code/comfyui/custom_nodes_config/custom_nodes.json /tmp/custom_nodes.json

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

FROM cap-demo-public-registry.cn-hangzhou.cr.aliyuncs.com/cap-app/funart-python-base:3.10.16_3.12.10 AS dependencies

WORKDIR /root

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    python3.12 -m venv venv

# 安装 cu128 最新 PyTorch 及相关包
RUN --mount=type=cache,target=/root/.cache/pip \
    /root/venv/bin/pip install --no-cache-dir torch torchvision torchaudio \
    --extra-index-url https://download.pytorch.org/whl/cu128

# issue: 历史原因，被某插件使用 @ohyee
RUN --mount=type=cache,target=/root/.cache/pip \
    venv/bin/pip install --no-cache-dir onnxruntime-gpu \
    --extra-index-url https://aiinfra.pkgs.visualstudio.com/PublicPackages/_packaging/onnxruntime-cuda-12/pypi/simple/

ENV COMFYUI_DIR="/root/comfyui"
COPY --from=codes ${COMFYUI_DIR} ${COMFYUI_DIR}

ENV COMFYUI_NODE_DIR="/root/comfyui/custom_nodes"
ENV AGENT_DIR="/root/agent"
ENV AGENT_VENV_DIR="${AGENT_DIR}/venv"

# 复制 agent 代码（用于调用 PIPInstaller）
# 注意：需要从项目根目录构建，构建上下文应该是项目根目录
# 如果从 src/code/comfyui/ 构建，需要先复制 agent 代码到构建上下文
COPY src/code/agent ${AGENT_DIR}

# 复制安装脚本
COPY src/code/comfyui/custom_nodes_config/install_custom_nodes.py /root/install_custom_nodes.py

# 安装 agent 的依赖（供 PIPInstaller 运行，使用 /root/venv 环境）
RUN --mount=type=cache,target=/root/.cache/pip \
    pip3.10 install -r ${AGENT_DIR}/requirements.txt --no-cache-dir
# 先使用 PIPInstaller 安装自定义节点依赖
# 这会合并所有 requirements.txt，处理依赖冲突，并执行 install.py 脚本
# 使用 -u 参数确保 Python 输出无缓冲，实时显示日志
RUN --mount=type=cache,target=/root/.cache/pip \
    python3.10 -u /root/install_custom_nodes.py

# 安装 ComfyUI 源码的依赖
RUN --mount=type=cache,target=/root/.cache/pip \
    cd ${COMFYUI_DIR} && \
    if [ -f requirements.txt ]; then \
        /root/venv/bin/pip install -r requirements.txt --no-cache-dir; \
    else \
        echo "警告: ${COMFYUI_DIR}/requirements.txt 不存在"; \
    fi

FROM cap-demo-public-registry.cn-hangzhou.cr.aliyuncs.com/cap-app/funart-python-base:3.10.16_3.12.10 AS agent

WORKDIR /root

ENV AGENT_DIR="/root/agent"

RUN --mount=type=cache,target=/var/cache/apt \
    apt update && \
    apt install -y --no-install-recommends \
    git curl wget jq ffmpeg gcc g++ build-essential zstd && \
    rm -rf /var/lib/apt/lists/*

COPY src/code/agent ${AGENT_DIR}

RUN python3.10 -m venv ${AGENT_DIR}/venv

RUN --mount=type=cache,target=/root/.cache/pip \
    ${AGENT_DIR}/venv/bin/pip install --upgrade pip && \
    ${AGENT_DIR}/venv/bin/pip install -r ${AGENT_DIR}/requirements.txt --no-cache-dir


FROM cap-demo-public-registry.cn-hangzhou.cr.aliyuncs.com/cap-app/funart-python-base:3.10.16_3.12.10 AS base

WORKDIR /root

RUN --mount=type=cache,target=/var/cache/apt \
    apt update && \
    apt install -y --no-install-recommends \
    git curl wget jq ffmpeg gcc g++ build-essential zstd && \
    rm -rf /var/lib/apt/lists/*

ENV WORK_DIR="/root"
ENV COMFYUI_DIR="${WORK_DIR}/comfyui"
ENV VENV_DIR="${WORK_DIR}/venv"
ENV AGENT_DIR="${WORK_DIR}/agent"
ENV AGENT_VENV_DIR="${AGENT_DIR}/venv"

COPY --from=dependencies ${VENV_DIR} ${VENV_DIR}
COPY --from=agent ${AGENT_DIR} ${AGENT_DIR}
COPY --from=codes ${COMFYUI_DIR} ${COMFYUI_DIR}

COPY src/code/comfyui/comfyui_manager_config/config.ini /tmp/comfyui_manager_config.ini
COPY src/code/comfyui/comfyui_manager_config/channels.list /tmp/comfyui_manager_channels.list
# 显式复制 custom_nodes 目录（确保被正确复制）
# 如果上面的 COPY 没有正确复制 custom_nodes，这里作为备选方案
# COPY --from=codes ${COMFYUI_DIR}/custom_nodes ${COMFYUI_DIR}/custom_nodes

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

RUN chmod +x ${AGENT_DIR}/entrypoint.bash

ENTRYPOINT [ "/bin/bash", "-c", "${AGENT_DIR}/entrypoint.bash" ]
