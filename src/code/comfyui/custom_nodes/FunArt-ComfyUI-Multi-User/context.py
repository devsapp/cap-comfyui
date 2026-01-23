"""
User Context Management - Thread and Async Safe User Isolation

Features:
    - Use contextvars for async/await safe context storage
    - Provide context manager for easy user switching
    - Support nested context with proper cleanup
"""

import contextvars

# ============================================
# Context Variable Storage: Store current context's user ID
# ============================================

_current_user: contextvars.ContextVar[str] = contextvars.ContextVar(
    'current_user',
    default='default'
)


def set_current_user(user_id: str):
    """
    Set the current context's user ID.
    
    Safe for both threading and async/await scenarios.

    Args:
        user_id: User identifier (e.g., "user_001" or "john@email.com")
    """
    _current_user.set(user_id)


def get_current_user() -> str:
    """
    Get the current context's user ID.
    
    Safe for both threading and async/await scenarios.

    Returns:
        User ID, defaults to "default" if not set
    """
    return _current_user.get()


def clear_current_user():
    """
    Clear the current context's user ID by resetting to default.
    
    Safe for both threading and async/await scenarios.
    """
    _current_user.set('default')


# ============================================
# Context Manager
# ============================================

class UserContext:
    """
    User context manager.

    Usage:
        with UserContext("user_001"):
            # Within this block, all asset operations use user_001's directories
            execute_workflow()
    """

    def __init__(self, user_id: str):
        """
        Initialize user context.
        
        Args:
            user_id: User identifier to set as current
        """
        self.user_id = user_id
        self.previous_user_id = None

    def __enter__(self):
        """Enter context - save previous user and set new user."""
        self.previous_user_id = get_current_user()
        set_current_user(self.user_id)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context - restore previous user."""
        if self.previous_user_id:
            set_current_user(self.previous_user_id)
        else:
            clear_current_user()
        return False


__all__ = [
    'set_current_user',
    'get_current_user',
    'clear_current_user',
    'UserContext',
]
