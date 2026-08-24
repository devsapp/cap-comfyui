# 定义变量
VALID_REGIONS = ap-southeast-1 cn-hangzhou cn-beijing cn-shanghai cn-shenzhen
export REGION ?= cn-hangzhou

ifeq ($(filter $(REGION),$(VALID_REGIONS)),)
$(error Invalid REGION: $(REGION). Must be one of: $(VALID_REGIONS))
endif

VERSION ?= $(shell date "+%Y%m%d%H%M%S")
REGISTRY = cap-demo-public-registry.cn-hangzhou.cr.aliyuncs.com/cap-app
AGENT_IMAGE ?= $(REGISTRY)/image-generation-comfyui-agent-dev:$(VERSION)
COMFYUI_VERSION ?= v0.3.77
ifeq ($(COMFYUI_VERSION),v0.16.4)
CAP_SYSTEM_VERSION ?= 2.0.5
# 指纹只用裸系统版本号(不带 -vp 后缀),与存量实例 NAS 记录保持同一口径。
# 内置插件代码或依赖实质变更时必须 bump，以触发存量项目更新。
BUILTIN_DEPENDENCY_VERSION ?= $(CAP_SYSTEM_VERSION)
else ifeq ($(COMFYUI_VERSION),v0.27.0)
CAP_SYSTEM_VERSION ?= 3.0.1
BUILTIN_DEPENDENCY_VERSION ?= $(CAP_SYSTEM_VERSION)
else ifeq ($(COMFYUI_VERSION),v0.33.1)
CAP_SYSTEM_VERSION ?= 4.0.0
BUILTIN_DEPENDENCY_VERSION ?= $(CAP_SYSTEM_VERSION)
else
CAP_SYSTEM_VERSION ?= 1.6.7
BUILTIN_DEPENDENCY_VERSION ?= $(CAP_SYSTEM_VERSION)
endif
AGENT_COMFYUI_IMAGE ?= cap-demo-public-registry.cn-hangzhou.cr.aliyuncs.com/aliyunfc/funart-comfyui:v$(CAP_SYSTEM_VERSION)
COMFYUI_LOCAL_IMAGE ?= comfyui:v$(CAP_SYSTEM_VERSION)-comfyui-$(COMFYUI_VERSION)
export OSS_BUCKET = dipper-cache-$(REGION)
WARMUP_REGIONS ?= cn-hangzhou cn-shenzhen cn-beijing cn-shanghai ap-southeast-1

# ————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
# 预发环境：构建推送 Agent dev 镜像 + 预热杭州
.PHONY: all
all:
	@IMAGE="$(REGISTRY)/image-generation-comfyui-agent-dev:$(VERSION)"; \
	echo "====== [Pre] Image: $$IMAGE ======"; \
	$(MAKE) AGENT_IMAGE="$$IMAGE" login && \
	$(MAKE) AGENT_IMAGE="$$IMAGE" build && \
	$(MAKE) AGENT_IMAGE="$$IMAGE" push && \
	$(MAKE) AGENT_IMAGE="$$IMAGE" WARMUP_REGIONS=cn-hangzhou warmup && \
	echo "====== [Pre] Completed successfully ======" || \
	{ echo "====== [Pre] Failed ======"; exit 1; }

# 生产环境：构建推送 Agent 生产镜像 + 预热全部 region（VERSION 必须指定为 git tag）
# make release VERSION=v1.4.0
.PHONY: release
release:
	@if [ "$(origin VERSION)" = "file" ]; then \
		echo "[ERROR] VERSION is required for production release. Usage: make release VERSION=v1.4.0"; \
		exit 1; \
	fi
	@IMAGE="$(REGISTRY)/image-generation-comfyui-agent:$(VERSION)"; \
	echo "====== [Prod] Image: $$IMAGE ======"; \
	$(MAKE) AGENT_IMAGE="$$IMAGE" login && \
	$(MAKE) AGENT_IMAGE="$$IMAGE" build && \
	$(MAKE) AGENT_IMAGE="$$IMAGE" push && \
	$(MAKE) AGENT_IMAGE="$$IMAGE" warmup && \
	echo "====== [Prod] Completed successfully ======" || \
	{ echo "====== [Prod] Failed ======"; exit 1; }

# ————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
# Agent镜像相关
# 镜像构建
.PHONY: build
build:
	cd src/code/agent && docker build --platform linux/amd64 \
		--build-arg COMFYUI_IMAGE=$(AGENT_COMFYUI_IMAGE) \
		--build-arg BUILTIN_DEPENDENCY_VERSION=$(BUILTIN_DEPENDENCY_VERSION) \
		-t $(AGENT_IMAGE) .
	docker tag $(AGENT_IMAGE) agent

# 本地测试运行
.PHONY: run
run:
	docker run -it --rm -p 9000:9000 $(AGENT_IMAGE)

# 本地测试登录
.PHONY: exec
exec:
	docker run -it --rm -p 9000:9000 --entrypoint /bin/bash agent

# 登录镜像仓库
# CR_USER=xxx CR_PWD=xxx make login
.PHONY: login
login:
	@if [ -z "$$CR_PWD" ]; then \
		echo "No CR_PWD provided, using interactive login..."; \
		docker login cap-demo-public-registry.cn-hangzhou.cr.aliyuncs.com; \
	else \
		echo "Using provided credentials for login..."; \
		CR_USER=$${CR_USER:-xiliu@1767215449378635}; \
		echo "$$CR_PWD" | docker login --username=$$CR_USER --password-stdin cap-demo-public-registry.cn-hangzhou.cr.aliyuncs.com; \
	fi

# 推送镜像
.PHONY: push
push:
	docker push $(AGENT_IMAGE)

# 部署到测试函数
.PHONY: deploy
deploy:
	export WEBHOOK_URL="http://dipper-any-post-rwhuiqmhaf.cn-hangzhou.fcapp.run/post?uid=a&projectName=a&environmentName=a&serviceName=a&token=a" \
	&& s deploy -t src/code/comfyui/s-dev-usemodel.yaml

# 镜像预热
# make warmup AGENT_IMAGE=<image>                                           # warmup all default regions
# make warmup AGENT_IMAGE=<image> WARMUP_REGIONS=cn-hangzhou                # warmup specific region
# make warmup AGENT_IMAGE=<image> WARMUP_REGIONS="cn-hangzhou cn-beijing"   # warmup multiple regions
.PHONY: warmup
warmup:
	@./warmup/warmup.sh "$(AGENT_IMAGE)" $(WARMUP_REGIONS)

# ————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
# ComfyUI 多版本构建

.PHONY: build-comfyui
build-comfyui:
	@$(MAKE) -C src/code/comfyui/$(COMFYUI_VERSION) build
	docker tag $(COMFYUI_LOCAL_IMAGE) $(AGENT_COMFYUI_IMAGE)
	@$(MAKE) build \
		COMFYUI_VERSION=$(COMFYUI_VERSION) \
		AGENT_COMFYUI_IMAGE=$(AGENT_COMFYUI_IMAGE) \
		BUILTIN_DEPENDENCY_VERSION=$(BUILTIN_DEPENDENCY_VERSION) \
		AGENT_IMAGE=$(AGENT_IMAGE)

.PHONY: build-comfyui-v0.3.77
build-comfyui-v0.3.77:
	@$(MAKE) build-comfyui COMFYUI_VERSION=v0.3.77

.PHONY: build-comfyui-v0.16.4
build-comfyui-v0.16.4:
	@$(MAKE) build-comfyui COMFYUI_VERSION=v0.16.4

.PHONY: build-comfyui-v0.27.0
build-comfyui-v0.27.0:
	@$(MAKE) build-comfyui COMFYUI_VERSION=v0.27.0

.PHONY: build-comfyui-v0.33.1
build-comfyui-v0.33.1:
	@$(MAKE) build-comfyui COMFYUI_VERSION=v0.33.1

.PHONY: build-comfyui-all
build-comfyui-all: build-comfyui-v0.3.77 build-comfyui-v0.16.4 build-comfyui-v0.27.0 build-comfyui-v0.33.1

.PHONY: run-comfyui
run-comfyui:
	@$(MAKE) -C src/code/comfyui/$(COMFYUI_VERSION) run

.PHONY: exec-comfyui
exec-comfyui:
	@$(MAKE) -C src/code/comfyui/$(COMFYUI_VERSION) exec

.PHONY: pull-comfyui
pull-comfyui:
	@$(MAKE) -C src/code/comfyui/$(COMFYUI_VERSION) pull

.PHONY: upload-comfyui-base
upload-comfyui-base:
	@$(MAKE) -C src/code/comfyui/$(COMFYUI_VERSION) upload-base

# 根据已发布的snapshot构建comfyui生产镜像
# BUILD_ENV_SNAPSHOT_DIR=/mnt/cap-models/4a34adf1-4b55-5ee7-b997-9f0414bb30c8/snapshots/prod-20250609-092136
# make build-comfyui-from-snapshot
.PHONY: build-comfyui-from-snapshot
build-comfyui-from-snapshot: build
	@$(MAKE) -C src/code/comfyui/$(COMFYUI_VERSION) build-from-snapshot

# ————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
.PHONY: build-sd
build-sd: build
	@make -C src/code/sd build

.PHONY: run-sd
run-sd:
	@make -C src/code/sd run

.PHONY: exec-sd
exec-sd:
	@make -C src/code/sd exec

.PHONY: pull-sd
pull-sd:
	@make -C src/code/sd pull

.PHONY: upload-sd-base
upload-sd-base:
	@make -C src/code/sd upload-base
