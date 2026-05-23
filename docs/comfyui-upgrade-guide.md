# ComfyUI 版本升级指南

**适用环境**：阿里云函数计算 FunArt 平台实例  
**操作方式**：登录实例终端执行  
**预计耗时**：5-15 分钟（视网络状况）

---

## 一、前置准备

### 1.1 确认当前版本

```bash
cd ~/comfyui
git log --oneline -1
# 或查看版本标签
git describe --tags --always
```

### 1.2 备份当前环境（推荐）

升级前通过控制台保存一次快照，或手动记录当前版本：

```bash
cat ~/comfyui/.funart-comfyui-version 2>/dev/null || echo "未记录版本"
```

> **重要**：升级后如遇问题，可通过控制台回滚到之前保存的快照。

---

## 二、升级步骤

### 2.1 进入 ComfyUI 目录

```bash
cd ~/comfyui
```

### 2.2 添加远程镜像仓库（加速 GitHub 访问）

```bash
git remote add mirror https://gh.llkk.cc/https://github.com/comfyanonymous/ComfyUI.git
```

> 若提示 `fatal: remote mirror already exists.`，说明已添加过，可忽略。

### 2.3 拉取最新信息

```bash
git fetch mirror --tags
```

### 2.4 查看可用版本

```bash
# 查看所有标签（版本号）
git tag --sort=-v:refname | head -20
```

### 2.5 切换到目标版本

```bash
# 示例：升级到 v0.16.4
git checkout v0.16.4
```

> 如果有本地修改冲突，执行：
> ```bash
> git stash
> git checkout v0.16.4
> git stash pop  # 尝试恢复本地修改（可选）
> ```

### 2.6 安装/更新 Python 依赖

```bash
pip install -r requirements.txt \
  -i https://mirrors.aliyun.com/pypi/simple/ \
  --trusted-host mirrors.aliyun.com \
  --extra-index-url https://pypi.org/simple/
```

> **说明**：优先使用阿里云镜像（内网高速），部分新包自动回退到官方 PyPI。

### 2.7 重启 ComfyUI

通过控制台重启实例，或在终端执行：

```bash
# 方式一：通过 Agent API 重启
curl -X POST http://localhost:9000/api/manager/reboot

# 方式二：手动 kill 后 Agent 自动拉起
kill $(pgrep -f "python.*main.py")
```

---

## 三、验证升级成功

### 3.1 检查版本号

打开 ComfyUI Web UI，底部应显示新版本号。

或通过终端确认：

```bash
cd ~/comfyui
git describe --tags --always
```

### 3.2 功能验证

执行一次简单的文生图工作流，确认：
- 节点加载正常
- 图片生成成功
- 预览显示正常

---

## 四、常见问题

### Q1: `git fetch` 超时或失败

**原因**：GitHub 镜像不稳定。

**解决**：更换镜像地址后重试：

```bash
# 删除旧 remote
git remote remove mirror

# 换一个镜像
git remote add mirror https://ghproxy.com/https://github.com/comfyanonymous/ComfyUI.git
# 或
git remote add mirror https://mirror.ghproxy.com/https://github.com/comfyanonymous/ComfyUI.git

git fetch mirror --tags
```

### Q2: `pip install` 报 403 / 超时

**原因**：国内镜像源未同步某些新包。

**解决**：使用阿里云 + 官方 PyPI 双源：

```bash
pip install -r requirements.txt \
  -i https://mirrors.aliyun.com/pypi/simple/ \
  --trusted-host mirrors.aliyun.com \
  --extra-index-url https://pypi.org/simple/
```

如果仍然失败，可尝试其他国内源：

```bash
# 腾讯云
pip install -r requirements.txt -i https://mirrors.cloud.tencent.com/pypi/simple/ --trusted-host mirrors.cloud.tencent.com --extra-index-url https://pypi.org/simple/

# 华为云
pip install -r requirements.txt -i https://repo.huaweicloud.com/repository/pypi/simple/ --trusted-host repo.huaweicloud.com --extra-index-url https://pypi.org/simple/
```

### Q3: 升级后插件报错 / 节点缺失

**原因**：新版本 ComfyUI 可能与某些插件不兼容。

**解决**：
1. 查看 ComfyUI 终端日志，定位报错插件
2. 进入插件目录更新到兼容版本：
   ```bash
   cd ~/comfyui/custom_nodes/<插件名>
   git pull
   ```
3. 如果插件有 `requirements.txt`，重新安装依赖：
   ```bash
   pip install -r requirements.txt \
     -i https://mirrors.aliyun.com/pypi/simple/ \
     --trusted-host mirrors.aliyun.com \
     --extra-index-url https://pypi.org/simple/
   ```

### Q4: 升级后想回退到旧版本

```bash
cd ~/comfyui

# 查看之前的版本
git reflog | head -5

# 切换回旧版本
git checkout v0.3.77

# 重新安装旧版本依赖
pip install -r requirements.txt \
  -i https://mirrors.aliyun.com/pypi/simple/ \
  --trusted-host mirrors.aliyun.com \
  --extra-index-url https://pypi.org/simple/

# 重启
curl -X POST http://localhost:9000/api/manager/reboot
```

### Q5: 升级后保存快照，下次冷启动还是旧版本

**原因**：`COMFYUI_VERSION` 环境变量控制快照加载路径，可能指向旧版本目录。

**解决**：升级后执行一次快照保存（控制台点保存，或通过 API）：

```bash
curl -X POST http://localhost:9000/management/save
```

这样下次冷启动会加载包含新版本代码的快照。

---

## 五、版本兼容性参考

| ComfyUI 版本 | Python | PyTorch | 说明 |
|-------------|--------|---------|------|
| v0.3.77 | 3.10+ | 2.x | 稳定版，大部分插件兼容 |
| v0.16.4 | 3.10+ | 2.x | 新版，UI 重构，部分旧插件可能需更新 |

> **建议**：升级前查看 [ComfyUI Release Notes](https://github.com/comfyanonymous/ComfyUI/releases) 确认目标版本的变更内容。

---

## 六、升级清单（Checklist）

- [ ] 确认当前版本号
- [ ] 控制台保存快照（备份）
- [ ] `git fetch mirror --tags`
- [ ] `git checkout <目标版本>`
- [ ] `pip install -r requirements.txt`（使用双源）
- [ ] 重启 ComfyUI
- [ ] 验证版本号正确
- [ ] 验证基本功能正常
- [ ] 保存快照（持久化新版本）
