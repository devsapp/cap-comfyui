"""
定制化依赖策略模块。

部分特殊插件需要覆写或注入额外的依赖（如指定 wheel URL）。
在 Step 1 合并完成、过滤之后、正式安装之前，对依赖字典执行策略调整。

对外暴露唯一入口：apply_custom_dependency_strategies()
新增策略时，在该函数内追加调用即可，不需要修改其他文件。
"""
from typing import Dict, List
from services.pip.models import DependencyInfo


def apply_custom_dependency_strategies(
    deps: Dict[str, DependencyInfo],
    nodes_to_install: List[str],
    nodes_map,
) -> Dict[str, DependencyInfo]:
    """
    依次执行所有定制化策略，返回调整后的依赖字典。

    Args:
        deps:             过滤后的依赖字典（会被原地或副本修改）
        nodes_to_install: 本次要安装的节点名称列表
        nodes_map:        节点配置映射（包含版本等信息）
    """
    print("\n[Installer] ## Applying custom dependency strategies...")

    deps = _handle_nunchaku_strategy(deps, nodes_to_install, nodes_map)

    # TODO: 新增策略在此追加
    # deps = _handle_xxx_strategy(deps, nodes_to_install, nodes_map)

    return deps


# ---------------------------------------------------------------------------
# 内部策略实现
# ---------------------------------------------------------------------------

def _handle_nunchaku_strategy(
    deps: Dict[str, DependencyInfo],
    nodes_to_install: List[str],
    nodes_map,
) -> Dict[str, DependencyInfo]:
    """
    ComfyUI-nunchaku 特殊处理：v1.0.0 / v1.0.1 注入指定 wheel URL。
    其他版本无需特殊处理。
    """
    node_name = "ComfyUI-nunchaku"
    if node_name not in nodes_to_install:
        return deps

    print(f"[Installer] ## Found {node_name} node, applying special handling...")

    version = _extract_nunchaku_version(nodes_map, node_name)

    if version in ["v1.0.0", "v1.0.1"]:
        print(f"[Installer] ## Detected nunchaku version {version}, adding custom wheel dependency...")
        wheel_url = (
            "https://modelscope.cn/models/nunchaku-tech/nunchaku/resolve/master/"
            "nunchaku-1.0.0+torch2.8-cp310-cp310-linux_x86_64.whl"
        )
        deps[wheel_url] = DependencyInfo(
            package_name=wheel_url,
            version_spec="",
            original_line=wheel_url,
            source_nodes=[node_name],
        )
        print(f"[Installer] ## Added nunchaku wheel: {wheel_url}")
    else:
        print(f"[Installer] ## Nunchaku version {version} does not require special handling")

    return deps


def _extract_nunchaku_version(nodes_map, node_name: str) -> str:
    """从 nodes_map 中提取 nunchaku 节点的版本字符串，解析失败时返回 'unknown'。"""
    if not nodes_map or node_name not in nodes_map:
        print(f"[Installer] ## Warning: No version info found for {node_name} in nodes_map")
        return "unknown"

    node_config = nodes_map[node_name]
    try:
        version_info = node_config.get('version', {})
        if isinstance(version_info, dict):
            version_value = version_info.get('value', 'unknown')
            print(f"[Installer] ## Extracted nunchaku version: {version_value}")
            return version_value
        print(f"[Installer] ## Warning: Invalid version structure in {node_name} config")
        return "unknown"
    except (KeyError, AttributeError, TypeError) as e:
        print(f"[Installer] ## Error extracting version from {node_name}: {e}")
        print(f"[Installer] ## Node config structure: {node_config}")
        return "unknown"
