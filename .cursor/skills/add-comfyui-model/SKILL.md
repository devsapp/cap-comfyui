---
name: add-comfyui-model
description: 为 ComfyUI 托管平台新增共享模型。创建增量模型列表文件并提示后续下载步骤。当用户说"新增模型"、"添加模型"、"add model"，或提供模型文件名和下载链接时使用。
---

# 新增 ComfyUI 共享模型

## 工作步骤

### 第 1 步：创建增量模型列表文件

在 `src/code/comfyui/models/` 目录下创建 `models_YYYYMMDD.json`（日期取今天）。

文件格式：

```json
{
  "模型文件名.safetensors": {
    "url": "https://huggingface.co/xxx/resolve/main/xxx.safetensors",
    "directory": "diffusion_models"
  }
}
```

`directory` 常见取值：`checkpoints`、`diffusion_models`、`unet`、`loras`、`clip`、`vae`

### 第 2 步：将改动 push 到 origin

文件创建完成后，将改动提交并推送到远端：

```bash
git add src/code/comfyui/models/models_YYYYMMDD.json
git commit -m "feat: add model qwen_3_4b_fp4_flux2.safetensors"
git push origin HEAD
```

> 提交信息中的模型名替换为实际添加的模型文件名。

### 第 3 步：提示用户后续操作

push 完成后，**必须**输出以下提示：

---

**下一步：登录线上机器下载模型**

账号：`fc-ide-staging`
函数计算控制台：https://fcnext.console.aliyun.com/cn-hangzhou/functions/art-funart-model-pusher-rp8y?tab=detail&section=logging

在线上机器执行以下命令：

```bash
apt-get install tmux
cd /mnt/art-funart-model-pusher-rp8y/cap-comfyui/src/code/comfyui/models
git pull
tmux new-session -s model "bash -c 'export HF_ENDPOINT=https://hf-mirror.com && ./scripts/download_models.sh models_YYYYMMDD.json /mnt/funart-dev/models --use-mirror; exec bash'"
```

> 将 `models_YYYYMMDD.json` 替换为刚创建的文件名。

---

## 注意事项

- 如果同一天已有 `models_YYYYMMDD.json`，直接向该文件追加模型，不要新建
- URL 使用 `resolve/main/` 路径（不用 `blob/main/`），确保可直接下载
- 完整工作流（下载→验证→同步到 prod→合并）参见 `src/code/comfyui/models/README.md`
