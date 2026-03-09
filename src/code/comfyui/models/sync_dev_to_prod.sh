#!/bin/bash
#
# sync_dev_to_prod.sh - 对比 dev/prod 挂载目录，将差异模型从 dev OSS 同步到 prod OSS
#
# 依赖:
#   ossutil (已配置 AK/SK)
#   python3
#
# 使用方法:
#   ./sync_dev_to_prod.sh                  # 生成 diff JSON 并同步到 prod
#   ./sync_dev_to_prod.sh --diff-only      # 只生成 diff JSON，不执行同步
#   ./sync_dev_to_prod.sh --dry-run        # 打印 ossutil 命令但不实际执行
#
# 环境变量（可覆盖默认值）:
#   DEV_MOUNT       dev OSS 挂载目录   (默认 /mnt/funart-dev/models)
#   PROD_MOUNT      prod OSS 挂载目录  (默认 /mnt/funart-prod/models)
#   DEV_OSS_BUCKET  dev OSS bucket    (默认 dipper-cache-cn-hangzhou-dev)
#   PROD_OSS_BUCKET prod OSS bucket   (默认 dipper-cache-cn-hangzhou)
#   OUTPUT_JSON     diff JSON 输出路径  (默认 diff_YYYYMMDD.json，放在脚本同目录)
#

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 脚本所在目录，用于默认输出路径
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 可通过环境变量覆盖的配置
DEV_MOUNT="${DEV_MOUNT:-/mnt/funart-dev/models}"
PROD_MOUNT="${PROD_MOUNT:-/mnt/funart-prod/models}"
DEV_OSS_BUCKET="${DEV_OSS_BUCKET:-dipper-cache-cn-hangzhou-dev}"
PROD_OSS_BUCKET="${PROD_OSS_BUCKET:-dipper-cache-cn-hangzhou}"
OUTPUT_JSON="${OUTPUT_JSON:-$SCRIPT_DIR/diff_$(date +%Y%m%d).json}"

# 固定路径前缀（不对外暴露）
DEV_OSS_PREFIX="funart/models"
PROD_OSS_PREFIX="function-art/comfyui/models"

# 参数解析
DIFF_ONLY=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --diff-only)
            DIFF_ONLY=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            echo "使用方法: $0 [选项]"
            echo ""
            echo "选项:"
            echo "  --diff-only  只生成 diff JSON，不执行 OSS 同步"
            echo "  --dry-run    打印 ossutil 命令，不实际执行"
            echo "  -h, --help   显示此帮助信息"
            echo ""
            echo "环境变量:"
            echo "  DEV_MOUNT       dev 挂载目录  (默认: /mnt/funart-dev/models)"
            echo "  PROD_MOUNT      prod 挂载目录 (默认: /mnt/funart-prod/models)"
            echo "  DEV_OSS_BUCKET  dev bucket   (默认: dipper-cache-cn-hangzhou-dev)"
            echo "  PROD_OSS_BUCKET prod bucket  (默认: dipper-cache-cn-hangzhou)"
            echo "  OUTPUT_JSON     输出路径      (默认: diff_YYYYMMDD.json)"
            exit 0
            ;;
        *)
            echo -e "${RED}错误: 未知参数 $1${NC}"
            echo "运行 $0 --help 查看帮助"
            exit 1
            ;;
    esac
done

echo "======================================"
echo "Dev/Prod 模型差异对比 & 同步"
echo "======================================"
echo -e "${BLUE}Dev  目录:  $DEV_MOUNT${NC}"
echo -e "${BLUE}Prod 目录:  $PROD_MOUNT${NC}"
echo -e "${BLUE}输出 JSON:  $OUTPUT_JSON${NC}"
echo ""

# ──────────────────────────────────────────
# 步骤 1: 扫描目录差异，生成 diff JSON
# ──────────────────────────────────────────
echo -e "${BLUE}[1/2] 扫描目录差异...${NC}"

if [ ! -d "$DEV_MOUNT" ]; then
    echo -e "${RED}错误: dev 挂载目录不存在: $DEV_MOUNT${NC}"
    exit 1
fi

if [ ! -d "$PROD_MOUNT" ]; then
    echo -e "${YELLOW}警告: prod 挂载目录不存在: $PROD_MOUNT（将视为空目录）${NC}"
fi

python3 - <<PYEOF
import os
import json
import sys

dev_mount  = "${DEV_MOUNT}"
prod_mount = "${PROD_MOUNT}"
output_json = "${OUTPUT_JSON}"

diff = {}
total_dev = 0
total_missing = 0

for root, dirs, files in os.walk(dev_mount):
    # 跳过隐藏目录
    dirs[:] = sorted(d for d in dirs if not d.startswith('.'))

    for filename in sorted(files):
        if filename.startswith('.'):
            continue

        total_dev += 1
        rel_dir = os.path.relpath(root, dev_mount)
        prod_path = os.path.join(prod_mount, rel_dir, filename)

        if not os.path.exists(prod_path):
            total_missing += 1
            diff[filename] = {"directory": rel_dir}
            print(f"  缺失: {rel_dir}/{filename}")

with open(output_json, 'w', encoding='utf-8') as f:
    json.dump(diff, f, indent=4, ensure_ascii=False)

print(f"\nDev 总文件: {total_dev} 个")
print(f"需要同步:   {total_missing} 个")
print(f"已保存到:   {output_json}")
PYEOF

# 读取 diff 数量
diff_count=$(python3 -c "import json; data=json.load(open('${OUTPUT_JSON}')); print(len(data))")

if [ "$diff_count" -eq 0 ]; then
    echo -e "\n${GREEN}✓ dev 和 prod 完全一致，无需同步${NC}"
    exit 0
fi

echo -e "\n${YELLOW}需要同步 $diff_count 个模型到 prod${NC}"

if [ "$DIFF_ONLY" = true ]; then
    echo -e "${BLUE}(--diff-only 模式，跳过同步步骤)${NC}"
    exit 0
fi

# ──────────────────────────────────────────
# 步骤 2: 使用 ossutil 同步差异模型到 prod
# ──────────────────────────────────────────
echo ""
echo -e "${BLUE}[2/2] 同步模型到 Prod OSS...${NC}"
echo -e "  Dev  OSS: oss://${DEV_OSS_BUCKET}/${DEV_OSS_PREFIX}/"
echo -e "  Prod OSS: oss://${PROD_OSS_BUCKET}/${PROD_OSS_PREFIX}/"
echo ""

if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}[Dry Run] 将执行以下 ossutil 命令:${NC}"
fi

# 检查 ossutil
if [ "$DRY_RUN" = false ] && ! command -v ossutil &>/dev/null; then
    echo -e "${RED}错误: 未找到 ossutil 命令${NC}"
    echo "安装: sudo -v ; curl https://gosspublic.alicdn.com/ossutil/install.sh | sudo bash"
    exit 1
fi

SUCCESS=0
FAILED=0
FAILED_MODELS=()

# 使用进程替换避免子 shell 导致计数器失效
while IFS='###SEP###' read -r filename directory; do
    src="oss://${DEV_OSS_BUCKET}/${DEV_OSS_PREFIX}/${directory}/${filename}"
    dst="oss://${PROD_OSS_BUCKET}/${PROD_OSS_PREFIX}/${directory}/${filename}"

    if [ "$DRY_RUN" = true ]; then
        echo -e "  ${BLUE}ossutil cp --ignore-existing \"$src\" \"$dst\"${NC}"
    else
        echo -n "  同步 $directory/$filename ... "
        if ossutil cp --ignore-existing "$src" "$dst" 2>&1 | tail -1; then
            echo -e "  ${GREEN}✓ 完成${NC}"
            SUCCESS=$((SUCCESS + 1))
        else
            echo -e "  ${RED}✗ 失败${NC}"
            FAILED=$((FAILED + 1))
            FAILED_MODELS+=("$directory/$filename")
        fi
    fi
done < <(python3 -c "
import json
with open('${OUTPUT_JSON}', 'r') as f:
    data = json.load(f)
for filename, info in data.items():
    directory = info.get('directory', 'unknown')
    print(f'{filename}###SEP###{directory}')
")

if [ "$DRY_RUN" = false ]; then
    echo ""
    echo "======================================"
    echo -e "${GREEN}成功: $SUCCESS${NC}"
    echo -e "${RED}失败: $FAILED${NC}"
    echo "======================================"

    if [ "${#FAILED_MODELS[@]}" -gt 0 ]; then
        echo ""
        echo -e "${RED}以下模型同步失败:${NC}"
        for m in "${FAILED_MODELS[@]}"; do
            echo -e "  ${RED}✗${NC} $m"
        done
        exit 1
    fi
fi

exit 0
