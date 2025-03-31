# 定义变量
VALID_REGIONS = ap-southeast-1 cn-hangzhou cn-beijing cn-shanghai
export REGION ?= cn-hangzhou

ifeq ($(filter $(REGION),$(VALID_REGIONS)),)
$(error Invalid REGION: $(REGION). Must be one of: $(VALID_REGIONS))
endif

AGENT_IMAGE = registry.$(REGION).aliyuncs.com/ohyee/fc-demo:cap-agent-v24
export OSS_BUCKET = dipper-cache-$(REGION)

# 构建Agent镜像
.PHONY: build
build:
	cd src/code/agent && docker build -t $(AGENT_IMAGE) .
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
.PHONY: login
login:
	docker login --username=oyohyee@gmail.com registry.$(REGION).aliyuncs.com

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
