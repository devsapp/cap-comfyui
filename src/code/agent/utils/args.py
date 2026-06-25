"""
参数解析工具函数
"""
import shlex
from typing import Tuple, List, Set, Dict

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


def filter_allowed_args(parsed_args: List[str], allowed_specs: Dict[str, bool]) -> Tuple[List[str], List[str]]:
    """
    白名单过滤：仅保留 allowed_specs 中的参数，其余排除

    用于 CPU 模式：只放行「CPU 安全」参数，丢弃 GPU 专属参数，避免 ComfyUI 启动失败。
    allowed_specs 的 value 声明该参数是否接收一个值（arity）：
      - False：布尔开关，不保留其后的值 token，并把 `--key=value` 规整为纯 `--key`
               （避免给 store_true 开关传值导致 argparse 启动失败）
      - True：接收一个值，保留紧随其后的值 token，或保留 `--key=value` 整体

    Args:
        parsed_args: 已解析的参数列表
        allowed_specs: 白名单规格 {参数名: 是否接值}

    Returns:
        Tuple[List[str], List[str]]: (放行的参数列表, 被排除的参数名列表)
    """
    valid_args = []
    excluded_args = []

    i = 0
    while i < len(parsed_args):
        arg = parsed_args[i]

        if arg.startswith('--'):
            arg_name = arg.split('=')[0]
            if arg_name in allowed_specs:
                if '=' in arg:
                    # --key=value 形式：接值则保留整体，布尔开关则规整为纯 flag
                    valid_args.append(arg if allowed_specs[arg_name] else arg_name)
                else:
                    valid_args.append(arg)
            else:
                excluded_args.append(arg_name)
            i += 1
        else:
            # 值 token：仅当前一个参数在白名单且声明接值（arity=True）时保留
            if i > 0:
                prev = parsed_args[i - 1]
                prev_name = prev.split('=')[0] if prev.startswith('--') else None
                if prev_name and allowed_specs.get(prev_name):
                    valid_args.append(arg)
            i += 1

    return valid_args, excluded_args


def build_boot_command(
    base_cmd: List[str],
    custom_boot_args: str,
    protected_args: Set[str],
    allowed_args: Dict[str, bool] = None
) -> List[str]:
    """
    构建最终的启动命令

    流程：
    1. 解析用户的自定义启动参数
    2. 若提供 allowed_args（CPU 白名单模式），先收窄到白名单内参数
    3. 过滤掉与系统默认参数冲突的受保护参数
    4. 将允许的自定义参数追加到默认命令后面

    Args:
        base_cmd: 基础启动命令列表（系统默认参数，全部受保护）
        custom_boot_args: 自定义启动参数字符串
        protected_args: 受保护的参数名集合（不允许用户修改）
        allowed_args: 可选白名单规格 {参数名: 是否接值}；非 None 时仅放行白名单内参数（CPU 模式用）。
                      默认 None 表示不启用白名单，GPU 模式行为不变

    Returns:
        List[str]: 最终的启动命令 = 默认命令 + 允许的自定义参数
    """
    # 1. 解析自定义启动参数
    parsed_args = parse_extra_boot_args(custom_boot_args)

    # 2. CPU 白名单收窄（仅当传入 allowed_args 时；GPU 调用不传，跳过此步）
    if allowed_args is not None:
        parsed_args, denied_args = filter_allowed_args(parsed_args, allowed_args)
        if denied_args:
            log("WARNING", f"[CPU_SAFE_BOOT_ARGS] Dropped non-allowlisted arguments in CPU mode: {denied_args}. Only {sorted(allowed_args)} are allowed")

    # 3. 过滤受保护的参数
    valid_args, excluded_args = filter_protected_args(parsed_args, protected_args)
    if excluded_args:
        log("WARNING", f"[CUSTOM_BOOT_ARGS] Provided arguments: {parsed_args}, excluded protected arguments: {excluded_args}, valid arguments: {valid_args}. Protected arguments cannot be overridden")

    # 4. 追加允许的自定义参数到默认命令
    return base_cmd + valid_args

