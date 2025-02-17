# 定义变量
IMAGE_NAME = registry.cn-hangzhou.aliyuncs.com/ohyee/fc-demo
TAG = cap-comfyui-agent-v2

# 默认目标
.PHONY: all
all: build login push deploy

# 构建镜像
.PHONY: build
build:
	docker build -t $(IMAGE_NAME):$(TAG) .
	docker tag $(IMAGE_NAME):$(TAG) agent

# 登录镜像仓库
.PHONY: login
login:
	docker login --username=oyohyee@gmail.com registry.cn-hangzhou.aliyuncs.com

# 推送镜像
.PHONY: push
push:
	docker push $(IMAGE_NAME):$(TAG)

.PHONY: test
test:
	docker run -it --rm -p 9000:9000 $(IMAGE_NAME):$(TAG)

.PHONY: test-debug
test-debug:
	docker run -it --rm -p 9000:9000 --entrypoint /bin/bash $(IMAGE_NAME):$(TAG)

.PHONY: deploy
deploy:
	export WEBHOOK_URL="http://dipper-any-post-rwhuiqmhaf.cn-hangzhou.fcapp.run/post?uid=a&projectName=a&environmentName=a&serviceName=a&token=a" \
	&& s deploy -t s-api-usemodel.yaml
