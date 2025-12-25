"""
模型准备工具
提供模型软链接相关功能
"""

import os
import shutil
from typing import Optional
from utils.logger import log
from utils import file_ops
import constants


def prepare_models(
    target_dir: str,
    user_models_dir: Optional[str] = None,
    shared_models_dir: Optional[str] = constants.SHARED_MODELS_DIR,
    watch_comfyui_dir: bool = True,
    watch_user_dir: bool = True
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
        watch_comfyui_dir: 是否监听 ComfyUI 目录变化并同步到用户目录（默认 True）
        watch_user_dir: 是否监听用户目录变化并同步到 ComfyUI 目录（默认 True）
    
    Example:
        prepare_models(
            target_dir="/root/comfyui/models",
            user_models_dir="/mnt/auto/models",
            shared_models_dir="/mnt/shared/models",
            watch_comfyui_dir=True,
            watch_user_dir=True
        )
    """
    log("INFO", f"Preparing models: target={target_dir}, user={user_models_dir or 'None'}, shared={shared_models_dir or 'None'}")
    
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
    
    # 步骤2: 再链接用户模型（覆盖重名 item）
    if user_models_exists:
        _link_directory(user_models_dir, target_dir, "user", override=True)
    else:
        log("DEBUG", f"User model directory not found or not configured, skipping")
    
    log("INFO", "Model preparation completed successfully")
    
    # 步骤3: 启动用户模型实时监听
    if user_models_exists:
        try:
            from services.model.watcher import start_model_watcher
            start_model_watcher(
                comfyui_models_dir=target_dir,
                user_models_dir=user_models_dir,
                watch_comfyui_dir=watch_comfyui_dir,
                watch_user_dir=watch_user_dir
            )
            log("DEBUG", "Model watcher started")
        except ImportError as e:
            log("WARNING", f"Cannot start model watcher (watchdog not installed): {e}")
        except Exception as e:
            log("ERROR", f"Failed to start model watcher: {e}")


def _link_directory(
    source_dir: str, 
    target_dir: str, 
    description: str, 
    override: bool = False
) -> None:
    """
    链接模型目录的两层结构
    
    第一层：处理 models 根目录下的文件和目录
    - 一级文件：创建软链接
    - 一级目录（模型类型目录）：创建目录，然后处理其内容
    
    第二层：对每个类型目录内的 item（文件或目录）创建软链接（原子单元）
    
    Args:
        source_dir: 源模型目录（如 /mnt/auto/models）
        target_dir: 目标模型目录（如 /root/comfyui/models）
        description: 描述（用于日志）
        override: 是否覆盖已存在的链接
    """
    log("DEBUG", f"Linking {description} models from {source_dir}")
    
    # 第一层：遍历 models 根目录下的所有 item
    for item in os.listdir(source_dir):
        try:
            source_path = os.path.join(source_dir, item)
            target_path = os.path.join(target_dir, item)
            
            if os.path.isdir(source_path):
                # 一级目录（模型类型目录）：创建对应目录，然后处理其内容
                os.makedirs(target_path, exist_ok=True)
                
                # 第二层：遍历类型目录内的所有原子 item
                for sub_item in os.listdir(source_path):
                    try:
                        source_sub_path = os.path.join(source_path, sub_item)
                        target_sub_path = os.path.join(target_path, sub_item)
                        
                        # 二级 item：文件或目录，都整体软链接
                        _create_link(source_sub_path, target_sub_path, f"{item}/{sub_item}", override)
                    except Exception as e:
                        log("ERROR", f"Failed to link {description} item '{item}/{sub_item}': {e}")
                        continue
            else:
                # 一级文件：直接创建软链接
                _create_link(source_path, target_path, item, override)
                    
        except Exception as e:
            log("ERROR", f"Failed to process {description} item '{item}': {e}")
            continue


def _create_link(
    source_path: str, 
    target_path: str, 
    item_name: str, 
    override: bool = False
) -> None:
    """
    创建原子item（文件或目录）的软链接
    
    Args:
        source_path: 源路径（文件或目录）
        target_path: 目标链接路径
        item_name: item 名称（用于日志）
        override: 是否覆盖已存在的链接
    
    Raises:
        Exception: 如果链接创建/覆盖失败
    """
    try:
        # 判断源是否是目录
        is_directory = os.path.isdir(source_path)
        item_type = "directory" if is_directory else "file"
        
        if os.path.exists(target_path) or os.path.islink(target_path):
            if os.path.islink(target_path):
                if override:
                    # 覆盖旧链接
                    os.unlink(target_path)
                    os.symlink(source_path, target_path)
                    log("DEBUG", f"{item_type.capitalize()} link overridden: {item_name}")
                else:
                    log("DEBUG", f"Skipped existing {item_type} link: {item_name}")
            elif os.path.isdir(target_path):
                if override:
                    # 如果目标是实体目录，删除后创建软链接
                    shutil.rmtree(target_path)
                    os.symlink(source_path, target_path)
                    log("DEBUG", f"Real directory replaced with link: {item_name}")
                else:
                    log("DEBUG", f"Skipped real directory: {item_name}")
            else:
                # 目标是实体文件
                if override and is_directory:
                    # 如果源是目录，目标是文件，删除文件后创建目录链接
                    os.remove(target_path)
                    os.symlink(source_path, target_path)
                    log("DEBUG", f"Real file replaced with directory link: {item_name}")
                else:
                    log("DEBUG", f"Skipped real file: {item_name}")
        else:
            # 创建新链接
            os.symlink(source_path, target_path)
            log("DEBUG", f"{item_type.capitalize()} linked: {item_name}")
    except Exception as e:
        log("ERROR", f"Unexpected error when linking {item_type} '{item_name}': {e}")
        raise


def _is_atomic_item(base_dir: str, item_path: str) -> bool:
    """
    判断 item_path 是否是原子模型 item
    
    原子模型 item 包括：
    1. 深度=1 的文件（models/config.yaml）
    2. 深度=2 的文件或目录（models/checkpoints/model.ckpt 或 models/checkpoints/flux/）
    
    注意：深度=1 的目录（模型类型目录）不是原子 item
    
    Args:
        base_dir: 模型根目录（如 /root/comfyui/models）
        item_path: 要判断的路径
    
    Returns:
        bool: 如果是原子模型 item 返回 True
        
    Examples:
        models/checkpoints/ -> False (深度1的目录，不是原子item)
        models/config.yaml -> True (深度1的文件)
        models/checkpoints/model.ckpt -> True (深度2的文件)
        models/checkpoints/flux/ -> True (深度2的目录)
        models/checkpoints/sdxl/base/model.ckpt -> False (深度3+)
    """
    try:
        rel_path = os.path.relpath(item_path, base_dir)
        parts = [p for p in rel_path.split(os.sep) if p]  # 过滤空字符串
        depth = len(parts)
        
        if depth == 1:
            # 深度=1：只有文件是原子 item，目录不是
            return os.path.isfile(item_path)
        elif depth == 2:
            # 深度=2：文件和目录都是原子 item
            return True
        else:
            # 深度>2 或 depth=0：不是原子 item
            return False
    except ValueError:
        # 如果路径不在 base_dir 下，返回 False
        return False


def _get_item_depth(base_dir: str, item_path: str) -> int:
    """
    获取 item 相对于 base_dir 的深度
    
    Args:
        base_dir: 基础目录
        item_path: item 路径
    
    Returns:
        int: 深度级别（1, 2, 3...），如果不在 base_dir 下返回 0
    
    Examples:
        models/checkpoints/ -> 1
        models/checkpoints/model.ckpt -> 2
        models/checkpoints/flux/model.ckpt -> 3
    """
    try:
        rel_path = os.path.relpath(item_path, base_dir)
        parts = [p for p in rel_path.split(os.sep) if p]
        return len(parts)
    except ValueError:
        return 0

