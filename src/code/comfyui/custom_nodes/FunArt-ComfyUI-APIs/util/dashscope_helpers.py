"""
DashScope API helpers for initialization and configuration.

This module only handles DashScope-specific operations (API key and client setup).
Business logic validation (e.g., prompt validation) should be done at the node level.
"""

import os


def get_dashscope_api_key(api_key: str = "") -> str:
    """Get and validate DashScope API key.

    Args:
        api_key: API key from node parameter (optional)

    Returns:
        str: The effective API key

    Raises:
        ValueError: If API key is missing from both parameter and environment
    """
    # Get API Key: prioritize parameter, fallback to environment variable
    effective_api_key = api_key if api_key else os.environ.get("DASHSCOPE_API_KEY", "")

    if not effective_api_key:
        raise ValueError("请提供 DashScope API Key。\n" "方式1：在节点中配置 api_key 参数\n" "方式2：设置环境变量 DASHSCOPE_API_KEY")

    return effective_api_key


def setup_dashscope(api_key: str, base_url: str = "https://dashscope.aliyuncs.com/api/v1") -> None:
    """Configure DashScope API client.

    Args:
        api_key: DashScope API key
        base_url: DashScope base URL (default: China region)

    Raises:
        ImportError: If dashscope is not installed
    """
    try:
        import dashscope
    except ImportError:
        raise ImportError("dashscope 未安装。请运行: pip install dashscope")

    dashscope.api_key = api_key
    dashscope.base_http_api_url = base_url


def initialize_dashscope(api_key: str = "", base_url: str = "https://dashscope.aliyuncs.com/api/v1") -> str:
    """Initialize DashScope API (convenience method).

    This is a convenience wrapper that combines get_dashscope_api_key() and setup_dashscope().

    Note: This function does NOT validate business logic (e.g., prompt).
    Nodes should handle their own input validation before calling this.

    Args:
        api_key: API key from node parameter (optional)
        base_url: DashScope base URL (default: China region)

    Returns:
        str: The effective API key

    Raises:
        ImportError: If dashscope is not installed
        ValueError: If API key is missing

    Example:
        ```python
        # In node: validate prompt first
        if not prompt:
            raise ValueError("请提供提示词")

        # Then initialize DashScope
        effective_api_key = initialize_dashscope(api_key=api_key)
        ```
    """
    # Get and validate API key
    effective_api_key = get_dashscope_api_key(api_key)

    # Setup DashScope
    setup_dashscope(effective_api_key, base_url)

    return effective_api_key
