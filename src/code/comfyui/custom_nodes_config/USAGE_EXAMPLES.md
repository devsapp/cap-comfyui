# ComfyUI 插件管理使用示例

本文档提供 ComfyUI 插件管理相关命令的详细使用示例。

---

## 📋 目录

- [生成 Top N 插件列表](#生成-top-n-插件列表)
- [常见使用场景](#常见使用场景)
- [文件说明](#文件说明)
- [故障排除](#故障排除)

---

## 生成 Top N 插件列表

### 基本命令

在 `src/code/comfyui` 目录下执行：

```bash
# 查看所有可用命令
make help

# 生成 Top 50 插件列表
make update-custom-nodes n=50

# 生成 Top 100 插件列表
make update-custom-nodes n=100

# 生成 Top 200 插件列表
make update-custom-nodes n=200

# 生成 Top 500 插件列表
make update-custom-nodes n=500

# 生成 Top 1000 插件列表
make update-custom-nodes n=1000
```

### 命令输出示例

```bash
$ make update-custom-nodes n=50

🚀 开始获取 Top 50 ComfyUI 插件...
📂 从文件加载插件列表: .../comfyui_manager_official_list.json
✅ 成功从 node_packs 格式转换 4209 个插件
📊 源文件包含: 4209 个插件
📊 其中有 stars 数据的: 3531 个插件
✅ 成功保存 50 个插件到: .../custom_nodes_top50_20260302.json

============================================================
📊 Top N 插件统计信息
============================================================
排名 #1: ComfyUI-Manager (13,769 stars)
排名 #10: FastVideo (3,112 stars)
排名 #50: Dynamic Thresholding (1,234 stars)

✅ 任务完成！
✅ 插件列表更新完成！
```

### 生成的文件位置

```
src/code/comfyui/custom_nodes_config/
└── custom_nodes_top50_20260302.json  ← 生成的文件
```

---

## 常见使用场景

### 场景 1: 为新环境准备核心插件列表

```bash
# 1. 生成最热门的 30 个插件（快速启动环境）
make update-custom-nodes n=30

# 2. 查看生成的文件
ls -lh custom_nodes_config/custom_nodes_top30_*.json

# 3. 将文件重命名为标准名称（可选）
cp custom_nodes_config/custom_nodes_top30_*.json \
   custom_nodes_config/custom_nodes_core.json
```

### 场景 2: 准备不同规模的推荐插件列表

```bash
# 小型环境：Top 20
make update-custom-nodes n=20

# 中型环境：Top 50
make update-custom-nodes n=50

# 大型环境：Top 100
make update-custom-nodes n=100
```

### 场景 3: 定期更新插件列表

```bash
#!/bin/bash
# update_plugins_weekly.sh

# 进入 ComfyUI 目录
cd /path/to/cap-comfyui/src/code/comfyui

# 生成本周的 Top 100 插件列表
make update-custom-nodes n=100

# 备份到特定目录
WEEK=$(date +%Y-W%V)
cp custom_nodes_config/custom_nodes_top100_*.json \
   backups/plugins_top100_${WEEK}.json

echo "✅ 本周插件列表已更新：${WEEK}"
```

### 场景 4: 对比不同时期的热门插件

```bash
# 生成当前的 Top 50
make update-custom-nodes n=50

# 对比两个时期的插件列表
jq -r '.custom_nodes[].name' custom_nodes_config/custom_nodes_top50_20260302.json > current.txt
jq -r '.custom_nodes[].name' custom_nodes_config/custom_nodes_top50_20260201.json > previous.txt

# 找出新增的插件
comm -13 <(sort previous.txt) <(sort current.txt)

# 找出移除的插件
comm -23 <(sort previous.txt) <(sort current.txt)
```

---

## 文件说明

### 生成文件的命名规则

```
custom_nodes_topN_YYYYMMDD.json
                 ↑        ↑
                 |        └─ 生成日期（年月日）
                 └────────── Top N 数量
```

**示例：**
- `custom_nodes_top50_20260302.json` - 2026年3月2日生成的 Top 50 列表
- `custom_nodes_top100_20260315.json` - 2026年3月15日生成的 Top 100 列表

### 生成文件的结构

```json
{
  "metadata": {
    "description": "Top 50 ComfyUI custom nodes sorted by GitHub stars",
    "total_plugins": 50,
    "source": "custom_nodes_top100.json",
    "created_at": "2026-03-02 11:58:30",
    "note": "If you need more than 103 plugins with stars data, please use GitHub API to fetch."
  },
  "custom_nodes": [
    {
      "id": "comfyui-manager",
      "name": "ComfyUI-Manager",
      "repository": "https://github.com/ltdrdata/ComfyUI-Manager",
      "version": "3.37.1",
      "stars": 12368,
      "enabled": true,
      "description": "ComfyUI-Manager provides features..."
    }
    // ... 更多插件
  ]
}
```

### 元数据字段说明

| 字段 | 说明 | 示例 |
|------|------|------|
| `description` | 列表描述 | "Top 50 ComfyUI custom nodes..." |
| `total_plugins` | 实际包含的插件数量 | 50 |
| `source` | 数据来源文件 | "custom_nodes_top100.json" |
| `created_at` | 创建时间 | "2026-03-02 11:58:30" |
| `note` | 注意事项 | "If you need more than 103..." |

---

## 高级用法

### 直接使用 Python 脚本

如果需要更灵活的控制，可以直接使用 Python 脚本：

```bash
cd custom_nodes_config

# 自定义输出文件名
python3 update_topn_plugins.py 50 --output my_custom_top50.json

# 从不同的源文件获取（旧格式）
python3 update_topn_plugins.py 30 --source custom_nodes_top100.json

# 查看完整帮助
python3 update_topn_plugins.py --help
```

### 脚本帮助信息

```
usage: update_topn_plugins.py [-h] [--output OUTPUT] [--source SOURCE] n

获取 ComfyUI Top N 插件列表

positional arguments:
  n                Top N 数量（如: 50, 100, 200）

optional arguments:
  -h, --help       show this help message and exit
  --output OUTPUT  输出文件名（默认: custom_nodes_topn_YYYYMMDD.json）
  --source SOURCE  源数据文件（默认: custom_nodes_top100.json）

示例：
  update_topn_plugins.py 50                                    # 获取 top 50，保存到默认文件
  update_topn_plugins.py 200 --output top200.json             # 获取 top 200，自定义文件名
  update_topn_plugins.py 100 --source custom_nodes.json       # 从指定源文件获取
```

---

## 故障排除

### 问题 1: 命令找不到 (make: command not found)

**解决方案：** 确保在正确的目录执行命令

```bash
cd /path/to/cap-comfyui/src/code/comfyui
make update-custom-nodes n=50
```

### 问题 2: Python 版本错误

**解决方案：** 确保 Python 3.6+ 已安装

```bash
# 检查 Python 版本
python3 --version

# 如果版本过低，请升级 Python
```

### 问题 3: 请求的插件数量超过可用数量

**输出示例：**
```
⚠️  警告: 请求 top 5000，但只找到 3531 个有 stars 数据的插件
💡 提示: 当前源文件最多支持 3531 个插件
```

**解决方案：**
将请求的数量降低到 3531 以内（当前官方列表包含 3531 个有效 stars 数据的插件）

### 问题 4: 文件权限错误

**解决方案：** 确保脚本有执行权限

```bash
chmod +x custom_nodes_config/update_topn_plugins.py
```

### 问题 5: JSON 文件无法解析

**解决方案：** 验证源文件是否损坏

```bash
# 验证 JSON 格式
jq . custom_nodes_config/custom_nodes_top100.json

# 如果损坏，重新下载或恢复备份
```

---

## 批处理示例

### 一次性生成多个规格的插件列表

```bash
#!/bin/bash
# generate_multiple_lists.sh

cd /path/to/cap-comfyui/src/code/comfyui

echo "🚀 开始生成多个插件列表..."

# 生成不同规格的列表
for n in 20 30 50 100; do
    echo ""
    echo "生成 Top ${n} 列表..."
    make update-custom-nodes n=${n}
done

echo ""
echo "✅ 所有列表生成完成！"
echo ""
echo "生成的文件："
ls -lh custom_nodes_config/custom_nodes_top*_$(date +%Y%m%d).json
```

---

## 相关文件

- **Makefile** - 包含 `update-custom-nodes` 命令定义
- **update_topn_plugins.py** - Python 脚本实现
- **README.md** - 完整的目录说明文档
- **custom_nodes_top100.json** - 数据源文件（103 个插件）

---

## 下一步

- 如需更多插件的 stars 数据，考虑实现 GitHub API 集成
- 定期更新 `custom_nodes_top100.json` 以获取最新数据
- 根据业务需求选择合适的 Top N 数量

---

**维护者：** 云平台架构团队  
**最后更新：** 2026-03-02  
**相关文档：** [README.md](README.md) | [COMPARISON_ANALYSIS.md](COMPARISON_ANALYSIS.md)
