# BUG-002: 执行线程用户上下文丢失导致图片预览失败

| 项目 | 内容 |
|------|------|
| **发现日期** | 2026-05-22 |
| **修复日期** | 2026-05-22 |
| **修复 Commit** | 待提交 |
| **严重程度** | P1 — 多租户模式下生成的图片无法预览 |
| **影响版本** | 所有启用 `ENABLE_COMFYUI_MULTI_USER=true` 的版本（v0.3.77、v0.16.4 均受影响） |
| **影响范围** | Agent 代理层（`routes.py`） |
| **修复文件** | `src/code/agent/routes/routes.py` |

---

## 1. 现象

多租户用户在 ComfyUI 中生成图片后，图片预览区域显示空白或加载失败。图片实际已生成，但浏览器无法通过 `/view` 端点获取。

## 2. 根因分析

### 核心问题

用户身份（user_id）在 HTTP header 层正确传递，但**没有注入到 ComfyUI prompt 队列的 `extra_data` 中**，导致异步执行线程无法获取用户上下文，图片被保存到默认目录而非用户专属目录。

### 完整调用链路分析

#### 图片生成阶段（写入路径错误）

```
1. 浏览器 POST /prompt (body: {prompt: {...}, extra_data: {client_id: "xxx"}})
     ↓
2. Agent proxy (routes.py:242)
   - @identify_user_or_default → g.user_id = "alice"（从 Basic Auth 或 JWT header 提取）
   - forward_headers[X-FunArt-Comfy-UserId] = "alice"  ✅ header 正确
   - data = request.get_data()  ← 原样转发 body，extra_data 中无 user_id ❌
     ↓
3. ComfyUI server_patch middleware
   - user_id = request.headers.get('X-FunArt-Comfy-UserId') → "alice"
   - set_current_user("alice")  ✅ 当前协程/线程上下文正确
     ↓
4. ComfyUI post_prompt handler (server.py)
   - extra_data = json_data["extra_data"]  ← 来自 body，没有 user_id
   - self.prompt_queue.put((..., extra_data, ...))  ← 入队，extra_data 无 user_id ❌
     ↓
5. server_patch middleware
   - clear_current_user()  ← 请求结束，清除上下文
     ↓
6. [执行线程] PromptExecutor.execute()
   - execution_patch: extra_data.get('x-funart-comfy-userid', 'default') → "default" ❌
   - set_current_user("default")
     ↓
7. SaveImage / PreviewImage 节点
   - folder_paths.get_output_directory() → DynamicPathProxy → /root/comfyui/output/  (default 目录)
   - 图片保存到: /root/comfyui/output/ComfyUI_00001_.png  ❌ 应该在用户目录
```

#### 图片预览阶段（读取路径不匹配）

```
1. 浏览器 GET /view?filename=ComfyUI_00001_.png&type=output
     ↓
2. Agent proxy → 识别用户 → X-FunArt-Comfy-UserId: alice
     ↓
3. ComfyUI server_patch → set_current_user("alice")
     ↓
4. /view handler (server.py)
   - folder_paths.get_directory_by_type("output")
     → get_output_directory()
     → DynamicPathProxy
     → /root/comfyui/output/users/alice/  ← 查找用户目录 ✅ 但文件不在这里
   - 查找: /root/comfyui/output/users/alice/ComfyUI_00001_.png → FILE NOT FOUND ❌
```

### 问题本质

```
写入阶段: user_id 在 HTTP header 中 → 未注入 extra_data → 执行线程丢失 → 写入 default 目录
读取阶段: user_id 在 HTTP header 中 → middleware 正确设置 → 读取 user 目录 → 文件不存在
```

两个阶段的目录不一致导致了 404。

### 为什么 API 模式不受影响

`ServerlessApiService`（API/在线服务模式）直接从请求的 `extra_data` 中提取 `user_id` 并传递给执行引擎（`serverless_api_service.py:150-151`），不经过 ComfyUI 的 prompt queue，因此不存在此问题。

## 3. 修复方案

在 Agent proxy 中，对 `POST /prompt` 请求，在转发前将 `user_id` 注入到 JSON body 的 `extra_data` 中：

```python
# 对 POST /prompt 请求，将 user_id 注入到 extra_data 中
# 确保 ComfyUI 执行线程能正确获取用户上下文（execution_patch 从 extra_data 读取）
data = request.get_data()
if user_id and path == 'prompt' and request.method == 'POST':
    try:
        json_data = json.loads(data)
        if 'extra_data' not in json_data:
            json_data['extra_data'] = {}
        json_data['extra_data'][constants.HEADER_FUNART_COMFY_USERID.lower()] = user_id
        data = json.dumps(json_data)
    except (json.JSONDecodeError, TypeError):
        pass
```

### 为什么在 Agent 层修复

| 方案 | 优点 | 缺点 |
|------|------|------|
| **Agent proxy 注入 extra_data（采用）** | 最简单，~10 行代码；与 API 模式的处理方式一致；execution_patch 已具备读取能力，无需改动 | 如果直接绕过 Agent 访问 ComfyUI 端口则不生效（但实际部署中不会发生） |
| Plugin 层 patch PromptQueue.put | 自包含在插件内 | 需要依赖 ComfyUI 内部的 PromptQueue 实现细节，版本兼容性风险高 |
| Plugin 层 prompt_id→user_id 映射 | 不修改请求体 | 复杂度高，需要在 server_patch 和 execution_patch 间协调状态 |
| 修改 ComfyUI post_prompt 源码 | 直接解决 | 需要 fork ComfyUI，维护成本极高 |

选择 Agent 层修复是因为：
1. Agent 是**唯一的入口**，所有请求都经过它
2. Agent 已经完成了用户识别（`g.user_id`），只需要把结果传递下去
3. 与 API 模式（`serverless_api_service.py`）处理 `extra_data` 的方式完全一致

## 4. 影响范围

- **与 ComfyUI 版本无关**：v0.3.77 和 v0.16.4 的 `post_prompt` handler 都不会将 HTTP header 复制到 `extra_data`。只要启用多租户模式，所有版本都受影响。
- **仅影响工作站模式**（用户通过浏览器直接使用 ComfyUI UI）：
  - 工作站模式通过 Agent proxy → ComfyUI `/prompt` 端点提交工作流 ✅ 受影响
  - API 模式通过 `ServerlessApiService` 直接调用执行引擎，`extra_data` 已包含 user_id ✅ 不受影响
  - Gateway 模式通过 `HistoryManager` 构造 prompt，`extra_data` 由 `parse_prompt_body` 处理 ✅ 需确认

## 5. 修复 Diff

```diff
# src/code/agent/routes/routes.py

             if user_id:
                 forward_headers[constants.HEADER_FUNART_COMFY_USERID] = user_id

+            # 对 POST /prompt 请求，将 user_id 注入到 extra_data 中
+            # 确保 ComfyUI 执行线程能正确获取用户上下文（execution_patch 从 extra_data 读取）
+            data = request.get_data()
+            if user_id and path == 'prompt' and request.method == 'POST':
+                try:
+                    json_data = json.loads(data)
+                    if 'extra_data' not in json_data:
+                        json_data['extra_data'] = {}
+                    json_data['extra_data'][constants.HEADER_FUNART_COMFY_USERID.lower()] = user_id
+                    data = json.dumps(json_data)
+                except (json.JSONDecodeError, TypeError):
+                    pass
+
             resp = requests.request(
                 method=request.method,
                 url=target_url,
                 headers=forward_headers,
                 params=request.args,
-                data=request.get_data(),
+                data=data,
                 cookies=request.cookies,
                 allow_redirects=False,
                 verify=False
```

## 6. 数据流修复前后对比

### 修复前

```
Browser → Agent (header: user=alice) → ComfyUI (header: user=alice, body.extra_data: {})
                                          ↓
                                    prompt_queue.put(extra_data={})
                                          ↓
                                    [执行线程] user_id = extra_data.get(...) = "default"
                                          ↓
                                    图片 → /output/  (default 目录)
```

### 修复后

```
Browser → Agent (header: user=alice) → ComfyUI (header: user=alice,
                                                  body.extra_data: {x-funart-comfy-userid: alice})
                                          ↓
                                    prompt_queue.put(extra_data={x-funart-comfy-userid: alice})
                                          ↓
                                    [执行线程] user_id = extra_data.get(...) = "alice"
                                          ↓
                                    图片 → /output/users/alice/  ✅
```

## 7. 验证方法

1. 启用 `ENABLE_COMFYUI_MULTI_USER=true`
2. 以用户 A 身份登录 ComfyUI（Basic Auth 或 JWT）
3. 运行一个包含 SaveImage/PreviewImage 节点的工作流
4. 确认：
   - 图片保存到 `output/users/{user_A}/` 目录（而非 `output/`）
   - `/view` 端点成功返回图片，UI 中预览正常
   - 以用户 B 登录，看不到用户 A 的图片（隔离性验证）

## 8. 关联问题

- **BUG-001**（`bugfix-001-dynamicpathproxy-json-serialization.md`）：同属 Multi-User 插件，解决 `DynamicPathProxy` 的 JSON 序列化问题。两个 bug 的根因不同，但都源于 `DynamicPathProxy` 代理对象与 ComfyUI 原生代码的兼容性缺口。
