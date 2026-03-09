# ComfyUI 模型管理工具

批量下载、验证、同步 ComfyUI 模型的工具集。

## 📁 目录结构

```
models/
├── models.json              # 主模型列表（全量，长期维护）
├── models_xxx.json          # 增量模型列表（按批次，合并前暂存）
├── scripts/
│   ├── extract_models.py    # 从模板中提取模型信息
│   ├── download_models.sh   # 批量下载模型文件
│   ├── cal_checksum.py      # 验证文件 SHA256 完整性
│   ├── merge_models.py      # 将增量列表合并到 models.json
│   └── sync_dev_to_prod.sh  # 将 dev OSS 模型同步到 prod OSS
└── README.md
```

**OSS 挂载说明**：

| 环境 | 挂载路径 | OSS Bucket |
|------|----------|------------|
| Dev  | `/mnt/funart-dev/models` | `dipper-cache-cn-hangzhou-dev` |
| Prod | `/mnt/funart-prod/models` | `dipper-cache-cn-hangzhou` |

---

## 🚀 完整工作流

### 准备工作

```bash
pip install huggingface_hub
```

---

### 第 1 步：准备增量模型列表

**方式 A：从模板自动提取**（提取工作流广场模板中引用的模型）

```bash
cd models
python3 scripts/extract_models.py
# 输出: models_YYYYMMDD.json
```

**方式 B：手动维护**

直接创建或编辑 `models_xxx.json`，格式如下：

```json
{
    "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors": {
        "url": "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
        "directory": "diffusion_models"
    }
}
```

---

### 第 2 步：下载模型到 dev

```bash
# 下载所有模型（使用国内镜像加速）
export HF_ENDPOINT="https://hf-mirror.com"
./scripts/download_models.sh models_20260308.json /mnt/funart-dev/models --use-mirror

# 只下载指定目录的模型（推荐，按需下载）
./scripts/download_models.sh models_20260308.json /mnt/funart-dev/models --use-mirror --dirs diffusion_models loras
```

**参数说明**：

| 参数 | 说明 |
|------|------|
| `models_xxx.json` | 增量模型列表 |
| `/mnt/funart-dev/models` | 下载目标目录（dev 挂载路径） |
| `--use-mirror` | 使用国内镜像（https://hf-mirror.com） |
| `--dirs <目录...>` | 只下载指定目录的模型 |

---

### 第 3 步：验证 checksum

```bash
# 验证所有下载的模型
python3 scripts/cal_checksum.py /mnt/funart-dev/models models_20260308.json

# 只验证指定目录
python3 scripts/cal_checksum.py /mnt/funart-dev/models models_20260308.json --dir diffusion_models
```

验证结果：
- ✅ **一致**：文件完整
- ❌ **不一致**：删除后重新下载

```bash
# 重新下载不一致的模型
rm /mnt/funart-dev/models/diffusion_models/problematic_model.safetensors
./scripts/download_models.sh models_20260308.json /mnt/funart-dev/models --use-mirror --dirs diffusion_models
```

---

### 第 4 步：同步到 prod OSS

确认 dev 下载无误后，将新模型同步到 prod。

**先 dry-run，确认将执行的 ossutil 命令**：

```bash
make sync-models-to-prod-dry-run
```

输出示例：

```
[Dry Run] 将执行以下 ossutil 命令:
  ossutil cp --ignore-existing "oss://dipper-cache-cn-hangzhou-dev/funart/models/diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors" "oss://dipper-cache-cn-hangzhou/function-art/comfyui/models/diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors"
  ...
```

**确认无误后，正式同步**：

```bash
make sync-models-to-prod
```

> 同步使用 `--ignore-existing`，不会覆盖 prod 中已存在的模型。

**只查看 diff，不执行同步**：

```bash
make diff-models
# 生成 models/diff_YYYYMMDD.json
```

---

### 第 5 步：合并到主模型列表

同步完成后，将增量列表合并到 `models.json`：

```bash
make merge-models MODELS_JSON=models/models_20260308.json
```

输出示例：

```
源文件:   models/models_20260308.json  (5 个模型)
目标文件: models/models.json

新增 5 个模型:
  + wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors
  + wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors
  ...

完成。models.json 现有 140 个模型。
```

> 合并规则：新模型追加，已存在的跳过，不会覆盖 `models.json` 中已有条目。

---

## 📋 Make 命令速查

| 命令 | 说明 |
|------|------|
| `make diff-models` | 列出 dev 有但 prod 没有的模型，生成 `diff_YYYYMMDD.json` |
| `make sync-models-to-prod-dry-run` | 预览将执行的 ossutil 命令（不实际执行） |
| `make sync-models-to-prod` | 将 dev 新模型同步到 prod OSS |
| `make merge-models MODELS_JSON=models/models_xxx.json` | 将增量列表合并到 `models.json` |

**覆盖默认变量**（如挂载路径或 bucket 不同时）：

```bash
make sync-models-to-prod \
  DEV_MOUNT=/custom/dev/path \
  PROD_MOUNT=/custom/prod/path \
  DEV_OSS_BUCKET=my-dev-bucket \
  PROD_OSS_BUCKET=my-prod-bucket
```

---

## 💡 使用技巧

### 按需下载，节省时间和空间

```bash
# 先下载小文件
./scripts/download_models.sh models_xxx.json /mnt/funart-dev/models --use-mirror --dirs vae loras clip

# 网络稳定时再下载大模型
./scripts/download_models.sh models_xxx.json /mnt/funart-dev/models --use-mirror --dirs diffusion_models unet checkpoints
```

### 查看模型按目录分布

```bash
python3 -c "
import json
from collections import Counter
with open('models/models.json') as f:
    data = json.load(f)
dirs = Counter(info.get('directory', 'unknown') for info in data.values())
for d, count in sorted(dirs.items()):
    print(f'{d}: {count} 个模型')
"
```

### 永久配置国内镜像

在 `~/.bashrc` 或 `~/.zshrc` 中添加：

```bash
export HF_ENDPOINT="https://hf-mirror.com"
```

配置后无需每次都加 `--use-mirror` 参数。

---

## ⚠️ 常见问题

### 下载速度慢

使用 `--use-mirror` 或预先设置 `HF_ENDPOINT` 环境变量。

### 找不到 hf 命令

```bash
pip install -U huggingface_hub
```

### SHA256 不一致

文件下载不完整或损坏，删除后重新下载：

```bash
rm /mnt/funart-dev/models/diffusion_models/problematic_model.safetensors
./scripts/download_models.sh models_xxx.json /mnt/funart-dev/models --use-mirror --dirs diffusion_models
```

### ossutil 未配置

```bash
# 安装
sudo -v ; curl https://gosspublic.alicdn.com/ossutil/install.sh | sudo bash

# 配置（需要有 OSS 写权限的 AK/SK，可联系 zijian）
ossutil config
# endpoint: oss-cn-hangzhou-internal.aliyuncs.com（内网）或 oss-cn-hangzhou.aliyuncs.com（公网）
```
