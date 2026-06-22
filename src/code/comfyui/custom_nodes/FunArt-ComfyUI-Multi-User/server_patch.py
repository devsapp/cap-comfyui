"""
Monkey Patch for Server - User Isolation in HTTP Requests

This module patches ComfyUI's server to automatically extract and set user_id from HTTP headers.
Uses aiohttp middleware for reliable request interception across all aiohttp versions.
"""

from aiohttp import web

from .context import set_current_user, clear_current_user
from .json_sanitize import install_json_sanitize

_hook_installed = False


@web.middleware
async def _user_context_middleware(request: web.Request, handler):
    """
    aiohttp middleware that sets user context for every request.
    Extracts user_id from X-FunArt-Comfy-UserId header.
    """
    user_id = request.headers.get('X-FunArt-Comfy-UserId', 'default')
    set_current_user(user_id)
    try:
        return await handler(request)
    finally:
        clear_current_user()


def install_server_middleware():
    """
    Install aiohttp middleware to extract user_id from HTTP headers.

    Strategy: PromptServer instance is already created by the time custom nodes load,
    so we directly access PromptServer.instance.app and prepend our middleware.

    For aiohttp, middleware can be added after app creation but MUST be added
    before the app is started (before app.freeze()). Since custom nodes load
    before server.start(), this timing is safe.

    Note: This function is safe to call multiple times (idempotent).
    """
    global _hook_installed

    if _hook_installed:
        return

    try:
        import server  # type: ignore

        install_json_sanitize()

        # Save original add_routes method
        _original_add_routes = server.PromptServer.add_routes

        def patched_add_routes(self):
            """
            Patched add_routes - wraps handlers after route registration.
            """
            # Call original add_routes first
            result = _original_add_routes(self)

            # Wrap all route handlers
            wrap_route_handlers(self.app)

            return result

        instance = server.PromptServer.instance
        if instance is None:
            print("[ComfyUI-Multi-User] ⚠️ PromptServer instance not yet created, deferring middleware install")
            _install_via_add_routes_patch(server)
            return

        instance.app.middlewares.insert(0, _user_context_middleware)
        _hook_installed = True
        print(f"[ComfyUI-Multi-User] ✅ User context middleware installed (direct)")

    except Exception as e:
        print(f"[ComfyUI-Multi-User] Server hook 安装失败: {e}")
        import traceback
        traceback.print_exc()


def _install_via_add_routes_patch(server_module):
    """
    Fallback: if PromptServer.instance doesn't exist yet, patch add_routes
    to install middleware when routes are being set up.
    """
    global _hook_installed

    _original_add_routes = server_module.PromptServer.add_routes

    def patched_add_routes(self):
        global _hook_installed
        result = _original_add_routes(self)
        if not _hook_installed:
            self.app.middlewares.insert(0, _user_context_middleware)
            _hook_installed = True
            print(f"[ComfyUI-Multi-User] ✅ User context middleware installed (via add_routes)")
        return result

    server_module.PromptServer.add_routes = patched_add_routes


__all__ = ['install_server_middleware']
