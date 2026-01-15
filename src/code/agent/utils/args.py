"""
参数解析工具函数
"""
import shlex
from typing import Tuple, List, Set

from utils.logger import log


def parse_extra_boot_args(extra_args_str: str) -> list:
    """
    解析额外的启动参数
    
    支持命令行参数格式: '--preview-method auto --use-pytorch-cross-attention'
    
    Args:
        extra_args_str: 额外参数字符串
        
    Returns:
        list: 解析后的参数列表，例如 ['--preview-method', 'auto', '--use-pytorch-cross-attention']
    """
    if not extra_args_str or not extra_args_str.strip():
        return []
    
    extra_args_str = extra_args_str.strip()
    
    # 使用 shlex 正确处理引号和空格
    try:
        return shlex.split(extra_args_str)
    except Exception as e:
        # 如果 shlex 解析失败，简单按空格分割
        log("WARNING", f"[PARSE_BOOT_ARGS] Failed to parse arguments with shlex: {e}. Falling back to simple split. Arguments: {extra_args_str}")
        return extra_args_str.split()


def filter_protected_args(parsed_args: List[str], protected_args: Set[str]) -> Tuple[List[str], List[str]]:
    """
    过滤掉受保护的参数
    
    Args:
        parsed_args: 已解析的参数列表
        protected_args: 受保护的参数名集合
        
    Returns:
        Tuple[List[str], List[str]]: (有效的参数列表, 被排除的参数名列表)
    """
    valid_args = []
    excluded_args = []
    
    i = 0
    while i < len(parsed_args):
        arg = parsed_args[i]
        
        if arg.startswith('--'):
            # 提取参数名（处理 --key=value 格式）
            arg_name = arg.split('=')[0]
            
            if arg_name in protected_args:
                # 这是受保护的参数，跳过它
                excluded_args.append(arg_name)
                i += 1
                continue
            else:
                # 不是受保护的参数，保留
                valid_args.append(arg)
                i += 1
        else:
            # 这是一个值参数，只有在前一个参数未被过滤时才添加
            if i > 0:
                prev_arg_name = parsed_args[i-1].split('=')[0] if parsed_args[i-1].startswith('--') else None
                if prev_arg_name and prev_arg_name not in protected_args:
                    valid_args.append(arg)
            i += 1
    
    return valid_args, excluded_args


def build_boot_command(
    base_cmd: List[str],
    custom_boot_args: str,
    protected_args: Set[str]
) -> List[str]:
    """
    构建最终的启动命令
    
    流程：
    1. 解析用户的自定义启动参数
    2. 过滤掉与系统默认参数冲突的受保护参数
    3. 将允许的自定义参数追加到默认命令后面
    
    Args:
        base_cmd: 基础启动命令列表（系统默认参数，全部受保护）
        custom_boot_args: 自定义启动参数字符串
        protected_args: 受保护的参数名集合（不允许用户修改）
        
    Returns:
        List[str]: 最终的启动命令 = 默认命令 + 允许的自定义参数
    """
    # 1. 解析自定义启动参数
    parsed_args = parse_extra_boot_args(custom_boot_args)
    
    # 2. 过滤受保护的参数
    valid_args, excluded_args = filter_protected_args(parsed_args, protected_args)
    if excluded_args:
        log("WARNING", f"[CUSTOM_BOOT_ARGS] Provided arguments: {parsed_args}, excluded protected arguments: {excluded_args}, valid arguments: {valid_args}. Protected arguments cannot be overridden")
    
    # 3. 追加允许的自定义参数到默认命令
    return base_cmd + valid_args

