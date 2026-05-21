"""
Monkey Patch for Server - User Isolation in HTTP Requests

This module patches ComfyUI's server to automatically extract and set user_id from HTTP headers.
"""

from .context import set_current_user, clear_current_user
from .json_sanitize import install_json_sanitize

_hook_installed = False
_original_add_routes = None


def install_server_middleware():
    """
    Install server hook to extract user_id from HTTP headers.
    
    Automatically wraps all route handlers to read user_id from request headers.
    
    Note: This function is safe to call multiple times (idempotent).
    """
    global _hook_installed, _original_add_routes

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

        # Replace add_routes method
        server.PromptServer.add_routes = patched_add_routes
        _hook_installed = True

    except Exception as e:
        print(f"[ComfyUI-Multi-User] Server hook 安装失败: {e}")


def wrap_route_handlers(app):
    """
    Wrap all route handlers in the application.
    
    Makes each handler automatically extract user_id from request headers
    and set it in the context.
    
    Design Philosophy:
        - Keep it simple: 只检查标记，够用了
        - contextvars 本身是线程安全的，不需要额外的锁
        - ComfyUI 启动时只调用一次 add_routes，不用担心重复包装
        - 即使万一重复包装，contextvars 也能正确处理（set 多次没问题）
    
    Args:
        app: aiohttp Application instance
    """
    wrapped_count = 0
    skipped_count = 0
    
    for resource in app.router.resources():
        for route in resource:
            try:
                # Get handler
                if not hasattr(route, '_handler'):
                    continue
                
                original_handler = route._handler
                
                # Skip if not callable
                if not callable(original_handler):
                    continue
                
                # Simple check: 如果已经包装过，跳过
                if getattr(original_handler, '_comfyui_user_wrapped', False):
                    skipped_count += 1
                    continue
                
                # Create wrapper - 使用工厂函数确保正确的闭包
                def make_wrapper(handler):
                    """简单的包装器工厂 - 确保每个包装器捕获正确的 handler"""
                    async def wrapped_handler(request):
                        # Extract user_id from headers
                        user_id = request.headers.get('X-FunArt-Comfy-UserId', 'default')
                        
                        # Set in context (contextvars 自动处理线程/协程隔离)
                        set_current_user(user_id)
                        
                        try:
                            return await handler(request)
                        finally:
                            clear_current_user()
                    
                    # Mark as wrapped
                    wrapped_handler._comfyui_user_wrapped = True
                    return wrapped_handler
                
                # Replace handler
                route._handler = make_wrapper(original_handler)
                wrapped_count += 1
                    
            except Exception:
                # 静默失败，不影响其他路由
                continue


__all__ = ['install_server_middleware']
