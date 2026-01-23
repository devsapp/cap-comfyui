"""
Monkey Patch for Execution - User Isolation in Workflow Execution

This module patches PromptExecutor.execute to support cross-thread user_id propagation.
It ensures that the correct user context is maintained during workflow execution.
"""

from .context import set_current_user, clear_current_user

# Store original function
_original_prompt_executor_execute = None


def _patched_prompt_executor_execute(self, prompt, prompt_id, extra_data=None, execute_outputs=None):
    """
    Patched version of PromptExecutor.execute.
    
    Extracts user_id from extra_data and sets it in the current thread context.
    
    Args:
        self: PromptExecutor instance
        prompt: Workflow prompt data
        prompt_id: Unique prompt identifier
        extra_data: Additional data, may contain 'X-FunArt-Comfy-UserId'
        execute_outputs: Outputs to execute
        
    Returns:
        Result from the original execute function
    """
    extra_data = extra_data or {}
    execute_outputs = execute_outputs or []
    
    # 从 extra_data 中提取 user_id
    # 注意：使用小写的 key（与 HTTP header 保持一致）
    user_id = extra_data.get('x-funart-comfy-userid', 'default')
    
    set_current_user(user_id)
    
    try:
        return _original_prompt_executor_execute(self, prompt, prompt_id, extra_data, execute_outputs)
    finally:
        clear_current_user()


def install_execution_patch():
    """
    Install execution monkey patch.
    
    Replaces PromptExecutor.execute with a patched version that handles user context.
    """
    global _original_prompt_executor_execute
    
    try:
        import execution  # type: ignore
        _original_prompt_executor_execute = execution.PromptExecutor.execute
        execution.PromptExecutor.execute = _patched_prompt_executor_execute
    except Exception as e:
        print(f"[ComfyUI-Multi-User] ❌ Execution patch 安装失败: {e}")
        import traceback
        traceback.print_exc()


__all__ = ['install_execution_patch']
