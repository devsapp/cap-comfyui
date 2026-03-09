# ComfyUI 插件配置目录

本目录包含 ComfyUI 自定义插件的配置和管理文件。

## 文件说明

### 1. comfyui_manager_official_list.json (2.1MB, 4236个插件)

**来源：** ComfyUI Manager 官方维护列表  
**更新地址：** https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main/custom-node-list.json  
**更新时间：** 2026-03-02

**用途：** ComfyUI Manager 官方维护的完整插件注册表，包含所有已发布的社区插件。

**数据结构：**
```json
{
  "custom_nodes": [
    {
      "author": "作者名称",
      "title": "插件标题",
      "id": "插件唯一标识",
      "reference": "GitHub 仓库地址",
      "files": ["安装文件列表"],
      "install_type": "git-clone | copy | unzip",
      "description": "插件描述",
      "nodename_pattern": "节点名称匹配模式(可选)",
      "preemptions": ["前置依赖(可选)"]
    }
  ]
}
```

**统计信息：**
- 总插件数：4236 个
- git-clone 安装：4195 个 (99.0%)
- copy 安装：37 个
- unzip 安装：3 个
- 最活跃作者 Top 5：
  - smthemex (58个插件)
  - AIFSH (44个插件)
  - kijai (41个插件)
  - ShmuelRonen (39个插件)
  - Yuan-ManX (32个插件)

---

### 2. custom_nodes_top100.json (44KB, 103个插件)

**来源：** 按 GitHub Stars 排序的热门插件精选列表  
**用途：** 用于系统内置推荐插件，按受欢迎程度筛选。

**数据结构：**
```json
{
  "custom_nodes": [
    {
      "id": "插件唯一标识",
      "name": "插件名称",
      "repository": "GitHub 仓库地址",
      "version": "版本号/commit hash",
      "stars": 12368,
      "enabled": true,
      "description": "插件描述"
    }
  ]
}
```

**特点：**
- 包含 GitHub Stars 数据
- 支持启用/禁用控制 (enabled 字段)
- 锁定版本号 (version 字段)
- 适用于生产环境部署

---

### 3. custom_nodes.json (19KB, 49个插件)

**来源：** 核心必需插件精选列表  
**用途：** 用于系统内置核心插件，数量更少、更精简。

**数据结构：** 与 `custom_nodes_top100.json` 相同

**特点：**
- 更精简的核心插件集合
- 适合镜像内置（控制镜像体积）
- 包含必需的管理器和常用工具

---

### 4. install_custom_nodes.py (3.2KB)

**用途：** 在 Dockerfile 构建阶段安装自定义插件依赖的脚本

**功能：**
- 复用 Agent 的 `PIPInstaller` 健壮安装逻辑
- 自动扫描插件目录并安装 requirements.txt 依赖
- 执行插件的 install.py 安装脚本
- 完整的错误处理和进度报告
- 失败时不中断构建，只输出警告

**使用方法：**
```dockerfile
# 在 Dockerfile 中
COPY custom_nodes_config/install_custom_nodes.py /root/
RUN cd /root/built-in/custom_nodes && \
    python3 /root/install_custom_nodes.py
```

---

## 文件对比

| 文件 | 插件数量 | 包含 Stars | 版本锁定 | 主要用途 |
|------|---------|-----------|---------|---------|
| comfyui_manager_official_list.json | 4236 | ❌ | ❌ | 官方完整注册表 |
| custom_nodes_top100.json | 103 | ✅ | ✅ | 推荐插件（OSS/共享存储） |
| custom_nodes.json | 49 | ✅ | ✅ | 核心插件（镜像内置） |

---

## 插件选择策略

### 镜像内置插件 (custom_nodes.json)

**原则：** 核心必需、稳定性高、使用频率高

**建议数量：** 5-20 个

**示例：**
- ✅ ComfyUI-Manager (必需)
- ✅ 自研插件 (FunArt-ComfyUI-Multi-User)
- ✅ ControlNet Aux (核心功能)
- ✅ AnimateDiff (视频生成)
- ✅ Impact Pack (图像增强)

**优点：**
- 启动快（本地磁盘）
- 零网络延迟
- 版本可控

**缺点：**
- 增加镜像体积
- 更新需要重新构建镜像

---

### OSS/共享存储插件 (custom_nodes_top100.json)

**原则：** 推荐使用、更新频繁、体积较大

**建议数量：** 50-100 个

**优点：**
- 镜像轻量
- 更新灵活
- 所有实例共享

**缺点：**
- 需要网络挂载
- 可能有 I/O 性能影响

---

### 用户自定义插件

**位置：** `/mnt/auto/custom_nodes/` (NAS 持久化)

**特点：**
- 用户完全自主安装/更新/删除
- 优先级最高（覆盖系统插件）
- 持久化存储

---

## 更新官方插件列表

```bash
# 下载最新的官方插件列表
curl -s "https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main/custom-node-list.json" \
  -o src/code/comfyui/custom_nodes_config/comfyui_manager_official_list.json

# 验证文件
jq '.custom_nodes | length' src/code/comfyui/custom_nodes_config/comfyui_manager_official_list.json
```

---

## 生成 Top N 插件列表

使用 Makefile 命令快速生成指定数量的热门插件列表：

### 基本用法

```bash
# 在 src/code/comfyui 目录下执行

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

### 输出文件

生成的文件会保存在 `custom_nodes_config/` 目录下，文件名格式为：
```
custom_nodes_topN_YYYYMMDD.json
```

例如：
- `custom_nodes_top50_20260302.json` - 2026年3月2日生成的 Top 50 列表
- `custom_nodes_top100_20260302.json` - 2026年3月2日生成的 Top 100 列表

### 文件格式

生成的文件包含：
```json
{
  "metadata": {
    "description": "Top 50 ComfyUI custom nodes sorted by GitHub stars",
    "total_plugins": 50,
    "source": "comfyui_manager_official_list.json",
    "created_at": "2026-03-02 12:18:50",
    "min_stars": 955,
    "max_stars": 13769
  },
  "custom_nodes": [
    {
      "id": "comfyui-manager",
      "name": "ComfyUI-Manager",
      "repository": "https://github.com/ltdrdata/ComfyUI-Manager",
      "version": "nightly",
      "stars": 13769,
      "author": "Dr.Lt.Data",
      "last_update": "2026-02-27 23:59:40"
      "enabled": true,
      "description": "..."
    }
  ]
}
```

### 高级用法

直接使用 Python 脚本（在 `custom_nodes_config/` 目录下）：

```bash
# 自定义输出文件名
python3 update_topn_plugins.py 50 --output my_top50.json

# 从不同的源文件获取
python3 update_topn_plugins.py 30 --source custom_nodes.json

# 查看帮助
python3 update_topn_plugins.py --help
```

### 注意事项

1. **数据源**：默认从 `comfyui_manager_official_list.json`（ComfyUI Manager 官方插件列表）获取数据
2. **可用数量**：官方列表包含 **4,209 个插件**，其中 **3,531 个插件**包含有效的 stars 数据
3. **最大支持**：可以生成最多 Top 3531 的插件列表
4. **更新频率**：官方列表数据来自 ComfyUI Manager，建议定期更新以获取最新数据

---

## 添加 GitHub Stars 数据

官方列表不包含 stars 数据，如需添加：

```python
import json
import requests
import time

def fetch_github_stars(repo_url):
    """从 GitHub API 获取 stars 数量"""
    if not repo_url.startswith("https://github.com/"):
        return 0
    
    # 提取 owner/repo
    parts = repo_url.replace("https://github.com/", "").rstrip("/").split("/")
    if len(parts) < 2:
        return 0
    
    owner, repo = parts[0], parts[1]
    
    try:
        api_url = f"https://api.github.com/repos/{owner}/{repo}"
        headers = {"Authorization": "token YOUR_GITHUB_TOKEN"}  # 可选，提高速率限制
        response = requests.get(api_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            return data.get("stargazers_count", 0)
        else:
            print(f"Error fetching {repo_url}: {response.status_code}")
            return 0
    except Exception as e:
        print(f"Error fetching {repo_url}: {e}")
        return 0

# 读取官方列表
with open("comfyui_manager_official_list.json") as f:
    data = json.load(f)

# 为每个插件添加 stars
for i, node in enumerate(data["custom_nodes"]):
    if i % 10 == 0:
        print(f"Progress: {i}/{len(data['custom_nodes'])}")
    
    repo_url = node.get("reference", "")
    stars = fetch_github_stars(repo_url)
    node["stars"] = stars
    
    # GitHub API 限流，每个请求间隔1秒
    time.sleep(1)

# 保存结果
with open("custom_nodes_with_stars.json", "w") as f:
    json.dump(data, f, indent=2)

# 按 stars 排序并提取 top 100
sorted_nodes = sorted(
    [n for n in data["custom_nodes"] if n.get("stars", 0) > 0],
    key=lambda x: x["stars"],
    reverse=True
)[:100]

with open("custom_nodes_top100.json", "w") as f:
    json.dump({"custom_nodes": sorted_nodes}, f, indent=2)
```

---

## 相关设计文档

详细的系统插件架构设计请参考：
- [系统插件设计文档](../../../system-plugins-design.md)

---

**维护者：** 云平台架构团队  
**最后更新：** 2026-03-02
