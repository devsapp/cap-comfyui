"""Top-level package for funart_apis."""

# 从各个节点组导入并合并
from .nodes_wan import NODE_CLASS_MAPPINGS as WAN_NODE_CLASS_MAPPINGS
from .nodes_wan import NODE_DISPLAY_NAME_MAPPINGS as WAN_NODE_DISPLAY_NAME_MAPPINGS

# 合并所有节点映射
NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

NODE_CLASS_MAPPINGS.update(WAN_NODE_CLASS_MAPPINGS)
NODE_DISPLAY_NAME_MAPPINGS.update(WAN_NODE_DISPLAY_NAME_MAPPINGS)

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
]

__author__ = """zijian"""
__email__ = "qiucheng.wzj@alibaba-inc.com"
__version__ = "0.0.1"
