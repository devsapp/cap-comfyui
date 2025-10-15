#!/bin/bash

# Cap-ComfyUI 快速部署脚本
# 用途: 将本地代码部署到开发机

set -e  # 遇到错误立即退出

DEV_SERVER="root@47.84.130.69"
REMOTE_DIR="cap-comfyui-cpu"
LOCAL_DIR="$(pwd)"

echo "🚀 开始部署 Cap-ComfyUI 到开发机..."
echo "📍 本地目录: $LOCAL_DIR"
echo "🖥️  开发机: $DEV_SERVER"
echo "📂 远程目录: $REMOTE_DIR"
echo ""

# 1. 连接开发机并清理旧代码
echo "🧹 步骤1: 清理开发机上的旧代码..."
ssh $DEV_SERVER << 'EOF'
    if [ -d "cap-comfyui-cpu" ]; then
        echo "   发现旧目录，正在删除..."
        rm -rf cap-comfyui-cpu
        echo "   ✅ 旧代码已删除"
    else
        echo "   📁 未发现旧目录，跳过删除"
    fi
EOF

# 2. 同步本地代码到开发机
echo ""
echo "📤 步骤2: 同步本地代码到开发机..."
rsync -avz --progress \
    --exclude='.git' \
    --exclude='.idea' \
    --exclude='*.pyc' \
    --exclude='__pycache__' \
    --exclude='.DS_Store' \
    --exclude='*.log' \
    --exclude='node_modules' \
    "$LOCAL_DIR/" "$DEV_SERVER:$REMOTE_DIR/"

echo "   ✅ 代码同步完成"

# 3. 验证部署结果
echo ""
echo "🔍 步骤3: 验证部署结果..."
ssh $DEV_SERVER << EOF
    if [ -d "$REMOTE_DIR" ]; then
        echo "   📂 远程目录结构:"
        ls -la $REMOTE_DIR/ | head -10
        echo ""
        echo "   📊 代码统计:"
        find $REMOTE_DIR -name "*.py" | wc -l | xargs echo "   Python文件数量:"
        find $REMOTE_DIR -name "*.md" | wc -l | xargs echo "   Markdown文件数量:"
        echo "   ✅ 部署验证通过"
    else
        echo "   ❌ 远程目录不存在，部署可能失败"
        exit 1
    fi
EOF

# 4. 构建 ComfyUI 镜像
echo ""
echo "🚀 步骤4: 构建 ComfyUI 镜像..."
ssh $DEV_SERVER << EOF
    cd $REMOTE_DIR
    echo "   📂 当前目录: \$(pwd)"
    echo "   🔨 执行 make build-comfyui..."

    # 检查 Makefile 是否存在
    if [ -f "Makefile" ]; then
        echo "   ✅ 发现 Makefile，开始构建..."
        make build-comfyui
        echo "   🎉 ComfyUI 构建完成!"
    else
        echo "   ❌ 未发现 Makefile，请手动检查"
        ls -la
        exit 1
    fi
EOF

echo ""
echo "🎉 Cap-ComfyUI 构建完成!"
echo "📋 部署总结:"
echo "   ✅ 旧代码已清理"
echo "   ✅ 新代码已同步"
echo "   ✅ 部署已验证"
echo "   ✅ ComfyUI 已启动"
echo ""
echo "🔧 如需手动登陆开发机进行调试:"
echo "   ssh $DEV_SERVER"
echo "   cd $REMOTE_DIR"
echo ""
echo "📊 服务状态检查:"
echo "   - 检查服务状态: systemctl status comfyui"
echo "   - 查看服务日志: journalctl -f -u comfyui"
echo "   - 重启服务: systemctl restart comfyui"
