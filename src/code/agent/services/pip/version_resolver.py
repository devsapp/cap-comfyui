"""
版本冲突裁决模块。

合并多个插件的 requirements.txt 时，同一个包可能出现多次且版本要求不同。
本模块提供纯函数（无副作用、无 I/O）来解析版本约束并裁决最终使用哪个版本规范。

对外暴露唯一入口：resolve_version_conflict()
"""
import re
from typing import Dict, List, Optional, Tuple


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

    existing_parsed = _parse_version_constraint(existing_spec)
    new_parsed = _parse_version_constraint(new_spec)

    resolved_spec = _apply_conflict_resolution_strategy(
        existing_parsed, new_parsed, existing_spec, new_spec, package_name
    )

    print(f"[Installer] ## Version conflict for {package_name}: '{existing_spec}' vs '{new_spec}' -> '{resolved_spec}'")
    return resolved_spec


# ---------------------------------------------------------------------------
# 内部实现
# ---------------------------------------------------------------------------

def _parse_version_constraint(version_spec: str) -> Dict:
    """
    解析版本约束，提取操作符和版本号。

    Returns:
        Dict: {
            'operators': [('>=', '1.0.0'), ...],
            'is_exact': bool,
            'has_exclusion': bool,
        }
    """
    if not version_spec.strip():
        return {'operators': [], 'is_exact': False, 'has_exclusion': False}

    constraints = [c.strip() for c in version_spec.split(',')]
    operators = []
    is_exact = False
    has_exclusion = False

    for constraint in constraints:
        match = re.match(r'^([><=!]+)(.+)$', constraint)
        if match:
            op = match.group(1)
            version = match.group(2).strip()
            operators.append((op, version))
            if op == '==':
                is_exact = True
            elif op.startswith('!'):
                has_exclusion = True

    return {'operators': operators, 'is_exact': is_exact, 'has_exclusion': has_exclusion}


def _apply_conflict_resolution_strategy(existing_parsed: Dict, new_parsed: Dict,
                                        existing_spec: str, new_spec: str,
                                        package_name: str) -> str:
    """
    应用冲突解决策略：
    1. 精确版本 vs 精确版本 → 选较新版本
    2. 精确版本 vs 范围版本 → 优先精确版本
    3. 范围版本 vs 范围版本 → 尝试合并，取较严格下界
    4. 默认 → 保持已有约束
    """
    if existing_parsed['is_exact'] and new_parsed['is_exact']:
        existing_version = _extract_version_from_exact(existing_spec)
        new_version = _extract_version_from_exact(new_spec)
        return new_spec if _is_version_newer(new_version, existing_version) else existing_spec

    if existing_parsed['is_exact'] and not new_parsed['is_exact']:
        return existing_spec
    if new_parsed['is_exact'] and not existing_parsed['is_exact']:
        return new_spec

    if not existing_parsed['is_exact'] and not new_parsed['is_exact']:
        merged = _try_merge_version_ranges(existing_spec, new_spec)
        if merged:
            return merged

    return existing_spec


def _extract_version_from_exact(version_spec: str) -> str:
    match = re.search(r'==([\d\.]+)', version_spec)
    return match.group(1) if match else version_spec


def _is_version_newer(version_a: str, version_b: str) -> bool:
    """判断 version_a 是否比 version_b 更新。"""
    try:
        parts_a = [int(x) for x in version_a.split('.')]
        parts_b = [int(x) for x in version_b.split('.')]
        max_len = max(len(parts_a), len(parts_b))
        parts_a.extend([0] * (max_len - len(parts_a)))
        parts_b.extend([0] * (max_len - len(parts_b)))
        return parts_a > parts_b
    except ValueError:
        return version_a > version_b


def _try_merge_version_ranges(range_a: str, range_b: str) -> Optional[str]:
    """
    尝试合并两个范围版本约束。

    情况1: >=1.8.0  vs  >=1.10.0  →  >=1.10.0
    情况2: >=1.8.0,<2.0  vs  >=1.10.0,<3.0  →  >=1.10.0,<2.0
    情况3: >=2.0.0  vs  <1.0.0  →  None（无交集）
    """
    merged = _try_merge_with_packaging(range_a, range_b)
    if merged is not None:
        return merged
    return _try_merge_simple_ranges(range_a, range_b)


def _try_merge_with_packaging(range_a: str, range_b: str) -> Optional[str]:
    """使用 packaging.specifiers 求交集，失败时返回 None。"""
    try:
        from packaging.specifiers import SpecifierSet, InvalidSpecifier
        spec_a = SpecifierSet(range_a)
        spec_b = SpecifierSet(range_b)
        intersection = spec_a & spec_b
        if not intersection:
            return None
        merged_str = str(intersection)
        simplified = _simplify_version_spec(merged_str)
        return simplified if simplified != merged_str else merged_str
    except Exception:
        return None


def _try_merge_simple_ranges(range_a: str, range_b: str) -> Optional[str]:
    """回退逻辑：只处理纯下界约束（>=x.y.z）的合并。"""
    if '>=' in range_a and '<' not in range_a and '>=' in range_b and '<' not in range_b:
        version_a = re.search(r'>=([\d\.]+)', range_a)
        version_b = re.search(r'>=([\d\.]+)', range_b)
        if version_a and version_b:
            return range_a if _is_version_newer(version_a.group(1), version_b.group(1)) else range_b
    return None


def _simplify_version_spec(version_spec: str) -> str:
    """简化重复的下界约束，例如 >=1.8.0,>=1.9.0 → >=1.9.0。"""
    if '>=' not in version_spec or ',' not in version_spec:
        return version_spec

    constraints = [c.strip() for c in version_spec.split(',')]
    ge_constraints: List[Tuple[str, str]] = []
    other_constraints: List[str] = []

    for constraint in constraints:
        if constraint.startswith('>='):
            match = re.match(r'>=([\d\.]+)', constraint)
            if match:
                ge_constraints.append((constraint, match.group(1)))
                continue
        other_constraints.append(constraint)

    if len(ge_constraints) > 1:
        highest = max(ge_constraints, key=lambda x: _version_to_tuple(x[1]))
        return ','.join([highest[0]] + other_constraints)

    return version_spec


def _version_to_tuple(version: str) -> tuple:
    try:
        return tuple(int(x) for x in version.split('.'))
    except ValueError:
        return (version,)
