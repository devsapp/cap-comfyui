"""ComfyUI v0.27 official template input compatibility plugin."""

from .folder_paths_patch import install_template_asset_patch


install_template_asset_patch()

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
