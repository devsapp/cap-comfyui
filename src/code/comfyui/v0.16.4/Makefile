COMFYUI_VERSION := v0.16.4
CUSTOM_NODES_JSON := comfyui/v0.16.4/custom_nodes.json
OSS_COMFYUI_BASE_DIR := base/comfyui/$(COMFYUI_VERSION)-gamma
OSS_COMFYUI_DEEPGPU_BASE_DIR := base/comfyui/$(COMFYUI_VERSION)-gamma-deepgpu
CAP_SYSTEM_VERSION := 2.0.5
VISION_PLAID_VERSION := 1.3.0
BITFORGE_VERSION := 0.2.4
VISION_PLAID_EXTRA_PACKAGES := flashinfer-python flashinfer-cubin
# 指纹只用裸 CAP_SYSTEM_VERSION，不编码 VP 后缀。
# 内置插件代码或依赖实质变更时必须 bump，以触发存量项目更新。
BUILTIN_DEPENDENCY_VERSION := $(CAP_SYSTEM_VERSION)

include ../shared/Makefile.common
