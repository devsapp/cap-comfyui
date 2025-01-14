# 定义变量
IMAGE_NAME = registry.us-east-1.aliyuncs.com/fc-demo2/zijian-test-sd
TAG = test-ctr-v12

# 默认目标
.PHONY: all
all: build login push

# 构建镜像
.PHONY: build
build:
	docker build -t $(IMAGE_NAME):$(TAG) .
	docker tag $(IMAGE_NAME):$(TAG) agent

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
	docker run -it --rm -p 9000:9000 $(IMAGE_NAME):$(TAG)

.PHONY: test-debug
test-debug:
	docker run -it --rm -p 9000:9000 --entrypoint /bin/bash $(IMAGE_NAME):$(TAG)

# 部署到线上，需要先手动改下s.yaml中的镜像版本
.PHONY: deploy
deploy:
	s deploy
