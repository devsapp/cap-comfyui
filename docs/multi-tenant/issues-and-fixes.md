# 多租户预发验证：问题排查与修复记录

**日期**：2026-05-23  
**环境**：预发 FunArt 控制台 + 多租户模式  
**适用版本**：ComfyUI v0.3.77 / v0.16.4  
**分支**：`feat/multi-user-v0377`（v0.3.77）、`multi-user`（v0.16.4）

---

## 问题一：媒体资产面板不展示生成的图片

### 现象

- 工作流执行成功，图片生成在正确的多租目录（`output/users/{user_id}/`）
- 但前端「媒体资产」面板显示为空
- 接口 `GET /api/jobs?status=completed,failed,cancelled` 返回 `{"jobs": [], "total": 0}`

### 根因

`/api/jobs` 是 ComfyUI v0.16.4 新增的原生 API，用于前端展示执行历史和媒体资产。

在 CPU+GPU 双函数架构中：
- 用户浏览器访问的是 **CPU 函数**（`comfyui-gw-xxx`）
- CPU 函数的 GatewayRoutes 未注册 `/api/jobs` 路由
- 请求穿透到 CPU 函数本地 ComfyUI 的 `/api/jobs` 端点
- 本地 ComfyUI 从不执行 prompt（都转发到 GPU 函数），所以 in-memory history 永远为空

对比：旧的 `/api/history` 接口在 CPU 模式有专门的 `HistoryHandler` 处理（从 TaskManager 读取），但 v0.16.4 新增的 `/api/jobs` 被遗漏了。

### 修复

**文件**：`src/code/agent/routes/gateway_routes.py`  
**改动**：在 CPU 模式注册 `/api/jobs` 和 `/api/jobs/<job_id>` 路由

**文件**：`src/code/agent/services/gateway/handlers/jobs_handler.py`（新建）  
**改动**：`JobsHandler` 类，从 TaskManager 的 HistoryManager 读取历史数据，转换为 v0.16.4 的 jobs 响应格式

**影响范围**：仅 CPU 模式生效，GPU 模式不注册此路由。旧版本前端不调用 `/api/jobs`，零影响。

### 验证方法

```bash
# 执行一个 workflow 后
curl "http://<cpu-function-url>/api/jobs?status=completed&limit=10"
# 应返回 {"jobs": [...], "pagination": {"total": >0}}
```

---

## 问题二：执行线程用户上下文丢失

### 现象

- 插件启用后，workflow 执行成功
- 但输出图片保存到了 `output/` 根目录而不是 `output/users/{user_id}/`
- `/view` 请求返回 404（在用户目录找不到文件）

### 根因

ComfyUI 的 `prompt_worker` 在独立线程中运行 `PromptExecutor.execute()`。HTTP 请求通过 `server_patch.py` 中间件设置了 `contextvars` 用户上下文，但执行线程不在 HTTP 请求上下文中，读不到 header。

`execution_patch.py` 设计为从 `extra_data` 中读取 user_id，但 Agent 的 catch-all proxy 只转发了 HTTP header，没有把 user_id 注入到 POST `/prompt` 的 JSON body 中的 `extra_data` 字段。

### 修复

**文件**：`src/code/agent/routes/routes.py`  
**改动**：在 catch-all proxy 中，对 `POST /prompt` 和 `POST /api/prompt` 请求，将 `user_id` 注入到请求 body 的 `extra_data` 字段

```python
if user_id and path in ('prompt', 'api/prompt') and request.method == 'POST':
    json_data['extra_data'][constants.HEADER_FUNART_COMFY_USERID.lower()] = user_id
```

**为什么旧版本没有这个问题**：旧版本（v0.3.77）没有多租执行隔离功能，不需要在执行线程中获取用户上下文。这是多租插件的新增需求。

### 验证方法

```bash
# 以某用户身份执行 workflow 后检查输出目录
ls /mnt/<nas>/output/users/<user_id>/
# 应有新生成的图片
```

---

## 问题三：DynamicPathProxy JSON 序列化失败

### 现象

- 启用多租后，访问 ComfyUI 的 `/object_info` 端点报 500 错误
- 日志报 `TypeError: Object of type DynamicPathProxy is not JSON serializable`

### 根因

`folder_paths_patch.py` 将 `get_output_directory()` 等函数的返回值改为 `DynamicPathProxy` 对象（惰性解析，解决节点实例缓存问题）。但 ComfyUI 的 `/object_info` 端点在序列化节点信息时调用 `json.dumps()`，无法处理 `DynamicPathProxy` 类型。

### 修复

**文件**：`src/code/comfyui/custom_nodes/FunArt-ComfyUI-Multi-User/__init__.py`  
**改动**：Patch `json.JSONEncoder.default`，遇到 `DynamicPathProxy` 自动转为字符串

```python
_original_json_default = json.JSONEncoder.default
def _json_default_with_proxy(self, obj):
    if isinstance(obj, DynamicPathProxy):
        return str(obj)
    return _original_json_default(self, obj)
json.JSONEncoder.default = _json_default_with_proxy
```

**影响范围**：仅在插件启用时生效。非 `DynamicPathProxy` 对象走原始 `default` 逻辑，零影响。

---

## 问题四：server_patch 使用 response hook 方式不可靠

### 现象

- 部分请求（如 `/view`）的用户上下文未被正确设置
- 在某些 ComfyUI 版本中，`on_response_prepare` hook 不触发

### 根因

原来的 `server_patch.py` 使用 aiohttp 的 `on_response_prepare` 信号来注入用户上下文，但这个信号在响应准备阶段才触发，时机太晚。请求处理过程中 `folder_paths` 已经被调用，此时 user_id 还未设置。

### 修复

**文件**：`src/code/comfyui/custom_nodes/FunArt-ComfyUI-Multi-User/server_patch.py`  
**改动**：改用 aiohttp `@web.middleware` 装饰器注入用户上下文，在请求处理之前就设置好 user_id

```python
@web.middleware
async def _user_context_middleware(request: web.Request, handler):
    user_id = request.headers.get('X-FunArt-Comfy-UserId', 'default')
    set_current_user(user_id)
    try:
        return await handler(request)
    finally:
        clear_current_user()
```

**兼容性**：aiohttp middleware 机制在所有 ComfyUI 版本（v0.3.77 和 v0.16.4）中均可用。

---

## 问题五：快照路径格式不正确（线上发布失败）

### 现象

- 在预发 FunArt 控制台点击「线上发布」报错：「快照路径格式不正确」
- 错误信息提示路径需包含正确的目录层级

### 根因

`make upload-comfyui-base` 上传的是原始 tar.zst 数据（base snapshot），不是可发布的 dev snapshot。FunArt 的发布流程需要的是 `${MNT_DIR}/snapshots/dev-<timestamp>/` 格式的快照目录，由工作空间启动时 agent 自动创建。

### 解决方案

1. 先在控制台中**启动工作空间**（agent 会展开 base 数据并创建 dev snapshot）
2. 等待 ComfyUI 启动完成
3. 再点击「线上发布」（此时 NAS 上已有正确格式的 snapshot）

**这不是代码 bug**，是操作顺序问题。

---

## 问题六：GPU 函数未启动导致 workflow 不执行

### 现象

- 提交 workflow 后，前端显示触发成功
- 推理日志中异步消息收到，但不执行
- TaskManager 日志只有 `Started messages polling for task...` 但无后续

### 根因

GPU 函数没有可用 GPU 卡（资源不足），函数实例未启动。CPU 函数向 GPU 函数发起异步调用后，轮询状态一直处于 pending。

### 解决方案

等待 GPU 资源可用，或选择有可用 GPU 卡的规格/地域。确认 GPU 函数实例已启动：

```bash
# 检查 GPU 函数状态
curl -s "http://<gpu-function-url>/management/status"
# 应返回 {"status": "RUNNING"}
```

---

## 修改清单总结

| 文件 | 修复的问题 | 适用版本 |
|------|-----------|---------|
| `agent/routes/routes.py` | #2 执行线程用户上下文丢失 | v0.3.77 + v0.16.4 |
| `agent/routes/gateway_routes.py` | #1 /api/jobs 返回空 | v0.3.77 + v0.16.4 |
| `agent/services/gateway/handlers/jobs_handler.py` | #1 /api/jobs 返回空 | v0.3.77 + v0.16.4 |
| `FunArt-ComfyUI-Multi-User/__init__.py` | #3 JSON 序列化失败 | v0.3.77 + v0.16.4 |
| `FunArt-ComfyUI-Multi-User/server_patch.py` | #4 用户上下文注入不可靠 | v0.3.77 + v0.16.4 |

所有修改对未启用多租的环境零影响（由 `ENABLE_COMFYUI_MULTI_USER` 环境变量控制）。
