"""
Monkey Patch for Cache Signature - User-Isolated Caching (Universal Solution)

Problem:
    - ComfyUI's cache signatures only include node inputs
    - extra_data (including userId) is not part of inputs
    - Different users executing the same workflow reuse cache incorrectly

Solution:
    - Patch the cache signature generation function get_immediate_node_signature
    - Include current user_id in the signature
    - Automatically covers all nodes (official + custom)
"""

from .context import get_current_user


# Store original function
_original_get_immediate_node_signature = None


async def _patched_get_immediate_node_signature(self, dynprompt, node_id, ancestor_order_mapping):
    """
    Patched version of get_immediate_node_signature.
    
    Adds user_id to the original signature to ensure cache isolation between users.
    
    Working principle:
        1. Get current user_id BEFORE await (防止协程切换导致 context 变化)
        2. Call original function to get base signature
        3. Append user_id to signature
        4. Different users -> different signatures -> no cache reuse
    
    Args:
        self: CacheKeySetInputSignature instance
        dynprompt: Dynamic prompt object
        node_id: Node identifier
        ancestor_order_mapping: Ancestor ordering map
        
    Returns:
        Modified signature with user_id appended
    """
    user_id = get_current_user()
    
    # Get base signature from original function
    signature = await _original_get_immediate_node_signature(
        self, dynprompt, node_id, ancestor_order_mapping
    )
    
    # For ALL users (including 'default'), append user_id to signature
    # This ensures different users have different signatures and won't share cache
    signature = list(signature) if not isinstance(signature, list) else signature
    signature.append(('__comfyui_user_id__', user_id))
    
    return signature


def install_cache_signature_patch():
    """
    Install cache signature patch.
    
    Patches get_immediate_node_signature function to include user_id
    in cache signatures for all nodes.
    
    Advantages:
        - Automatically covers all nodes (official + custom)
        - Zero-intrusion, no need to modify any node code
        - Only need to patch one place
    """
    global _original_get_immediate_node_signature
    
    try:
        # Import caching module
        from comfy_execution.caching import CacheKeySetInputSignature  # type: ignore
        
        # Save original function
        _original_get_immediate_node_signature = CacheKeySetInputSignature.get_immediate_node_signature
        
        # Replace with patched version
        CacheKeySetInputSignature.get_immediate_node_signature = _patched_get_immediate_node_signature
        
    except ImportError:
        pass  # comfy_execution.caching 模块不存在（旧版本 ComfyUI）
    except Exception as e:
        print(f"[ComfyUI-Multi-User] ❌ Cache signature patch 安装失败: {e}")
        import traceback
        traceback.print_exc()


__all__ = ['install_cache_signature_patch']
