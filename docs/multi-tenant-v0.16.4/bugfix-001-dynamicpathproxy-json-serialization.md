# BUG-001: DynamicPathProxy JSON 序列化错误

| 项目 | 内容 |
|------|------|
| **发现日期** | 2026-05-21 |
| **修复日期** | 2026-05-21 |
| **修复 Commit** | `28e47e7` |
| **严重程度** | P1 — 多租户模式下 ComfyUI UI 无法加载 |
| **影响版本** | 所有启用 `ENABLE_COMFYUI_MULTI_USER=true` 的版本（v0.3.77、v0.16.4 均受影响） |
| **影响范围** | ComfyUI 插件层（`FunArt-ComfyUI-Multi-User`） |
| **修复文件** | `src/code/comfyui/custom_nodes/FunArt-ComfyUI-Multi-User/__init__.py` |

---

## 1. 现象

多租户用户登录 ComfyUI 后，UI 页面无法正常加载节点信息，浏览器控制台/服务端日志报错：

```
TypeError: Object of type DynamicPathProxy is not JSON serializable
```

错误发生在 ComfyUI `server.py` 的 `get_object_info` 端点（line 681），该端点收集所有节点的元数据并返回 JSON。

## 2. 根因分析

### 调用链路

```
GET /object_info
  → ComfyUI server.py:get_object_info()
  → 遍历所有节点类，收集 INPUT_TYPES 等元信息
  → 某些节点的 INPUT_TYPES 包含 folder_paths.get_input_directory() 的返回值
  → Multi-User 插件已将 get_input_directory() 等函数 patch 为返回 DynamicPathProxy
  → json.dumps() 序列化整个结果时遇到 DynamicPathProxy
  → Python json 模块不认识 DynamicPathProxy → TypeError
```

### 技术细节

Multi-User 插件的 `folder_paths_patch.py` 将 `folder_paths.get_input_directory()`、`get_output_directory()`、`get_temp_directory()` 等函数替换为返回 `DynamicPathProxy` 对象的版本。`DynamicPathProxy` 实现了 `__str__`、`__fspath__` 等方法，在大部分场景下表现得像字符串。

但 Python 的 `json.JSONEncoder` **不会**调用 `__str__()` 或 `__fspath__()`，它只序列化原生类型（`str`、`int`、`list`、`dict` 等）。当 `json.dumps()` 遇到 `DynamicPathProxy` 实例时，直接抛出 `TypeError`。

ComfyUI 的 `get_object_info` 端点在收集节点元信息时，某些节点会调用 `folder_paths.get_input_directory()` 作为默认参数值，这个值最终被包含在 `json.dumps()` 的输入中。

## 3. 修复方案

在插件初始化时（`__init__.py`），monkey-patch `json.JSONEncoder.default` 方法，使其遇到 `DynamicPathProxy` 时自动调用 `str()` 转换为真实路径字符串：

```python
import json
from .path_proxy import DynamicPathProxy

_original_json_default = json.JSONEncoder.default

def _json_default_with_proxy(self, obj):
    if isinstance(obj, DynamicPathProxy):
        return str(obj)
    return _original_json_default(self, obj)

json.JSONEncoder.default = _json_default_with_proxy
```

### 为什么选择这个方案

| 方案 | 优点 | 缺点 |
|------|------|------|
| **Patch json.JSONEncoder.default（采用）** | 全局生效，覆盖所有 JSON 序列化路径；无需修改 ComfyUI 源码 | 全局 monkey-patch 有一定侵入性 |
| 让 DynamicPathProxy 继承 str | 与 `contextvars` 动态解析矛盾，str 是不可变的 | 不可行 |
| 修改 ComfyUI server.py | 需要 fork ComfyUI | 维护成本高 |
| 在 aiohttp handler 层转换 | 需要逐个找到所有序列化点 | 遗漏风险大 |

## 4. 影响范围

- **与 ComfyUI 版本无关**：`DynamicPathProxy` 是 Multi-User 插件的实现，`get_object_info` 在各版本 ComfyUI 中都存在且调用 `folder_paths` 函数。
- **仅在 `ENABLE_COMFYUI_MULTI_USER=true` 时触发**：单租户模式不加载插件，`folder_paths` 函数返回原生字符串，不会触发此问题。

## 5. 修复 Diff

```diff
# src/code/comfyui/custom_nodes/FunArt-ComfyUI-Multi-User/__init__.py

+import json
 import os

 from .context import (
     set_current_user,
     get_current_user,
     clear_current_user,
     UserContext,
 )

+from .path_proxy import DynamicPathProxy
 from .folder_paths_patch import install_folder_paths_patch
 ...
         install_server_middleware()
+
+        _original_json_default = json.JSONEncoder.default
+        def _json_default_with_proxy(self, obj):
+            if isinstance(obj, DynamicPathProxy):
+                return str(obj)
+            return _original_json_default(self, obj)
+        json.JSONEncoder.default = _json_default_with_proxy
+
         print(f"[ComfyUI-Multi-User] ✅ 插件已启用并安装成功 (v{__version__})")
```

## 6. 验证方法

1. 启用 `ENABLE_COMFYUI_MULTI_USER=true`
2. 启动 ComfyUI，打开浏览器访问 UI
3. 确认：
   - 日志无 `TypeError: Object of type DynamicPathProxy is not JSON serializable`
   - `/object_info` 端点返回有效 JSON
   - UI 正常加载所有节点信息
