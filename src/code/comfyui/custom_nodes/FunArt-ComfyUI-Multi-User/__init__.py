"""
ComfyUI Multi-User Support Plugin
==================================

A ComfyUI plugin that provides per-user asset directory isolation.
Enables multi-user support by automatically segregating input/output/temp directories.

Features:
    - Per-user directory isolation (input/output/temp/user)
    - Automatic cache isolation between users
    - HTTP request integration via X-FunArt-Comfy-UserId header
    - Thread-safe and async-safe user context management
    - Zero dependencies beyond ComfyUI core

Usage:
    1. Set environment variable: ENABLE_COMFYUI_MULTI_USER=true
    2. Start ComfyUI: python main.py
    3. Send requests with X-FunArt-Comfy-UserId header or x-funart-comfy-userid in extra_data

Example:
    ```python
    from FunArt-ComfyUI-Multi-User.core.context import UserContext
    
    with UserContext("user_001"):
        # All operations use user_001's directories
        execute_workflow(workflow_data)
    ```

Author: FunArt Team
License: MIT
Version: 1.0.0
"""

import json
import os

from .context import (
    set_current_user,
    get_current_user,
    clear_current_user,
    UserContext,
)

from .path_proxy import DynamicPathProxy
from .folder_paths_patch import install_folder_paths_patch
from .execution_patch import install_execution_patch
from .cache_signature_patch import install_cache_signature_patch
from .server_patch import install_server_middleware

# Plugin metadata
__version__ = "1.0.0"
__author__ = "FunArt Team"
__license__ = "MIT"

# ComfyUI standard exports
NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

# Check if plugin is enabled via environment variable
ENABLE_PLUGIN = os.getenv('ENABLE_COMFYUI_MULTI_USER', 'false').lower() == 'true'

if ENABLE_PLUGIN:
    try:
        # Install all patches
        install_folder_paths_patch()
        install_execution_patch()
        install_cache_signature_patch()
        install_server_middleware()

        _original_json_default = json.JSONEncoder.default
        def _json_default_with_proxy(self, obj):
            if isinstance(obj, DynamicPathProxy):
                return str(obj)
            return _original_json_default(self, obj)
        json.JSONEncoder.default = _json_default_with_proxy

        print(f"[ComfyUI-Multi-User] ✅ 插件已启用并安装成功 (v{__version__})")
    except Exception as e:
        print(f"[ComfyUI-Multi-User] ❌ 插件安装失败: {e}")
        import traceback
        traceback.print_exc()
else:
    print("[ComfyUI-Multi-User] ⚠️ 插件未启用")

# Export public API
__all__ = [
    'NODE_CLASS_MAPPINGS',
    'NODE_DISPLAY_NAME_MAPPINGS',
    'set_current_user',
    'get_current_user',
    'clear_current_user',
    'UserContext',
    '__version__',
]
