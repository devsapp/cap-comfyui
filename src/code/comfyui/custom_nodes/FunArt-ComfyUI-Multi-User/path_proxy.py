"""
Dynamic Path Proxy - Solving Node Instance Caching Issues

This module provides a dynamic path proxy that computes the actual path
based on the current user context when accessed, rather than when assigned.

This solves the problem where ComfyUI caches node instances, which would
otherwise lock paths to a specific user.
"""

import os


class DynamicPathProxy:
    """
    Dynamic path proxy object.

    Acts like a string but computes the actual path dynamically based on
    the current user_id when the path value is actually needed.

    This ensures each user gets their own directory even when node instances are reused.
    """

    def __init__(self, path_getter):
        """
        Initialize the dynamic path proxy.
        
        Args:
            path_getter: Callable that returns the current actual path
        """
        self._path_getter = path_getter

    def _get_path(self):
        """Internal method to get the current path."""
        return self._path_getter()

    def __str__(self):
        """Return the current user's actual path when converted to string."""
        return self._get_path()

    def __repr__(self):
        """Return representation of the proxy."""
        return f"DynamicPathProxy({self._get_path()})"

    def __fspath__(self):
        """Support os.path operations (os.fspath, os.path.join, etc.)."""
        return self._get_path()

    # Path concatenation support
    def __truediv__(self, other):
        """Support / operator: path / "subdir"."""
        return os.path.join(self._get_path(), other)

    def __rtruediv__(self, other):
        """Support reverse / operator: "subdir" / path."""
        return os.path.join(other, self._get_path())

    # String operation support
    def __add__(self, other):
        """Support string concatenation."""
        return self._get_path() + other

    def __radd__(self, other):
        """Support reverse string concatenation."""
        return other + self._get_path()

    def __eq__(self, other):
        """Support equality comparison."""
        if isinstance(other, DynamicPathProxy):
            return self._get_path() == other._get_path()
        return self._get_path() == other

    def __ne__(self, other):
        """Support inequality comparison."""
        if isinstance(other, DynamicPathProxy):
            return self._get_path() != other._get_path()
        return self._get_path() != other

    def __lt__(self, other):
        """Support less than comparison."""
        other_path = other._get_path() if isinstance(other, DynamicPathProxy) else other
        return self._get_path() < other_path

    def __le__(self, other):
        """Support less than or equal comparison."""
        other_path = other._get_path() if isinstance(other, DynamicPathProxy) else other
        return self._get_path() <= other_path

    def __gt__(self, other):
        """Support greater than comparison."""
        other_path = other._get_path() if isinstance(other, DynamicPathProxy) else other
        return self._get_path() > other_path

    def __ge__(self, other):
        """Support greater than or equal comparison."""
        other_path = other._get_path() if isinstance(other, DynamicPathProxy) else other
        return self._get_path() >= other_path

    def __hash__(self):
        """
        DynamicPathProxy 的值依赖于当前 user_id，会动态变化。
        根据 Python 规范，可变对象不应作为 dict key。
        
        如果需要将路径存储为 key，请先转换为字符串：
            my_dict[str(proxy)] = value  # ✅ 正确
        而不是：
            my_dict[proxy] = value  # ❌ 错误
        """
        raise TypeError(
            f"unhashable type: '{type(self).__name__}'. "
            f"DynamicPathProxy 不能作为 dict key"
        )

    def __bool__(self):
        """Support boolean conversion (for empty path checks)."""
        return bool(self._get_path())

    def __len__(self):
        """Support len()."""
        return len(self._get_path())

    def __getitem__(self, key):
        """Support indexing and slicing."""
        return self._get_path()[key]

    def __contains__(self, item):
        """Support 'in' operator."""
        return item in self._get_path()

    # Common string methods
    def startswith(self, prefix):
        """Check if path starts with prefix."""
        return self._get_path().startswith(prefix)

    def endswith(self, suffix):
        """Check if path ends with suffix."""
        return self._get_path().endswith(suffix)

    def split(self, *args, **kwargs):
        """Split the path string."""
        return self._get_path().split(*args, **kwargs)

    def replace(self, *args, **kwargs):
        """Replace substring in path."""
        return self._get_path().replace(*args, **kwargs)

    def format(self, *args, **kwargs):
        """Format the path string."""
        return self._get_path().format(*args, **kwargs)

    def __bytes__(self):
        """Support bytes conversion for compatibility with os.path operations."""
        path = self._get_path()
        if isinstance(path, bytes):
            return path
        return path.encode('utf-8')

    def __format__(self, format_spec):
        """Support format() and f-strings with format specs."""
        return format(self._get_path(), format_spec)

    def __reduce__(self):
        """
        禁止 pickle 序列化。
        
        DynamicPathProxy 依赖于运行时上下文（user_id），序列化后无法正确恢复。
        如果需要序列化，请先转换为字符串：str(proxy)
        """
        raise TypeError(
            f"cannot pickle '{type(self).__name__}' object. "
            f"请使用 str(proxy) 转换为字符串后再序列化"
        )

    @classmethod
    def __class_getitem__(cls, item):
        """Support type checking."""
        return cls


__all__ = ['DynamicPathProxy']
