COMFYUI_VERSION := v0.16.4
CUSTOM_NODES_JSON := comfyui/v0.16.4/custom_nodes.json
OSS_COMFYUI_BASE_DIR := base/comfyui/$(COMFYUI_VERSION)-gamma
OSS_COMFYUI_DEEPGPU_BASE_DIR := base/comfyui/$(COMFYUI_VERSION)-gamma-deepgpu
CAP_SYSTEM_VERSION := 2.0.3
VISION_PLAID_VERSION := 1.2.2
BITFORGE_VERSION := 0.2.4
VISION_PLAID_EXTRA_PACKAGES := flashinfer-python flashinfer-cubin
# 指纹回归旧方式:只用 CAP_SYSTEM_VERSION,不编码 VP 版本,
# 防止存量实例因指纹变化在冷启动时触发 install_all
BUILTIN_DEPENDENCY_VERSION := $(CAP_SYSTEM_VERSION)

include ../shared/Makefile.common
