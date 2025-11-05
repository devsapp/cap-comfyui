#!/bin/bash

# GitHub 代理守护进程
# 功能：持续监测 GitHub 代理可用性，自动切换到可用的代理
# 工作原理：
#   1. 默认使用主代理，每 60 秒检测是否可用
#   2. 如果主代理不可用，遍历备用代理列表查找可用的
#   3. 自动更新 Git 全局配置

set -e

# ==================== 配置 ====================

# 代理列表（按优先级排序）
PROXIES=(
    "https://cap-accor-proxy-qkqnjxeail.ap-southeast-1.fcapp.run/https://github.com/"
    "https://cap-accor-proxy-qkqnjxeail.cn-hongkong.fcapp.run/https://github.com/"
    "https://gh.llkk.cc/https://github.com/"
    "https://ghproxy.com/https://github.com/"
    "https://ghfast.top/https://github.com/"
)

# 日志文件
LOG_FILE="/tmp/github_proxy_daemon.log"

# 当前使用的代理
CURRENT_PROXY=""

# ==================== 工具函数 ====================

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
}

# 测试代理是否可用
test_proxy() {
    local proxy_url="$1"
    local timeout=3
    
    # 测试访问 ComfyUI 仓库
    if curl -s --connect-timeout $timeout --max-time $timeout "${proxy_url}" > /dev/null 2>&1; then
        return 0  # 成功
    else
        log "❌ Proxy test failed: $proxy_url"
        return 1  # 失败
    fi
}

# 查找可用的代理
find_working_proxy() {
    for proxy in "${PROXIES[@]}"; do
        if test_proxy "$proxy"; then
            log "✅ Found working proxy: $proxy"
            return 0
        fi
    done
    log "⚠️  No working proxy found, using direct connection"

    return 1
}

# 设置 Git 代理配置
set_git_proxy() {
    local proxy="$1"
    
    # 先清除所有现有配置
    git config --global --unset-all url."https://cap-accor-proxy-qkqnjxeail.ap-southeast-1.fcapp.run/https://github.com/".insteadOf 2>/dev/null || true
    git config --global --unset-all url."https://cap-accor-proxy-qkqnjxeail.cn-hongkong.fcapp.run/https://github.com/".insteadOf 2>/dev/null || true
    git config --global --unset-all url."https://gh.llkk.cc/https://github.com/".insteadOf 2>/dev/null || true
    git config --global --unset-all url."https://ghproxy.com/https://github.com/".insteadOf 2>/dev/null || true
    git config --global --unset-all url."https://ghfast.top/https://github.com/".insteadOf 2>/dev/null || true
    
    if [ "$proxy" != "direct" ]; then
        # 设置新代理
        git config --global url."${proxy}".insteadOf "https://github.com/"
        log "✅ Switched to proxy: $proxy"
    else
        log "ℹ️  Using direct connection (no proxy available)"
    fi
}

# ==================== 主循环 ====================

log "=========================================="
log "GitHub Proxy Daemon started"
log "=========================================="

# 初始化：设置默认代理
log "Initializing with default proxy..."
CURRENT_PROXY="${PROXIES[0]}"
set_git_proxy "$CURRENT_PROXY"

while true; do
    # 检测当前代理是否可用
    if [ -n "$CURRENT_PROXY" ] && [ "$CURRENT_PROXY" != "direct" ]; then
        if test_proxy "$CURRENT_PROXY"; then
            # 当前代理可用，继续使用
            sleep 60
            continue
        else
            # 当前代理不可用
            log "⚠️  Current proxy unavailable: $CURRENT_PROXY"
        fi
    fi
    
    # 查找新的可用代理
    log "🔍 Searching for available proxy..."
    new_proxy=$(find_working_proxy)
    
    if [ "$new_proxy" != "$CURRENT_PROXY" ]; then
        log "⚡ Switching proxy: $CURRENT_PROXY -> $new_proxy"
        set_git_proxy "$new_proxy"
        CURRENT_PROXY="$new_proxy"
    fi
    
    sleep 60
done
