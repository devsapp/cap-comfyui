# 定义变量
VALID_REGIONS = ap-southeast-1 cn-hangzhou cn-beijing cn-shanghai cn-shenzhen
export REGION ?= cn-hangzhou

ifeq ($(filter $(REGION),$(VALID_REGIONS)),)
$(error Invalid REGION: $(REGION). Must be one of: $(VALID_REGIONS))
endif

VERSION ?= $(shell date "+%Y%m%d%H%M%S")
AGENT_IMAGE = registry.$(REGION).aliyuncs.com/ohyee/fc-demo:agent-$(VERSION)
export OSS_BUCKET = dipper-cache-$(REGION)

# 构建并推送Agent镜像到所有Region
# make all
# CR_PWD=xxx make all
# REGIONS="cn-hangzhou cn-shanghai" CR_PWD=xxx make all
# CR_PWD=xxx VERSION=v0.0.1-alpha.0 make all
.PHONY: all
all:
	@REGIONS_TO_DEPLOY="$${REGIONS:-$(VALID_REGIONS)}"; \
	echo "====== Will process regions: $$REGIONS_TO_DEPLOY ======"; \
	for region in $$REGIONS_TO_DEPLOY; do \
		if ! echo "$(VALID_REGIONS)" | grep -w "$$region" > /dev/null; then \
			echo "Error: Invalid region '$$region'. Must be one of: $(VALID_REGIONS)"; \
			exit 1; \
		fi; \
	done; \
	for region in $$REGIONS_TO_DEPLOY; do \
		echo "\n====== Processing region: $$region ======"; \
		$(MAKE) REGION=$$region CR_PWD="$$CR_PWD" VERSION=$(VERSION) login build push; \
		if [ $$? -ne 0 ]; then \
			echo "====== Failed in region $$region ======"; \
			exit 1; \
		fi; \
		echo "====== Completed region: $$region ======"; \
	done

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
	docker run -it --rm -p 9000:9000 --entrypoint /bin/bash $(IMAGE_NAME):$(TAG)

# 登录镜像仓库
# REGION=xxx CR_PWD=xxx make login
.PHONY: login
login:
	@if [ -z "$$CR_PWD" ]; then \
		echo "[$(REGION)] No CR_PWD provided, using interactive login..."; \
		docker login --username=oyohyee@gmail.com registry.$(REGION).aliyuncs.com; \
	else \
		echo "[$(REGION)] Using provided CR_PWD for login..."; \
		echo "$$CR_PWD" | docker login --username=oyohyee@gmail.com --password-stdin registry.$(REGION).aliyuncs.com; \
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
