"""
Monkey Patch for folder_paths - User Asset Directory Isolation

Features:
    1. Intercept folder_paths.get_*_directory functions
    2. Return user-specific asset directories based on current user ID
    3. Support automatic isolation for input/output/temp/user directories
    4. Use dynamic path proxy to solve node instance caching issues
"""

import os
import threading

from .context import get_current_user
from .path_proxy import DynamicPathProxy


# Store original functions
_original_functions = {}
_original_get_save_image_path = None

# 目录创建缓存和锁
_dir_cache = set()
_dir_lock = threading.Lock()


def _get_user_directory(base_dir: str, user_id: str) -> str:
    """
    Get user-specific directory.

    Args:
        base_dir: Base directory path
        user_id: User identifier

    Returns:
        User directory path in format: base_dir/users/{user_id}
    """
    if user_id == 'default':
        return base_dir

    user_dir = os.path.join(base_dir, "users", user_id)
    
    # 使用缓存避免重复创建，提高性能
    if user_dir not in _dir_cache:
        with _dir_lock:
            # 双重检查
            if user_dir not in _dir_cache:
                os.makedirs(user_dir, exist_ok=True)
                _dir_cache.add(user_dir)
    
    return user_dir


def _patched_get_input_directory():
    """
    Patched version of get_input_directory.
    
    Returns DynamicPathProxy to solve node instance caching issues.
    
    Returns:
        DynamicPathProxy that computes user-specific input directory on use
    """
    return DynamicPathProxy(_patched_get_input_directory_real)


def _patched_get_input_directory_real():
    """
    Actual path computation function for input directory.
    
    Returns:
        User-specific input directory path
    """
    base_dir = _original_functions['get_input_directory']()
    user_id = get_current_user()
    return _get_user_directory(base_dir, user_id)


def _patched_get_output_directory():
    """
    Patched version of get_output_directory.
    
    Returns DynamicPathProxy to solve node instance caching issues.
    
    Returns:
        DynamicPathProxy that computes user-specific output directory on use
    """
    return DynamicPathProxy(_patched_get_output_directory_real)


def _patched_get_output_directory_real():
    """
    Actual path computation function for output directory.
    
    Returns:
        User-specific output directory path
    """
    base_dir = _original_functions['get_output_directory']()
    user_id = get_current_user()
    return _get_user_directory(base_dir, user_id)


def _patched_get_temp_directory():
    """
    Patched version of get_temp_directory.
    
    Returns DynamicPathProxy to solve node instance caching issues.
    
    Returns:
        DynamicPathProxy that computes user-specific temp directory on use
    """
    return DynamicPathProxy(_patched_get_temp_directory_real)


def _patched_get_temp_directory_real():
    """
    Actual path computation function for temp directory.
    
    Returns:
        User-specific temp directory path
    """
    base_dir = _original_functions['get_temp_directory']()
    user_id = get_current_user()
    return _get_user_directory(base_dir, user_id)


def _patched_get_user_directory():
    """
    Patched version of get_user_directory.
    
    Returns user-specific directory for storing workflows and user data.
    Compatible with ComfyUI's --multi-user mode.
    
    Returns:
        User-specific user directory path
    """
    user_id = get_current_user()
    base_dir = _original_functions['get_user_directory']()

    # Check if running with --multi-user flag
    try:
        from comfy import cli_args  # type: ignore
        if cli_args.args.multi_user:
            return base_dir
    except (ImportError, AttributeError):
        pass

    return _get_user_directory(base_dir, user_id)


def _patched_get_save_image_path(filename_prefix: str, output_dir, image_width=0, image_height=0):
    """
    Patched version of get_save_image_path.
    
    Ensures output_dir is properly converted to string before processing.
    
    Args:
        filename_prefix: Prefix for the saved image filename
        output_dir: Output directory (may be DynamicPathProxy or string)
        image_width: Width of the image
        image_height: Height of the image
        
    Returns:
        Result from original get_save_image_path
    """
    # Convert output_dir to string
    if hasattr(output_dir, '__fspath__'):
        output_dir = os.fspath(output_dir)
    elif not isinstance(output_dir, str):
        output_dir = str(output_dir)

    return _original_get_save_image_path(filename_prefix, output_dir, image_width, image_height)


def install_folder_paths_patch():
    """
    Install folder_paths monkey patch.
    
    Replaces folder_paths module's directory retrieval functions to automatically
    return user-specific subdirectories based on user ID.
    """
    global _original_get_save_image_path
    
    try:
        import folder_paths  # type: ignore
    except ImportError:
        print("[ComfyUI-Multi-User] Folder paths 模块未找到，跳过安装")
        return

    # Save original functions
    _original_functions['get_input_directory'] = folder_paths.get_input_directory
    _original_functions['get_output_directory'] = folder_paths.get_output_directory
    _original_functions['get_temp_directory'] = folder_paths.get_temp_directory
    _original_functions['get_user_directory'] = folder_paths.get_user_directory
    _original_get_save_image_path = folder_paths.get_save_image_path

    # Replace with patched versions
    folder_paths.get_input_directory = _patched_get_input_directory
    folder_paths.get_output_directory = _patched_get_output_directory
    folder_paths.get_temp_directory = _patched_get_temp_directory
    folder_paths.get_user_directory = _patched_get_user_directory
    folder_paths.get_save_image_path = _patched_get_save_image_path


__all__ = ['install_folder_paths_patch']
