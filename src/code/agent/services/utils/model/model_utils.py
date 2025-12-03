"""
模型准备工具
提供模型软链接相关功能
"""

import os
from typing import Optional
from utils.logger import log
from utils import file_ops


def prepare_models(
    target_dir: str,
    user_models_dir: Optional[str] = None,
    shared_models_dir: Optional[str] = "/mnt/shared/models",
    enable_watch: bool = True
) -> None:
    """
    准备模型目录：将平台共享模型和用户模型链接到目标目录
    
    优先级：用户模型 > 平台共享模型（重名时用户模型覆盖平台模型）
    
    特殊情况：
    - 如果 shared_models_dir 不存在且 user_models_dir 存在，直接将 target_dir 软链接到 user_models_dir
    - 如果 shared_models_dir 存在，则逐个链接文件（shared 先，user 后）
    
    Args:
        target_dir: 目标模型目录（如 /root/comfyui/models）
        user_models_dir: 用户模型目录（可选，如 /mnt/auto/models）
        shared_models_dir: 平台共享模型目录（可选，默认 /mnt/shared/models）
        enable_watch: 是否启用实时监听（默认 True，仅在非整体软链接时生效）
    
    Example:
        prepare_models(
            target_dir="/root/comfyui/models",
            user_models_dir="/mnt/auto/models",
            shared_models_dir="/mnt/shared/models",
            enable_watch=True
        )
    """
    log("INFO", f"Preparing models: target={target_dir}, user={user_models_dir or 'None'}, shared={shared_models_dir or 'None'}, watch={enable_watch}")
    
    shared_models_exists = shared_models_dir and os.path.isdir(shared_models_dir)
    user_models_exists = user_models_dir and os.path.isdir(user_models_dir)
    
    # 特殊情况：如果没有平台共享模型，但有用户模型，直接将整个 models 目录软链接到用户模型
    if not shared_models_exists and user_models_exists:
        log("DEBUG", "Shared models not found, creating direct symlink to user models")
        file_ops.create_symlink(
            source_path=user_models_dir,
            link_path=target_dir,
            force=True  # 强制替换已存在的目录
        )
        log("INFO", "Model preparation completed successfully (direct symlink)")
        # 注意：整体软链接时不需要启动监听器，因为用户直接操作的就是 user_models_dir
        return
    
    # 正常情况：逐个文件链接
    # 确保目标目录存在
    os.makedirs(target_dir, exist_ok=True)
    
    # 步骤1: 先链接平台共享模型
    if shared_models_exists:
        _link_directory(shared_models_dir, target_dir, "shared")
    else:
        log("DEBUG", f"Shared model directory not found, skipping")
    
    # 步骤2: 再链接用户模型（覆盖重名文件）
    if user_models_exists:
        _link_directory(user_models_dir, target_dir, "user", override=True)
    else:
        log("DEBUG", f"User model directory not found or not configured, skipping")
    
    log("INFO", "Model preparation completed successfully")
    
    # 步骤3: 启动用户模型实时监听（如果启用）
    if enable_watch and user_models_exists:
        try:
            from services.utils.model.model_watcher import start_model_watcher
            start_model_watcher(
                comfyui_models_dir=target_dir,
                user_models_dir=user_models_dir
            )
            log("DEBUG", "Model watcher started")
        except ImportError as e:
            log("WARNING", f"Cannot start model watcher (watchdog not installed): {e}")
        except Exception as e:
            log("ERROR", f"Failed to start model watcher: {e}")


def _link_directory(source_dir: str, target_dir: str, description: str, override: bool = False) -> None:
    """
    递归链接目录中的所有内容
    
    Args:
        source_dir: 源目录
        target_dir: 目标目录
        description: 描述（用于日志）
        override: 是否覆盖已存在的链接
    """
    log("DEBUG", f"Linking {description} models from {source_dir}")
    
    for item_name in os.listdir(source_dir):
        source_path = os.path.join(source_dir, item_name)
        target_path = os.path.join(target_dir, item_name)
        
        if os.path.isdir(source_path):
            # 目录：确保存在，然后递归处理
            os.makedirs(target_path, exist_ok=True)
            _link_directory(source_path, target_path, description, override)
        else:
            # 文件：创建软链接
            _create_link(source_path, target_path, item_name, override)


def _create_link(source_path: str, target_path: str, item_name: str, override: bool = False) -> None:
    """
    创建单个文件的软链接
    
    Args:
        source_path: 源文件路径
        target_path: 目标链接路径
        item_name: 文件名（用于日志）
        override: 是否覆盖已存在的链接
    """
    if os.path.exists(target_path) or os.path.islink(target_path):
        if os.path.islink(target_path):
            if override:
                # 覆盖旧链接
                os.unlink(target_path)
                os.symlink(source_path, target_path)
                log("DEBUG", f"Overridden: {item_name}")
            else:
                log("DEBUG", f"Skipped existing: {item_name}")
        else:
            # 实体文件不覆盖
            log("DEBUG", f"Skipped real file: {item_name}")
    else:
        # 创建新链接
        os.symlink(source_path, target_path)
        log("DEBUG", f"Linked: {item_name}")

