# 定义变量
VALID_REGIONS = ap-southeast-1 cn-hangzhou cn-beijing cn-shanghai cn-shenzhen
export REGION ?= cn-hangzhou

ifeq ($(filter $(REGION),$(VALID_REGIONS)),)
$(error Invalid REGION: $(REGION). Must be one of: $(VALID_REGIONS))
endif

VERSION ?= $(shell date "+%Y%m%d%H%M%S")
AGENT_IMAGE = cap-demo-public-registry.cn-hangzhou.cr.aliyuncs.com/cap-app/image-generation-comfyui-agent-dev:$(VERSION)
export OSS_BUCKET = dipper-cache-$(REGION)

# 构建并推送Agent镜像
# make all
# CR_PWD=xxx make all
# CR_USER=xxx CR_PWD=xxx make all
# CR_PWD=xxx VERSION=v1.0.0 make all
.PHONY: all
all:
	@echo "====== Building and pushing agent image ======"; \
	BUILD_VERSION=$${VERSION:-$$(date "+%Y%m%d%H%M%S")}; \
	$(MAKE) VERSION=$$BUILD_VERSION login && \
	$(MAKE) VERSION=$$BUILD_VERSION build && \
	$(MAKE) VERSION=$$BUILD_VERSION push; \
	if [ $$? -eq 0 ]; then \
		echo "====== Build and push completed successfully ======"; \
	else \
		echo "====== Build and push failed ======"; \
		exit 1; \
	fi

# 构建Agent镜像
.PHONY: build
build:
	cd src/code/agent && docker build --platform linux/amd64 -t $(AGENT_IMAGE) .
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
		CR_USER=$${CR_USER:-oyohyee@gmail.com}; \
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

# ————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
.PHONY: build-comfyui
build-comfyui: build
	@make -C src/code/comfyui build

.PHONY: run-comfyui
run-comfyui:
	@make -C src/code/comfyui run

.PHONY: exec-comfyui
exec-comfyui:
	@make -C src/code/comfyui exec

.PHONY: pull-comfyui
pull-comfyui:
	@make -C src/code/comfyui pull

.PHONY: upload-comfyui-base
upload-comfyui-base:
	@make -C src/code/comfyui upload-base

# 根据已发布的snapshot构建comfyui生产镜像
# BUILD_ENV_SNAPSHOT_DIR=/mnt/cap-models/4a34adf1-4b55-5ee7-b997-9f0414bb30c8/snapshots/prod-20250609-092136
# make build-comfyui-from-snapshot
.PHONY: build-comfyui-from-snapshot
build-comfyui-from-snapshot: build
	@make -C src/code/comfyui build-from-snapshot

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
