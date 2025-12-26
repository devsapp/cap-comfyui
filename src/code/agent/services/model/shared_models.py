"""
共享模型配置模块
使用 ComfyUI 原生的 extra_model_paths.yaml 配置共享模型路径
"""

import os
from typing import Optional
from utils.logger import log
import constants


def setup_shared_models(
    comfyui_dir: str = constants.COMFYUI_DIR,
    shared_models_dir: str = constants.SHARED_MODELS_DIR,
    config_key: str = "funart_shared_models"
) -> None:
    """
    设置 ComfyUI 的 extra_model_paths.yaml 配置文件，配置共享模型路径
    
    功能：
    1. 检查 /root/comfyui/extra_model_paths.yaml 是否存在
    2. 如果不存在，创建文件并添加共享模型配置
    3. 如果存在且已有指定配置键，则更新该配置（支持新增模型目录的情况）
    4. 如果存在但没有该配置，则追加到文件末尾
    5. 自动遍历 shared_models_dir 的一级目录并生成配置项
    
    Args:
        comfyui_dir: ComfyUI 安装目录，默认使用 constants.COMFYUI_DIR
        shared_models_dir: 共享模型目录，默认使用 constants.SHARED_MODELS_DIR
        config_key: 配置键名，默认 funart_shared_models
    
    Example:
        setup_shared_models(
            comfyui_dir="/root/comfyui",
            shared_models_dir="/mnt/shared/models",
            config_key="funart_shared_models"
        )
    """
    log("INFO", "[SharedModels] Setting up extra_model_paths.yaml configuration...")
    
    # 检查 ComfyUI 目录是否存在
    if not os.path.isdir(comfyui_dir):
        log("WARNING", f"[SharedModels] ComfyUI directory not found: {comfyui_dir}, skipping extra_model_paths setup")
        return
    
    # 检查共享模型目录是否存在
    if not os.path.isdir(shared_models_dir):
        log("INFO", f"[SharedModels] Shared models directory not found: {shared_models_dir}, skipping extra_model_paths setup")
        return
    
    extra_paths_file = os.path.join(comfyui_dir, "extra_model_paths.yaml")
    
    # 生成配置内容
    yaml_block = _generate_config(shared_models_dir, config_key)
    
    # 情况1: extra_model_paths.yaml 文件不存在，创建新文件
    if not os.path.exists(extra_paths_file):
        log("INFO", f"[SharedModels] Creating new extra_model_paths.yaml file at {extra_paths_file}")
        _write_yaml_block(extra_paths_file, yaml_block, append=False)
        log("INFO", "[SharedModels] Successfully created extra_model_paths.yaml with shared models configuration")
        return
    
    # 情况2: 文件存在，检查是否已有指定配置
    if _config_exists(extra_paths_file, config_key):
        log("INFO", f"[SharedModels] Configuration '{config_key}' already exists, updating with latest model directories")
        _update_config_file(extra_paths_file, config_key, yaml_block)
        log("INFO", "[SharedModels] Successfully updated shared models configuration in extra_model_paths.yaml")
        return
    
    # 情况3: 文件存在但没有指定配置，追加配置
    log("INFO", f"[SharedModels] Appending '{config_key}' configuration to extra_model_paths.yaml")
    _write_yaml_block(extra_paths_file, yaml_block, append=True)
    log("INFO", "[SharedModels] Successfully appended shared models configuration to extra_model_paths.yaml")


def _generate_config(shared_models_dir: str, config_key: str) -> str:
    """
    生成 extra_model_paths.yaml 配置内容
    
    Args:
        shared_models_dir: 共享模型目录路径
        config_key: 配置键名
    
        生成的 extra_model_paths.yaml 示例：
        假设 /mnt/shared/models 包含以下子目录：
        - checkpoints
        - loras
        - vae
        - controlnet
        
        生成的配置：
        funart_shared_models:
            base_path: /mnt/shared/models
            is_default: false
            
            checkpoints: checkpoints/
            controlnet: controlnet/
            loras: loras/
            vae: vae/
            
    Returns:
        生成的 YAML 配置字符串
    """
    lines = [
        f"{config_key}:",
        f"    base_path: {shared_models_dir}",
        "    is_default: false",
        ""
    ]
    
    # 遍历共享模型目录的一级子目录
    try:
        if os.path.isdir(shared_models_dir):
            # 获取所有一级子目录并排序（保证输出稳定）
            subdirs = []
            for item in os.listdir(shared_models_dir):
                item_path = os.path.join(shared_models_dir, item)
                if os.path.isdir(item_path):
                    subdirs.append(item)
            
            subdirs.sort()
            
            # 为每个子目录生成配置项
            for subdir in subdirs:
                lines.append(f"    {subdir}: {subdir}/")
            
            log("DEBUG", f"[SharedModels] Found {len(subdirs)} model subdirectories in {shared_models_dir}")
    except Exception as e:
        log("ERROR", f"[SharedModels] Error scanning shared models directory: {e}")
    
    return "\n".join(lines)


def _config_exists(file_path: str, config_key: str) -> bool:
    """
    检查配置文件中是否已存在指定配置键
    
    Args:
        file_path: 配置文件路径
        config_key: 配置键名
    
    Returns:
        True 如果配置已存在，否则 False
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            # 检查是否有以配置键开头的行（顶级配置）
            for line in content.splitlines():
                if line.strip().startswith(f"{config_key}:"):
                    return True
        return False
    except Exception as e:
        log("ERROR", f"[SharedModels] Error reading config file: {e}")
        return False


def _write_yaml_block(file_path: str, yaml_block: str, append: bool = False) -> None:
    """
    写入或追加 YAML 配置块到文件
    
    Args:
        file_path: 配置文件路径
        yaml_block: YAML 配置块内容
        append: True 追加到文件末尾，False 创建新文件（覆盖），默认 False
    """
    try:
        mode = 'a' if append else 'w'
        with open(file_path, mode, encoding='utf-8') as f:
            # 追加模式需要先加空行分隔
            if append:
                f.write("\n")
            f.write(yaml_block)
            f.write("\n")
    except Exception as e:
        action = "appending to" if append else "writing"
        log("ERROR", f"[SharedModels] Error {action} config file: {e}")
        raise


def _update_config_file(file_path: str, config_key: str, yaml_block: str) -> None:
    """
    更新配置文件中已存在的配置块
    
    策略：
    1. 删除旧配置块
    2. 追加新配置块到文件末尾
    
    Args:
        file_path: 配置文件路径
        config_key: 配置键名
        yaml_block: 新的 YAML 配置块内容
    """
    try:
        # 1. 删除旧配置块
        if not _remove_config_block(file_path, config_key):
            log("WARNING", f"[SharedModels] Configuration '{config_key}' not found in file, cannot update")
            return
        
        # 2. 追加新配置块
        _write_yaml_block(file_path, yaml_block, append=True)
        
        log("DEBUG", f"[SharedModels] Updated configuration block '{config_key}'")
        
    except Exception as e:
        log("ERROR", f"[SharedModels] Error updating config file: {e}")
        raise


def _remove_config_block(file_path: str, config_key: str) -> bool:
    """
    从配置文件中删除指定的配置块
    
    Args:
        file_path: 配置文件路径
        config_key: 配置键名
    
    Returns:
        True 如果找到并删除成功，False 如果未找到配置块
    """
    try:
        # 读取所有行
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # 找到配置块的起始和结束位置
        start_idx = -1
        end_idx = -1
        
        for i, line in enumerate(lines):
            # 找到配置块起始行（顶级键，不以空格开头）
            if line.strip().startswith(f"{config_key}:"):
                start_idx = i
                # 从下一行开始查找配置块的结束位置
                for j in range(i + 1, len(lines)):
                    # 遇到下一个顶级键（非空行且不以空格开头）或文件结束
                    if lines[j].strip() and not lines[j].startswith((' ', '\t')):
                        end_idx = j
                        break
                else:
                    # 到达文件末尾
                    end_idx = len(lines)
                break
        
        if start_idx == -1:
            return False
        
        # 删除配置块：保留前面和后面的内容
        new_lines = lines[:start_idx] + lines[end_idx:]
        
        # 写回文件
        with open(file_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        
        log("DEBUG", f"[SharedModels] Removed configuration block '{config_key}' (lines {start_idx+1}-{end_idx})")
        return True
        
    except Exception as e:
        log("ERROR", f"[SharedModels] Error removing config block: {e}")
        raise