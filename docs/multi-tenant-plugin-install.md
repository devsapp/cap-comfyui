# FunArt-ComfyUI-Multi-User 多租插件安装指南

**适用版本**：ComfyUI v0.3.77 / v0.16.4  
**前置条件**：实例运行在 FunArt 平台（cap-comfyui agent 层已部署）  
**插件依赖**：无（纯 Python 标准库，零 pip 依赖）

---

## 一、概述

`FunArt-ComfyUI-Multi-User` 插件为 ComfyUI 提供**按用户隔离**的资产目录能力：

- 每个用户的 output/input/temp 文件存放在独立子目录（`users/{user_id}/`）
- 不同用户之间的执行缓存互不干扰
- 对 ComfyUI 原有功能零入侵，未激活时无任何副作用

### 架构关系

```
浏览器/API 调用
    ↓
FC HTTP 触发器 (认证、注入用户身份)
    ↓
Agent (port 9000) ← 提取 user_id，注入到 header + extra_data
    ↓
ComfyUI (port 8188) ← 本插件读取 user_id，隔离目录
```

> **重要**：本插件仅负责 ComfyUI 侧的目录隔离。用户身份的识别和注入由 Agent 层完成。  
> 脱离 Agent 单独安装插件**无法实现完整多租**（执行线程会丢失用户上下文）。

---

## 二、内部操作指南（运维/客服）

### 2.1 打包插件

在开发机上执行：

```bash
cd src/code/comfyui/custom_nodes

# 打包（排除缓存文件）
tar -czf FunArt-ComfyUI-Multi-User.tar.gz \
  --exclude='__pycache__' \
  FunArt-ComfyUI-Multi-User/

# 产出文件：FunArt-ComfyUI-Multi-User.tar.gz（约 15KB）
```

### 2.2 包内容校验

打包后确认包含以下 7 个文件：

```
FunArt-ComfyUI-Multi-User/
├── __init__.py              # 入口，控制插件激活
├── context.py               # 用户上下文管理（contextvars）
├── path_proxy.py            # DynamicPathProxy 动态路径代理
├── folder_paths_patch.py    # 目录函数 monkey-patch
├── execution_patch.py       # 执行线程用户上下文传播
├── cache_signature_patch.py # 缓存签名用户隔离
└── server_patch.py          # HTTP 请求用户上下文注入
```

### 2.3 交付给客户

将 `FunArt-ComfyUI-Multi-User.tar.gz` 通过工单/钉钉发送给客户，并附上下方「客户安装步骤」。

---

## 三、客户安装步骤

### 3.1 上传插件包

将收到的 `FunArt-ComfyUI-Multi-User.tar.gz` 上传到实例中。

### 3.2 解压到 custom_nodes 目录

登录实例终端，执行：

```bash
# 进入 ComfyUI 的 custom_nodes 目录
cd /root/comfyui/custom_nodes/

# 解压插件包
tar -xzf /path/to/FunArt-ComfyUI-Multi-User.tar.gz

# 确认目录结构正确
ls FunArt-ComfyUI-Multi-User/
# 应看到: __init__.py  context.py  path_proxy.py  folder_paths_patch.py  execution_patch.py  cache_signature_patch.py  server_patch.py
```

> **注意**：如果 `/root/comfyui/custom_nodes` 是一个软链接（指向 NAS），解压会直接写入 NAS，实例重启后仍然存在。可通过 `ls -la /root/comfyui/custom_nodes` 确认。

### 3.3 配置环境变量

在 FunArt 控制台中设置环境变量：

```
ENABLE_COMFYUI_MULTI_USER = true
```

或通过 FC 控制台 → 函数配置 → 环境变量 中添加。

> 此环境变量同时控制：
> - Agent 层的用户身份识别（开启后从请求中提取 user_id）
> - 插件的激活（开启后安装 monkey-patch）

### 3.4 重启 ComfyUI

通过控制台重启函数实例，或调用管理接口：

```bash
curl -X POST http://localhost:9000/api/manager/reboot
```

### 3.5 验证安装成功

#### 方法一：检查启动日志

在实例终端中查看 ComfyUI 输出，应包含：

```
[ComfyUI-Multi-User] ✅ 插件已启用并安装成功 (v1.0.0)
```

如果看到以下信息则说明环境变量未设置：

```
[ComfyUI-Multi-User] ⚠️ 插件未启用
```

#### 方法二：检查目录隔离

执行一次图片生成后，确认输出文件位于用户子目录中：

```bash
# 假设用户 ID 为 user-abc123
ls /mnt/<nas-mount>/output/users/user-abc123/
# 应看到生成的图片文件
```

#### 方法三：API 测试

```bash
# 带用户 header 请求 /view（通过 agent 代理）
curl -s -o /dev/null -w "%{http_code}" \
  "http://127.0.0.1:8188/api/view?filename=<生成的文件名>&type=output&subfolder=" \
  -H "X-FunArt-Comfy-UserId: <用户ID>"

# 返回 200 = 正常；404 = 插件未生效或文件路径不对
```

---

## 四、配合控制台使用

### 4.1 控制台开启多租

在 FunArt 控制台中开启「多租户模式」开关，等效于设置：

```
ENABLE_COMFYUI_MULTI_USER=true
```

开启后：
1. Agent 开始从请求中识别用户（JWT / Basic Auth）
2. Agent 将 `user_id` 注入到转发给 ComfyUI 的请求 header 和 prompt body 中
3. 插件读取 `user_id`，自动将文件操作路由到用户专属目录

### 4.2 关闭多租

控制台关闭多租开关或移除环境变量后重启：
- Agent 将所有用户视为 `default`
- 插件不激活，所有文件回到原始目录结构
- **已有的 `users/` 子目录不会被删除**，但新文件不再写入

---

## 五、工作原理

### 5.1 目录隔离结构

```
/mnt/<nas>/output/                    ← user_id='default' 时使用（单租/未开启）
/mnt/<nas>/output/users/user-A/       ← user_id='user-A' 的产出
/mnt/<nas>/output/users/user-B/       ← user_id='user-B' 的产出
```

同理 `input/`、`temp/` 目录也按相同结构隔离。

### 5.2 用户身份传递链

| 环节 | 负责组件 | 机制 |
|------|----------|------|
| 认证 | FC HTTP 触发器 / 网关 | JWT 验证，注入 `X-FunArt-Comfy-UserId` header |
| 提取 | Agent `user_identity.py` | 从 header 或 Basic Auth 中读取 user_id |
| 注入 (HTTP) | Agent catch-all proxy | 转发请求时带上 `X-FunArt-Comfy-UserId` header |
| 注入 (执行) | Agent proxy | POST /prompt 时将 user_id 写入 `extra_data` |
| 读取 (HTTP) | 插件 `server_patch.py` | aiohttp 中间件从 header 读 user_id |
| 读取 (执行) | 插件 `execution_patch.py` | 从 `extra_data` 读 user_id 设到执行线程 |
| 隔离 | 插件 `folder_paths_patch.py` | 动态解析输出目录为 `base/users/{user_id}/` |

### 5.3 缓存隔离

插件在缓存签名中附加 `user_id`，确保：
- 用户 A 提交的 workflow 缓存不会被用户 B 命中
- 相同 workflow 不同用户各自独立缓存

---

## 六、常见问题

### Q1: 安装后日志显示「插件未启用」

**原因**：`ENABLE_COMFYUI_MULTI_USER` 环境变量未设置或值不为 `true`。

**解决**：确认环境变量已添加并重启实例。注意值必须是小写 `true`。

### Q2: 插件启用了但图片预览 404

**可能原因**：

1. **custom_nodes 为空（被 NAS 覆盖）**  
   检查 `/root/comfyui/custom_nodes/FunArt-ComfyUI-Multi-User/` 是否存在。  
   如果 custom_nodes 是 NAS 软链接，需确保插件解压到了 NAS 对应目录。

2. **Agent 未注入 user_id 到 extra_data**  
   确认 Agent 版本 ≥ v1.4.0（包含 extra_data 注入修复）。

3. **CPU/GPU 双函数环境下只有一侧开启了多租**  
   两个函数都必须设置 `ENABLE_COMFYUI_MULTI_USER=true`，且都需要安装本插件。

### Q3: 旧文件在原目录，新文件在 users/ 子目录

**这是正常行为**。开启多租前产生的文件保留在原始 output 目录，开启后新产生的文件才进入 `users/{user_id}/` 目录。

### Q4: 关闭多租后用户文件还能访问吗？

关闭后，`/view` 请求会在原始 output 目录查找文件。`users/` 子目录下的文件不会被自动访问，但数据仍然保留在 NAS 上，不会丢失。

### Q5: 插件对性能有影响吗？

无明显影响。插件仅在以下时机有额外开销：
- 首次访问某用户目录时创建 `users/{user_id}/` 目录（`os.makedirs`，带缓存避免重复）
- 每次路径解析时一次 `contextvars.get()` 调用（纳秒级）

---

## 七、版本兼容性

| ComfyUI 版本 | 插件兼容性 | 说明 |
|-------------|-----------|------|
| v0.3.77 | ✅ 完全兼容 | 已在生产环境验证 |
| v0.16.4 | ✅ 完全兼容 | 源码级调研确认 API 签名一致 |
| 其他版本 | ⚠️ 未验证 | 需确认 `folder_paths`/`execution`/`comfy_execution.caching` 接口未变 |

---

## 附录：插件文件说明

| 文件 | 功能 | Patch 目标 |
|------|------|-----------|
| `__init__.py` | 入口，按环境变量决定是否激活 | - |
| `context.py` | contextvars 用户上下文管理 | - |
| `path_proxy.py` | DynamicPathProxy，惰性解析用户路径 | - |
| `folder_paths_patch.py` | 目录隔离 | `folder_paths.get_output_directory` 等 |
| `execution_patch.py` | 执行线程用户传播 | `execution.PromptExecutor.execute` |
| `cache_signature_patch.py` | 缓存隔离 | `comfy_execution.caching.CacheKeySetInputSignature` |
| `server_patch.py` | HTTP 请求用户注入 | `server.PromptServer.add_routes` |
