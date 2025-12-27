#!/bin/bash
#
# 使用 hf download 批量下载 ComfyUI 模型
#
# 依赖:
#   pip install huggingface_hub
#
# 使用方法:
#   ./download_models.sh models_20251225.json /path/to/target_dir
#   ./download_models.sh models_20251225.json /path/to/target_dir --use-mirror
#   ./download_models.sh models_20251225.json /path/to/target_dir --dirs vae loras
#
# 参数:
#   $1: models_*.json 文件路径
#   $2: 下载目标目录
#   --use-mirror: 使用国内镜像 (可选)
#   --dirs <目录...>: 只下载指定目录的模型 (可选)
#

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 参数检查
if [ $# -lt 2 ]; then
    echo -e "${RED}错误: 参数不足${NC}"
    echo ""
    echo "使用方法:"
    echo "  $0 <models_json> <target_dir> [选项]"
    echo ""
    echo "选项:"
    echo "  --use-mirror           使用国内镜像加速"
    echo "  --dirs <目录...>       只下载指定目录的模型"
    echo "  -h, --help            显示此帮助信息"
    echo ""
    echo "示例:"
    echo "  $0 models_20251225.json /root/models"
    echo "  $0 models_20251225.json /root/models --use-mirror"
    echo "  $0 models_20251225.json /root/models --dirs vae"
    echo "  $0 models_20251225.json /root/models --dirs vae loras unet"
    echo "  $0 models_20251225.json /root/models --use-mirror --dirs vae"
    echo ""
    exit 1
fi

MODELS_JSON="$1"
TARGET_DIR="$2"
shift 2

USE_MIRROR=false
FILTER_DIRS=()

# 解析可选参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --use-mirror)
            USE_MIRROR=true
            export HF_ENDPOINT="https://hf-mirror.com"
            shift
            ;;
        --dirs|-d)
            shift
            while [[ $# -gt 0 && ! "$1" =~ ^-- ]]; do
                FILTER_DIRS+=("$1")
                shift
            done
            ;;
        -h|--help)
            echo "使用方法: $0 <models_json> <target_dir> [选项]"
            echo ""
            echo "选项:"
            echo "  --use-mirror           使用国内镜像加速"
            echo "  --dirs <目录...>       只下载指定目录的模型"
            echo "  -h, --help            显示此帮助信息"
            echo ""
            echo "示例:"
            echo "  $0 models_20251225.json /root/models"
            echo "  $0 models_20251225.json /root/models --use-mirror"
            echo "  $0 models_20251225.json /root/models --dirs vae"
            echo "  $0 models_20251225.json /root/models --dirs vae loras unet --use-mirror"
            echo ""
            exit 0
            ;;
        *)
            echo -e "${RED}错误: 未知参数 $1${NC}"
            echo "运行 $0 --help 查看帮助"
            exit 1
            ;;
    esac
done

if [ "$USE_MIRROR" = true ]; then
    echo -e "${BLUE}✓ 使用 Hugging Face 镜像: $HF_ENDPOINT${NC}"
fi

# 检查文件是否存在
if [ ! -f "$MODELS_JSON" ]; then
    echo -e "${RED}错误: 文件不存在: $MODELS_JSON${NC}"
    exit 1
fi

# 检查 hf 命令
if ! command -v hf &> /dev/null; then
    echo -e "${RED}错误: 未找到 hf 命令${NC}"
    echo "请运行: pip install huggingface_hub"
    exit 1
fi

# 创建目标目录
mkdir -p "$TARGET_DIR"

echo "======================================"
echo "开始下载 ComfyUI 模型"
echo "======================================"
echo -e "${BLUE}模型配置: ${MODELS_JSON}${NC}"
echo -e "${BLUE}目标目录: ${TARGET_DIR}${NC}"
if [ ${#FILTER_DIRS[@]} -gt 0 ]; then
    echo -e "${BLUE}筛选目录: ${FILTER_DIRS[*]}${NC}"
fi
echo ""

# 统计变量
declare -a SUCCESS_MODELS
declare -a FAILED_MODELS
declare -a SKIPPED_MODELS
SUCCESS=0
FAILED=0
SKIPPED=0

# 解析 Hugging Face URL
parse_hf_url() {
    local url="$1"
    
    # 移除查询参数（如 ?download=true）
    url="${url%%\?*}"
    
    # 检查是否是 HF URL
    if [[ ! "$url" =~ ^https://huggingface\.co/ ]]; then
        echo ""
        return 1
    fi
    
    # 提取 repo_id, revision, file_path
    # 格式: https://huggingface.co/{repo_id}/resolve/{revision}/{file_path}
    if [[ "$url" =~ https://huggingface\.co/([^/]+/[^/]+)/(resolve|blob)/([^/]+)/(.+) ]]; then
        REPO_ID="${BASH_REMATCH[1]}"
        REVISION="${BASH_REMATCH[3]}"
        FILE_PATH="${BASH_REMATCH[4]}"
        echo "${REPO_ID}|${REVISION}|${FILE_PATH}"
        return 0
    fi
    
    echo ""
    return 1
}

# 下载单个模型
download_model() {
    local model_name="$1"
    local url="$2"
    local directory="$3"
    local target_path="$TARGET_DIR/$directory"
    
    # 创建目录
    mkdir -p "$target_path"
    
    # 检查文件是否已存在
    if [ -f "$target_path/$model_name" ]; then
        echo -e "  ${GREEN}✓ 已存在，跳过${NC}"
        SKIPPED=$((SKIPPED + 1))
        SKIPPED_MODELS+=("$model_name ($directory)")
        return 0
    fi
    
    # 检查是否有下载地址
    if [ -z "$url" ] || [ "$url" = "null" ]; then
        echo -e "  ${YELLOW}⚠ 没有下载地址，跳过${NC}"
        SKIPPED=$((SKIPPED + 1))
        SKIPPED_MODELS+=("$model_name ($directory) - 无下载地址")
        return 0
    fi
    
    # 解析 URL
    local parsed=$(parse_hf_url "$url")
    if [ -z "$parsed" ]; then
        echo -e "  ${YELLOW}⚠ 非 Hugging Face 链接，跳过${NC}"
        echo -e "  ${YELLOW}  URL: $url${NC}"
        SKIPPED=$((SKIPPED + 1))
        SKIPPED_MODELS+=("$model_name ($directory) - 非HF链接")
        return 0
    fi
    
    # 提取信息
    IFS='|' read -r REPO_ID REVISION FILE_PATH <<< "$parsed"
    
    echo -e "  ${BLUE}下载中...${NC}"
    echo -e "    Repo: $REPO_ID"
    echo -e "    File: $FILE_PATH"
    
    # 执行下载（最多重试3次）
    local max_retries=3
    local retry_delay=5
    
    for ((attempt=1; attempt<=max_retries; attempt++)); do
        if [ $attempt -gt 1 ]; then
            echo -e "  ${YELLOW}🔄 重试 $attempt/$max_retries...${NC}"
            sleep $retry_delay
        fi
        
        # 显示执行的命令
        if [ $attempt -eq 1 ]; then
            echo -e "  ${CYAN}执行命令:${NC}"
            echo -e "    ${CYAN}hf download \"$REPO_ID\" \"$FILE_PATH\" --local-dir \"$target_path\" --revision \"$REVISION\"${NC}"
        fi
        
        # 下载命令
        if hf download "$REPO_ID" "$FILE_PATH" \
            --local-dir "$target_path" \
            --revision "$REVISION" 2>&1; then
            
            # 检查文件是否在子目录中
            SOURCE_FILE="$target_path/$FILE_PATH"
            TARGET_FILE="$target_path/$model_name"
            
            if [ "$SOURCE_FILE" != "$TARGET_FILE" ] && [ -f "$SOURCE_FILE" ]; then
                mv "$SOURCE_FILE" "$TARGET_FILE" 2>/dev/null || true
                # 清理空目录
                rmdir "$(dirname "$SOURCE_FILE")" 2>/dev/null || true
            fi
            
            echo -e "  ${GREEN}✓ 下载完成${NC}"
            SUCCESS=$((SUCCESS + 1))
            SUCCESS_MODELS+=("$model_name ($directory)")
            return 0
        fi
    done
    
    # 所有重试都失败
    echo -e "  ${RED}✗ 下载失败（已重试 $max_retries 次）${NC}"
    FAILED=$((FAILED + 1))
    FAILED_MODELS+=("$model_name ($directory)")
    return 1
}

# 读取 JSON 并下载
echo "正在解析模型列表..."

# 获取可用目录列表
available_dirs=$(python3 -c "
import json
dirs = set()
with open('$MODELS_JSON', 'r', encoding='utf-8') as f:
    data = json.load(f)
    for info in data.values():
        dirs.add(info.get('directory', 'unknown'))
print(' '.join(sorted(dirs)))
")

echo -e "${BLUE}可用目录: $available_dirs${NC}"

# 验证筛选的目录是否有效
if [ ${#FILTER_DIRS[@]} -gt 0 ]; then
    for filter_dir in "${FILTER_DIRS[@]}"; do
        if [[ ! " $available_dirs " =~ " $filter_dir " ]]; then
            echo -e "${YELLOW}⚠️  警告: 目录 '$filter_dir' 在配置文件中不存在${NC}"
        fi
    done
fi

# 计算要下载的模型数量
if [ ${#FILTER_DIRS[@]} -gt 0 ]; then
    model_count=$(python3 -c "
import json
with open('$MODELS_JSON', 'r', encoding='utf-8') as f:
    data = json.load(f)
filter_dirs = set('${FILTER_DIRS[*]}'.split())
count = sum(1 for info in data.values() if info.get('directory', 'unknown') in filter_dirs)
print(count)
")
else
    model_count=$(python3 -c "import json; data=json.load(open('$MODELS_JSON')); print(len(data))")
fi

echo -e "${BLUE}要下载 $model_count 个模型${NC}"
echo ""

current=0
total_count=0

# 使用 Python 解析 JSON 并逐个下载
python3 -c "
import json
import sys

with open('$MODELS_JSON', 'r', encoding='utf-8') as f:
    data = json.load(f)

filter_dirs = set('${FILTER_DIRS[*]}'.split()) if '${FILTER_DIRS[*]}' else None

for model_name, info in data.items():
    url = info.get('url', '')
    directory = info.get('directory', 'unknown')
    
    # 如果指定了目录筛选，只输出匹配的模型
    if filter_dirs and directory not in filter_dirs:
        continue
    
    # 使用特殊分隔符
    sep = '###SEP###'
    print(f'{model_name}{sep}{url}{sep}{directory}')
" | while IFS= read -r line; do
    # 手动分割，避免空字段问题
    model_name=$(echo "$line" | awk -F'###SEP###' '{print $1}')
    url=$(echo "$line" | awk -F'###SEP###' '{print $2}')
    directory=$(echo "$line" | awk -F'###SEP###' '{print $3}')
    current=$((current + 1))
    echo "[$current/$model_count] $model_name"
    echo -e "  目录: ${BLUE}$directory${NC}"
    
    download_model "$model_name" "$url" "$directory"
    echo ""
done

# 显示总结
echo ""
echo "======================================"
echo "下载完成!"
echo "======================================"
echo -e "${GREEN}成功: $SUCCESS${NC}"
echo -e "${YELLOW}跳过: $SKIPPED${NC}"
echo -e "${RED}失败: $FAILED${NC}"
echo "总计: $((SUCCESS + SKIPPED + FAILED))"
echo "======================================"

# 显示成功的模型
if [ $SUCCESS -gt 0 ]; then
    echo ""
    echo -e "${GREEN}✓ 成功下载的模型:${NC}"
    for model in "${SUCCESS_MODELS[@]}"; do
        echo -e "  ${GREEN}✓${NC} $model"
    done
fi

# 显示失败的模型
if [ $FAILED -gt 0 ]; then
    echo ""
    echo -e "${RED}✗ 失败的模型（建议重新下载）:${NC}"
    for model in "${FAILED_MODELS[@]}"; do
        echo -e "  ${RED}✗${NC} $model"
    done
fi

# 显示跳过的模型
if [ $SKIPPED -gt 0 ] && [ ${#SKIPPED_MODELS[@]} -lt 20 ]; then
    echo ""
    echo -e "${YELLOW}⚠ 跳过的模型:${NC}"
    for model in "${SKIPPED_MODELS[@]}"; do
        echo -e "  ${YELLOW}⚠${NC} $model"
    done
fi

echo ""
echo "======================================"

# 如果有失败，返回非零退出码
if [ $FAILED -gt 0 ]; then
    exit 1
fi

exit 0

