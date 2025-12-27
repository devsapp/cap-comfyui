# ComfyUI 模型下载工具

从 ComfyUI 模板中提取模型信息，批量下载并验证文件完整性的工具集。

## 📁 工具脚本

| 脚本 | 功能 |
|------|------|
| `extract_models.py` | 从模板中提取模型信息 |
| `download_models.sh` | 批量下载模型文件 |
| `cal_checksum.py` | 验证文件 SHA256 完整性 |

## 🚀 使用流程

### 准备工作

安装依赖：
```bash
pip install huggingface_hub
```

### 第 1 步：提取模型信息

从 `templates` 目录提取所有模板使用的模型信息：

```bash
cd models
python3 extract_models.py
```

**输出**：`models_20251225.json`（自动生成当前日期）

### 第 2 步：下载模型

根据提取的配置文件下载模型：

```bash
# 下载所有模型（使用国内镜像加速）
./download_models.sh models_20251220.json /root/ComfyUI/models --use-mirror

# 只下载指定目录的模型（推荐）
./download_models.sh models_20251220.json /root/ComfyUI/models --use-mirror --dirs vae loras

# 支持多个目录
./download_models.sh models_20251220.json /root/ComfyUI/models --use-mirror --dirs unet clip vae loras
```

**参数说明**：
- `models_*.json`：第 1 步生成的配置文件
- `/root/ComfyUI/models`：下载目标目录
- `--use-mirror`：使用国内镜像（https://hf-mirror.com）
- `--dirs <目录...>`：只下载指定目录的模型

**功能特性**：
- ✅ 自动创建目录结构
- ✅ 跳过已存在的文件
- ✅ 失败自动重试 3 次
- ✅ 显示详细的下载进度和统计

### 第 3 步：验证完整性

验证下载的文件是否完整：

```bash
# 验证所有模型
python3 cal_checksum.py /root/ComfyUI/models models_20251220.json

# 只验证指定目录
python3 cal_checksum.py /root/ComfyUI/models models_20251220.json --dir vae

# 使用国内镜像获取 SHA256（推荐）
export HF_ENDPOINT="https://hf-mirror.com"
python3 cal_checksum.py /root/ComfyUI/models models_20251220.json
```

**验证结果**：
- ✅ **一致**：文件完整
- ❌ **不一致**：需要重新下载
- ⚠️ **错误**：无法验证（非 HF 链接或缺少 URL）

如有不一致的文件，删除后重新运行第 2 步：
```bash
rm /root/ComfyUI/models/loras/problematic_model.safetensors
./download_models.sh models_20251225.json /root/ComfyUI/models --use-mirror --dirs loras
```

## 💡 使用技巧

### 按需下载，节省时间和空间

根据实际需要，先下载关键模型：

```bash
# 先下载小文件
./download_models.sh models_20251225.json /root/models --use-mirror --dirs vae loras clip

# 网络稳定时再下载大模型
./download_models.sh models_20251225.json /root/models --use-mirror --dirs unet checkpoints
```

### 查看可用目录

查看配置文件中包含哪些目录：

```bash
python3 -c "
import json
from collections import Counter
with open('models_20251225.json') as f:
    data = json.load(f)
dirs = Counter(info.get('directory', 'unknown') for info in data.values())
for dir_name, count in sorted(dirs.items()):
    print(f'{dir_name}: {count} 个模型')
"
```

常见目录：
- `unet`：UNET 模型（通常较大）
- `vae`：VAE 编码器
- `clip`：CLIP 文本编码器
- `loras`：LoRA 微调模型
- `checkpoints`：完整检查点
- `controlnet`：ControlNet 控制模型
- `clip_vision`：CLIP 视觉编码器

## 📊 输出示例

### 提取模型信息

```
==============================
提取 ComfyUI 模板中的模型信息
==============================
模板目录: ../templates

正在分析模板文件...
找到 206 个模板文件
✓ 找到 130 个独特的模型文件
✓ 已生成: models_20251220.json

按目录分布:
  unet      : 46 个
  loras     : 18 个
  checkpoints: 19 个
  vae       : 10 个
  ...
```

### 下载模型

```
======================================
开始下载 ComfyUI 模型
======================================
模型配置: models_20251220.json
目标目录: /root/ComfyUI/models
筛选目录: vae loras

可用目录: audio checkpoints clip controlnet loras unet vae
要下载 28 个模型

[1/28] vae-ft-mse-840000-ema-pruned.safetensors
  目录: vae
  下载中...
  ✓ 下载完成

[2/28] flux1-depth-dev-lora.safetensors
  目录: loras
  ✓ 已存在，跳过
...

======================================
下载完成!
======================================
成功: 22
跳过: 5
失败: 1
总计: 28
======================================
```

### 验证完整性

```
================================================================================
🔍 ComfyUI 模型 SHA256 验证工具
================================================================================
✓ 找到 28 个模型文件

[1/28] 验证: vae/vae-ft-mse.safetensors
  计算本地 SHA256...
  从 Hugging Face 获取 SHA256...
✅ 状态: 一致
...

================================================================================
📊 验证总结
================================================================================
总文件数: 28
✅ 一致:   27
❌ 不一致: 1

⚠️  以下模型 SHA256 不一致，建议重新下载:
  • loras/problematic_model.safetensors
================================================================================
```

## ⚠️ 常见问题

### 1. 下载速度慢

**解决方案**：使用 `--use-mirror` 启用国内镜像加速

```bash
./download_models.sh models_20251225.json /root/models --use-mirror
```

### 2. 找不到 hf 命令

**解决方案**：
```bash
pip install -U huggingface_hub
```

### 3. 下载失败

**解决方案**：
1. 检查网络连接
2. 使用镜像加速（`--use-mirror`）
3. 检查磁盘空间：`df -h`
4. 脚本会自动重试 3 次，失败后可手动重新运行

### 4. SHA256 不一致

**原因**：文件下载不完整或损坏

**解决方案**：删除文件后重新下载
```bash
rm /path/to/problematic_model.safetensors
./download_models.sh models_20251225.json /root/models --use-mirror
```

## 🌐 永久配置国内镜像

在 `~/.bashrc` 或 `~/.zshrc` 中添加：

```bash
export HF_ENDPOINT="https://hf-mirror.com"
```

然后重新加载：
```bash
source ~/.bashrc  # 或 source ~/.zshrc
```

配置后，无需每次都加 `--use-mirror` 参数。

## 📖 工作原理

### extract_models.py
1. 扫描 `templates` 目录的所有 JSON 文件
2. 解析节点中的模型文件名和下载链接
3. 根据节点类型推断存储目录
4. 生成 `models_{日期}.json` 配置文件

### download_models.sh
1. 读取配置文件中的模型信息
2. 根据 `--dirs` 参数筛选目录（可选）
3. 检查文件是否已存在，存在则跳过
4. 使用 `hf download` 命令下载
5. 失败自动重试，最多 3 次
6. 生成下载统计报告

### cal_checksum.py
1. 扫描指定目录的模型文件
2. 计算本地文件的 SHA256
3. 从 Hugging Face API 获取远程 SHA256
4. 比对并生成验证报告

---

**提示**：建议使用 `--dirs` 参数按需下载，避免下载不需要的大模型，节省时间和磁盘空间。
