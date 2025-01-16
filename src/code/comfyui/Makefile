# 定义变量
IMAGE_NAME = registry.us-east-1.aliyuncs.com/fc-demo2/zijian-test-sd
TAG = cap-comfyui-v13

# 默认目标
.PHONY: all
all: build login push

# 构建镜像
.PHONY: build
build:
	docker build -t $(IMAGE_NAME):$(TAG) .

# 登录镜像仓库
.PHONY: login
login:
	docker login --username=qiucheng.wzj@1431999136518149 registry.us-east-1.aliyuncs.com

# 推送镜像
.PHONY: push
push:
	docker push $(IMAGE_NAME):$(TAG)

.PHONY: test
test:
	docker run --gpus all -it --rm -p 9000:9000 -p 8188:8188 $(IMAGE_NAME):$(TAG)

.PHONY: test-debug
test-debug:
	docker run --gpus all -it --rm -p 9000:9000 -p 8188:8188 --entrypoint /bin/bash $(IMAGE_NAME):$(TAG)
