#!/bin/bash

# --- 变量定义 ---
MNT_DIR=${MODEL_ASSET_DIR:-${MNT_DIR:-"/mnt/auto"}}
SOURCE_DIR="${MNT_DIR}/output/serverless_api"
HISTORY_DIR="${MNT_DIR}/output/serverless_api_archived"
KEEP_TOTAL=500


# 1. 准备目录
mkdir -p "$SOURCE_DIR"
mkdir -p "$HISTORY_DIR"

# 2. 【滑动窗口搬运】只把 SOURCE 目录中超出 500 名开外的旧文件移走
# 这样保证 SOURCE 目录始终有且仅有最新的 500 个
cd "$SOURCE_DIR" || exit

# 统计文件数量（先检查，避免不必要的操作）
FILE_COUNT=$(find . -maxdepth 1 -type f | wc -l)

# 只有当文件数量超过 KEEP_TOTAL 时才执行移动操作
if [ "$FILE_COUNT" -gt "$KEEP_TOTAL" ]; then
    # 优化：使用 mv -t 批量移动，比 xargs -I {} 逐个移动更高效
    # ls -t: 按修改时间排序（最新的在前）
    # tail -n +$((KEEP_TOTAL + 1)): 取第 501 个及之后的文件（旧文件）
    # xargs: 批量传递给 mv -t，一次性移动多个文件
    ls -t | tail -n +$((KEEP_TOTAL + 1)) | xargs -r mv -t "$HISTORY_DIR/" 2>/dev/null
    
    MOVED_COUNT=$((FILE_COUNT - KEEP_TOTAL))
    echo "[INFO] Moved $MOVED_COUNT old file(s) to history (kept $KEEP_TOTAL newest files)"
else
    echo "[INFO] File count ($FILE_COUNT) <= KEEP_TOTAL ($KEEP_TOTAL), no files to move"
fi

# 3. 【History 清理】（可选）
# 如果你希望 history 目录也不要无限增加，可以再对 history 做一次裁减
# 例如 history 只留 2000 个，或者不限制（根据你说的“无所谓”来定）
# 若不需要限制 history 总量，下面这段可以删掉
# cd "$HISTORY_DIR" && ls -t | tail -n +2001 | xargs -r rm -f -- 2>/dev/null

exit 0