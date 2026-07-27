"""Keep Function Compute task IDs compatible with newer ComfyUI releases."""

from .prompt_id_compat import install_prompt_id_compat


# Install before ComfyUI starts accepting requests. This lives in a dedicated
# built-in plugin so an older FunArt-ComfyUI-APIs copy on a user's NAS cannot
# shadow the compatibility fix during an in-place ComfyUI upgrade.
install_prompt_id_compat()

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
