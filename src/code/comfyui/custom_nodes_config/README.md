# ComfyUI 插件配置目录

本目录包含 ComfyUI 自定义插件的配置文件和管理脚本。

---

## 文件说明

| 文件 | 类型 | 用途 |
|------|------|------|
| `get_topn.py` | 脚本 | 从网络拉取最新数据，生成 Top N 插件列表 |
| `custom_nodes.json` | 配置 | 镜像内置核心插件列表（49 个） |
| `excluded_custom_nodes.json` | 配置 | 排除列表，记录不内置的插件及原因 |
| `custom_nodes_top100.json` | 数据 | 按 Stars 排序的 Top 100 插件列表 |

---

## custom_nodes.json — 镜像内置插件

镜像构建时安装的核心插件列表，数量精简，追求稳定性和启动速度。

**数据结构：**

```json
{
  "custom_nodes": [
    {
      "id": "comfyui-manager",
      "name": "ComfyUI-Manager",
      "repository": "https://github.com/ltdrdata/ComfyUI-Manager",
      "version": "3.37.1",
      "stars": 12368,
      "enabled": true,
      "description": "插件描述"
    }
  ]
}
```

**选择原则：**

- 核心必需、稳定性高、使用频率高
- 控制镜像体积（建议 5–20 个）
- 典型插件：ComfyUI-Manager、ControlNet Aux、AnimateDiff、Impact Pack

---

## excluded_custom_nodes.json — 排除列表

记录明确不内置的插件，`get_topn.py` 生成列表时会自动跳过这些插件。

每条记录包含 `reason` 字段，说明排除原因（import 失败、体积过大等）。

---

## get_topn.py — 生成 Top N 插件列表

从 ComfyUI Manager 官方 GitHub 实时下载插件数据，按 Stars 排序，过滤排除列表，生成候选列表供人工审核。

**数据来源：**

- Stars 数据：`https://raw.githubusercontent.com/Comfy-Org/ComfyUI-Manager/main/github-stats.json`
- 插件列表：`https://raw.githubusercontent.com/Comfy-Org/ComfyUI-Manager/main/custom-node-list.json`

### 使用方法

在 `src/code/comfyui` 目录下执行：

```bash
# 生成 Top 100 插件列表
make update-custom-nodes n=100

# 生成 Top 200 插件列表
make update-custom-nodes n=200
```

或直接运行脚本（在 `custom_nodes_config/` 目录下）：

```bash
# 生成 Top 100
python3 get_topn.py --top 100

# 指定输出目录
python3 get_topn.py --top 50 --output-dir ./
```

### 输出文件

生成文件保存在 `custom_nodes_config/` 目录，命名格式：

```
custom_nodes_top_N_YYYY-MM-DD.json
```

**文件结构：**

```json
{
  "metadata": {
    "generated_at": "2026-03-05",
    "top_n": 100,
    "total": 100,
    "excluded_count": 5
  },
  "custom_nodes": [
    {
      "id": "comfyui-manager",
      "name": "ComfyUI-Manager",
      "repository": "https://github.com/ltdrdata/ComfyUI-Manager",
      "version": "v3.37.1",
      "stars": 13769,
      "enabled": true,
      "description": "..."
    }
  ]
}
```

### 典型工作流

```bash
# 1. 生成候选列表（会自动排除 excluded_custom_nodes.json 中的插件）
make update-custom-nodes n=150

# 2. 人工审核生成的文件，确认内容
# 3. 确认后重命名为正式配置文件
cp custom_nodes_config/custom_nodes_top_150_2026-03-05.json \
   custom_nodes_config/custom_nodes.json
```

### 注意事项

- 脚本会调用 GitHub API 获取每个插件的版本信息，建议配置 `GITHUB_TOKEN` 或通过 `gh` CLI 登录以避免限速
- 生成的文件仅供人工审核，确认后才应替换 `custom_nodes.json`

---

## 相关设计文档

详细的系统插件架构设计请参考：[系统插件设计文档](../../../system-plugins-design.md)
