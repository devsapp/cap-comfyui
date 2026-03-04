"""
版本冲突裁决模块。

合并多个插件的 requirements.txt 时，同一个包可能出现多次且版本要求不同。
本模块提供纯函数（无副作用、无 I/O）来解析版本约束并裁决最终使用哪个版本规范。

裁决优先级（由高到低）：
  1. 简单策略（fast-path，无需三方库）
       a. 任一为纯 == 时：保留版本号较高的 ==
       b. 双方均为单一同类操作符（>= / <= / > / < 一致）时：取更严格的一方
  2. packaging.specifiers 兜底：字符串合并后交由 pip 最终裁决
  3. 兜底：返回 existing_spec 保持已有约束

对外暴露唯一入口：resolve_version_conflict()
"""
import re
from typing import Optional, Tuple


def resolve_version_conflict(existing_spec: str, new_spec: str, package_name: str) -> str:
    """
    解决版本冲突，返回裁决后的版本规范。

    Args:
        existing_spec: 当前已记录的版本规范（如 '>=1.0.0'）
        new_spec:      新遇到的版本规范（如 '==2.0.0'）
        package_name:  包名（仅用于日志）

    Returns:
        裁决后的版本规范字符串
    """
    if not existing_spec:
        return new_spec
    if not new_spec:
        return existing_spec
    if existing_spec == new_spec:
        return existing_spec

    # Step 1: 简单策略，覆盖两类最常见场景
    simple_result = _apply_simple_strategy(existing_spec, new_spec)
    if simple_result is not None:
        return simple_result

    # Step 2: packaging.specifiers 兜底，复杂约束交由 pip 裁决
    pkg_result = _try_merge_with_packaging(existing_spec, new_spec)
    if pkg_result is not None:
        return pkg_result

    # Step 3: 无法合并，保留已有约束
    return existing_spec


# ---------------------------------------------------------------------------
# 简单策略（fast-path）
# ---------------------------------------------------------------------------

def _apply_simple_strategy(existing_spec: str, new_spec: str) -> Optional[str]:
    """
    处理两类最常见的约束冲突场景（无需 packaging 库）。

    场景 1 — 任一为纯 == 时，保留版本号较高的 ==：
      '==1.0'  vs '==2.0'   -> '==2.0'   （双方均为 ==，取较高版本）
      '==2.0'  vs '==1.0'   -> '==2.0'
      '==1.5'  vs '>=1.0'   -> '==1.5'   （只有一方为 ==，精确版本优先）
      '>=1.0'  vs '==1.5'   -> '==1.5'

    场景 2 — 双方均为单一同类操作符时，取更严格的一方：
      '>=1.8'  vs '>=1.10'  -> '>=1.10'  （下界：取较大值）
      '<=1.8'  vs '<=1.10'  -> '<=1.8'   （上界：取较小值）
      '>1.8'   vs '>1.10'   -> '>1.10'
      '<1.8'   vs '<1.10'   -> '<1.8'

    其他场景（混合操作符、含 !=、含 ~=、复合约束等）返回 None，交由 packaging 处理。
    """
    # 场景 1：任一含纯 ==
    exact_a = _extract_exact_version(existing_spec)
    exact_b = _extract_exact_version(new_spec)

    if exact_a is not None or exact_b is not None:
        if exact_a is not None and exact_b is not None:
            # 双方都是 ==：保留更高版本
            return existing_spec if _is_version_newer(exact_a, exact_b) else new_spec
        # 只有一方是 ==：精确约束优先
        return existing_spec if exact_a is not None else new_spec

    # 场景 2：单一同类操作符
    op_a, ver_a = _parse_single_op(existing_spec)
    op_b, ver_b = _parse_single_op(new_spec)

    if op_a and op_b and op_a == op_b:
        if op_a in ('>=', '>'):
            # 下界：取更大值（更严格）
            return existing_spec if _is_version_newer(ver_a, ver_b) else new_spec
        if op_a in ('<=', '<'):
            # 上界：取更小值（更严格）
            return new_spec if _is_version_newer(ver_a, ver_b) else existing_spec

    return None


def _extract_exact_version(spec: str) -> Optional[str]:
    """
    若 spec 是纯精确版本约束（如 '==1.8.0'），返回版本号；否则返回 None。

    只匹配独立的单一 == 约束，复合约束（如 '==1.5,!=1.5.1'）返回 None。

    Examples:
      '==1.8.0'        -> '1.8.0'
      '==2.1.5.post1'  -> '2.1.5.post1'
      '==1.0.0a1'      -> '1.0.0a1'
      '>=1.0.0'        -> None
      '==1.5,!=1.5.1'  -> None
      ''               -> None
    """
    m = re.match(r'^==([\d][^,]*)$', spec.strip())
    return m.group(1).strip() if m else None


def _parse_single_op(spec: str) -> Tuple[Optional[str], Optional[str]]:
    """
    若 spec 是单一 >= / <= / > / < 约束，返回 (op, version)；否则返回 (None, None)。

    不处理 ==、!=、~= 操作符，也不处理复合约束（含逗号）。

    Examples:
      '>=1.8.0'     -> ('>=', '1.8.0')
      '<=2.0'       -> ('<=', '2.0')
      '>1.0'        -> ('>', '1.0')
      '<3.0.0'      -> ('<', '3.0.0')
      '>=1.0,<2.0'  -> (None, None)   # 复合约束
      '!=1.5'       -> (None, None)   # 不支持的操作符
      '~=1.4.2'     -> (None, None)
      '==1.5'       -> (None, None)
    """
    spec = spec.strip()
    if ',' in spec:
        return None, None
    # 允许操作符与版本号之间有空格，如 ">= 0.33.0"
    m = re.match(r'^(>=|<=|>|<)\s*([\d].*)$', spec)
    if m:
        return m.group(1), m.group(2).strip()
    return None, None


# ---------------------------------------------------------------------------
# packaging.specifiers 兜底
# ---------------------------------------------------------------------------

def _try_merge_with_packaging(range_a: str, range_b: str) -> Optional[str]:
    """
    使用 packaging.specifiers.SpecifierSet 合并两个版本约束，失败时返回 None。

    packaging 的 & 操作本质是约束字符串的拼接，不做语义推断，合并结果交由 pip 最终裁决：
    - 不会把 '>=1.26.4,<=1.26.4' 化简为 '==1.26.4'
    - 不会检测矛盾区间（如 '>=2.0,<=1.0'），pip 安装时才会报错

    常见场景示例（packaging 可用时）：
      '>=1.8.0,<2.0'      vs '>=1.10.0,<3.0'   -> '<2.0,<3.0,>=1.8.0,>=1.10.0'  （冗余，pip 正确处理）
      '>=4.39.0,!=4.50.*' vs '>=4.44.0'         -> '!=4.50.*,>=4.39.0,>=4.44.0'
      '>=1.26.4'          vs '<=1.26.4'          -> '>=1.26.4,<=1.26.4'
      '>=1.26.5'          vs '<=1.26.3'          -> '>=1.26.5,<=1.26.3'  （矛盾区间，pip 安装时报错）
      '~=1.4.2'           vs '>=1.4.0'           -> '~=1.4.2,>=1.4.0'
    """
    try:
        from packaging.specifiers import SpecifierSet
        merged = SpecifierSet(range_a) & SpecifierSet(range_b)
        return str(merged)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 共用工具函数
# ---------------------------------------------------------------------------

def _is_version_newer(version_a: str, version_b: str) -> bool:
    """
    判断 version_a 是否比 version_b 更新（严格大于），完整支持 PEP 440。

    使用 packaging.version.Version 进行比较，覆盖预发布（a/b/rc）、
    post release、dev release、epoch 等所有标准版本形式。
    packaging 不可用或版本字符串无法解析时，打印 WARNING 并视 version_a 为较新版本。
    """
    try:
        from packaging.version import Version
        return Version(version_a) > Version(version_b)
    except Exception as e:
        print(f"[Installer] WARNING: failed to compare versions '{version_a}' vs '{version_b}': {e}, treating '{version_a}' as newer")
        return True
