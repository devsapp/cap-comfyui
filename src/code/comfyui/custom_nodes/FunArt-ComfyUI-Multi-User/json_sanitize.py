"""
JSON 序列化辅助 - 将 DynamicPathProxy 转为字符串

ComfyUI /object_info 经 aiohttp.web.json_response → json.dumps；
仅 patch web.json_response 不够（server 模块可能已绑定旧引用）。
同时 patch json.JSONEncoder.default，确保所有标准 json.dumps 都能序列化 Proxy。
"""

import json

from aiohttp import web

from .path_proxy import DynamicPathProxy

_installed = False
_original_encoder_default = None
_original_json_response = None


def sanitize_for_json(obj):
    """递归将 DynamicPathProxy 转为 str（按当前 user 上下文解析路径）。"""
    if isinstance(obj, DynamicPathProxy):
        return str(obj)
    if isinstance(obj, dict):
        return {sanitize_for_json(k): sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_for_json(x) for x in obj]
    return obj


def install_json_sanitize():
    """
    安装 JSON 序列化补丁（幂等）。

    1. json.JSONEncoder.default — 覆盖 aiohttp 内部的 json.dumps(data)
    2. aiohttp.web.json_response — 双保险，先 sanitize 再 dumps
    3. server.web.json_response — 若 server 已 import，同步替换
    """
    global _installed, _original_encoder_default, _original_json_response

    if _installed:
        return

    _original_encoder_default = json.JSONEncoder.default

    def patched_encoder_default(self, o):
        if isinstance(o, DynamicPathProxy):
            return str(o)
        return _original_encoder_default(self, o)

    json.JSONEncoder.default = patched_encoder_default

    _original_json_response = web.json_response

    def json_response_safe(data, **kwargs):
        return _original_json_response(sanitize_for_json(data), **kwargs)

    json_response_safe._comfyui_user_json_patched = True
    web.json_response = json_response_safe

    try:
        import server  # type: ignore

        server.web.json_response = json_response_safe
    except ImportError:
        pass

    _installed = True
    print("[ComfyUI-Multi-User] JSON sanitize 已安装 (JSONEncoder.default + json_response)")


__all__ = ['sanitize_for_json', 'install_json_sanitize']
