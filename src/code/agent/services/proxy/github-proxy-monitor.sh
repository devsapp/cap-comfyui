#!/bin/bash

# GitHub 代理监控守护进程
# 功能：定期检测代理可用性，自动切换到可用的代理
# 工作原理：
#   1. 每 60 秒检测当前代理是否可用
#   2. 如果不可用，遍历备用代理列表查找可用的
#   3. 更新 ~/.gitconfig 中的代理配置

# ==================== 配置 ====================

# 代理列表（按优先级排序）
PROXIES=(
    # 测试 github
    "https://cap-accor-proxy-qkqnjxeail.ap-southeast-1.fcapp.run/https://github.com/"
    "https://cap-accor-proxy-qkqnjxeail.cn-hongkong.fcapp.run/https://github.com/"
    "https://gh.llkk.cc/https://github.com/"
    "https://ghproxy.com/https://github.com/"
    "https://ghfast.top/https://github.com/"
)

# 日志文件
LOG_FILE="/tmp/github_proxy_monitor.log"

# Git 配置文件
GITCONFIG="$HOME/.gitconfig"

# 检测间隔（秒）
CHECK_INTERVAL=60

# 当前使用的代理
CURRENT_PROXY=""

# ==================== 工具函数 ====================

log() {
    # 只写入日志文件，不输出到 stdout（避免被命令替换捕获）
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
}

# 测试代理是否可用
test_proxy() {
    local proxy_url="$1"
    
    # 使用 ComfyUI 仓库进行测试（完整的代理 URL）
    local test_repo="${proxy_url}comfyanonymous/ComfyUI.git"
    
    log "🔍 Testing proxy: $proxy_url"
    log "   Testing repo: $test_repo"
    log "   Command: GIT_TERMINAL_PROMPT=0 GIT_CONFIG_GLOBAL=/dev/null git ls-remote --exit-code '$test_repo' HEAD"
    
    # 使用 git ls-remote 测试（真实的 git 命令）
    # GIT_TERMINAL_PROMPT=0: 禁用交互式提示
    # GIT_CONFIG_GLOBAL=/dev/null: 禁用全局配置，避免干扰
    # timeout 10: 10秒超时（git 操作比 curl 慢）
    if timeout 10 env GIT_TERMINAL_PROMPT=0 GIT_CONFIG_GLOBAL=/dev/null git ls-remote --exit-code "$test_repo" HEAD > /dev/null 2>&1; then
        log "✅ Proxy test passed: $proxy_url"
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
            echo "$proxy"
            return 0
        fi
    done
    log "⚠️  No working proxy found"
    return 1
}

# 获取当前 gitconfig 中配置的代理
get_current_proxy() {
    # 读取 gitconfig 中的第一个 url.*.insteadOf 配置
    # 匹配 [url "代理URL"] 格式，提取引号中的 URL
    # 注意：这里的 sed 只是解析文本（从管道读取），不会修改 .gitconfig 文件
    local proxy=$(grep -A 1 '^\[url ' "$GITCONFIG" 2>/dev/null | head -1 | sed 's/\[url "\(.*\)"\]/\1/')
    
    # Debug 日志
    log "🔍 [DEBUG] get_current_proxy() returned: ${proxy:-<empty>}"
    
    echo "$proxy"
}

# 更新 gitconfig 中的代理配置
update_gitconfig_proxy() {
    local new_proxy="$1"
    
    log "📝 Updating gitconfig with new proxy: $new_proxy"
    
    # 备份当前配置
    cp "$GITCONFIG" "${GITCONFIG}.bak"
    
    # 删除所有现有的 [url ...] 配置段
    # sed 语法：/pattern1/,/pattern2/d 表示删除从 pattern1 到 pattern2 之间的所有行
    # /^\[url /  匹配以 [url 开头的行（配置段开始）
    # /^$/      匹配空行（配置段结束）
    # d         删除操作
    # -i.tmp    直接修改文件并创建 .tmp 备份
    sed -i.tmp '/^\[url /,/^$/d' "$GITCONFIG"
    
    # 添加新的代理配置
    cat >> "$GITCONFIG" << EOF

# GitHub 代理配置（由 github-proxy-monitor 自动更新）
[url "$new_proxy"]
	insteadOf = https://github.com/
	insteadOf = http://github.com/
	insteadOf = git@github.com:
EOF
    
    # 清理临时文件
    rm -f "${GITCONFIG}.tmp"
    
    log "✅ Gitconfig updated successfully"
}

# ==================== 主循环 ====================

log "=========================================="
log "GitHub Proxy Monitor started"
log "=========================================="

# 初始化：读取当前配置的代理
CURRENT_PROXY=$(get_current_proxy)
if [ -n "$CURRENT_PROXY" ]; then
    log "📋 Current proxy from gitconfig: $CURRENT_PROXY"
else
    log "⚠️  No proxy configured, will set default proxy"
    CURRENT_PROXY="${PROXIES[0]}"
    update_gitconfig_proxy "$CURRENT_PROXY"
fi

# 主监控循环
while true; do
    log "🔍 Checking current proxy: $CURRENT_PROXY"
    
    if test_proxy "$CURRENT_PROXY"; then
        log "✅ Current proxy is working"
    else
        log "❌ Current proxy failed, searching for alternative..."
        
        new_proxy=$(find_working_proxy)
        log "🔍 [DEBUG] find_working_proxy() returned: ${new_proxy:-<empty>}"
        
        if [ -n "$new_proxy" ]; then
            log "⚡ Found working proxy: $new_proxy"
            update_gitconfig_proxy "$new_proxy"
            CURRENT_PROXY="$new_proxy"
            log "🔍 [DEBUG] CURRENT_PROXY updated to: $CURRENT_PROXY"
        else
            log "⚠️  No working proxy found! Will retry in $CHECK_INTERVAL seconds"
        fi
    fi
    
    sleep $CHECK_INTERVAL
done

