COMFYUI_VERSION := v0.33.1
CUSTOM_NODES_JSON := comfyui/v0.33.1/custom_nodes.json
OSS_COMFYUI_BASE_DIR := base/comfyui/$(COMFYUI_VERSION)-gamma
OSS_COMFYUI_DEEPGPU_BASE_DIR := base/comfyui/$(COMFYUI_VERSION)-gamma-deepgpu
CAP_SYSTEM_VERSION := 4.0.0
# VisionPlaid 1.1.0 is the newest wheel with the current node schema that does
# not pin transformers 5.5; 1.1.1+ conflicts with Nunchaku 1.0.2 (<4.57).
VISION_PLAID_VERSION := 1.1.0
BITFORGE_VERSION := 0.2.4
# Nunchaku 1.0.2 allows newer diffusers/huggingface-hub versions whose
# constraints conflict with transformers 4.56.2. Keep this release line
# deterministic without changing the dependency behavior of older versions.
NUNCHAKU_DEPENDENCY_CONSTRAINTS := diffusers==0.35.1 huggingface-hub==0.34.4 transformers==4.56.2 torch==2.9.1 torchvision==0.24.1 torchaudio==2.9.1
# 指纹只用裸 CAP_SYSTEM_VERSION；v0.33.1 独立版本线不覆盖 v0.27.0。
BUILTIN_DEPENDENCY_VERSION := $(CAP_SYSTEM_VERSION)

include ../shared/Makefile.common
