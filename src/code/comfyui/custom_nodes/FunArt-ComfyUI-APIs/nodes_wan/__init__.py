"""
Wan 系列节点 for ComfyUI
包含 Wan 模型相关的图像生成和编辑节点
"""

# Wan 2.5 节点
from .wan2_5_image_edit import Wan2_5_ImageEdit
from .wan2_5_i2v import Wan2_5_I2V
from .wan2_5_t2i import Wan2_5_T2I
from .wan2_5_t2v import Wan2_5_T2V

# Wan 2.6 节点
from .wan2_6_image_edit import Wan2_6_ImageEdit
from .wan2_6_i2v import Wan2_6_I2V
from .wan2_6_t2i import Wan2_6_T2I
from .wan2_6_t2v import Wan2_6_T2V

# 节点类映射 - 用于ComfyUI识别和加载节点
NODE_CLASS_MAPPINGS = {
    # Wan 2.5
    "Wan2_5_ImageEdit": Wan2_5_ImageEdit,
    "Wan2_5_I2V": Wan2_5_I2V,
    "Wan2_5_T2I": Wan2_5_T2I,
    "Wan2_5_T2V": Wan2_5_T2V,
    # Wan 2.6
    "Wan2_6_ImageEdit": Wan2_6_ImageEdit,
    "Wan2_6_I2V": Wan2_6_I2V,
    "Wan2_6_T2I": Wan2_6_T2I,
    "Wan2_6_T2V": Wan2_6_T2V,
}

# 节点显示名称映射 - 在ComfyUI界面中显示的友好名称
NODE_DISPLAY_NAME_MAPPINGS = {
    # Wan 2.5
    "Wan2_5_ImageEdit": "Wan 2.5 图像编辑",
    "Wan2_5_I2V": "Wan 2.5 图生视频",
    "Wan2_5_T2I": "Wan 2.5 文生图",
    "Wan2_5_T2V": "Wan 2.5 文生视频",
    # Wan 2.6
    "Wan2_6_ImageEdit": "Wan 2.6 图像编辑",
    "Wan2_6_I2V": "Wan 2.6 图生视频",
    "Wan2_6_T2I": "Wan 2.6 文生图",
    "Wan2_6_T2V": "Wan 2.6 文生视频",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
