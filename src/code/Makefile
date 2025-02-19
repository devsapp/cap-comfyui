# 定义变量
AGENT_IMAGE = registry.cn-hangzhou.aliyuncs.com/ohyee/fc-demo:cap-comfyui-agent-v2
COMFYUI_IMAGE = registry.cn-hangzhou.aliyuncs.com/ohyee/fc-demo:cap-comfyui-v18
OSS_BUCKET = dipper-cache-cn-hangzhou
OSS_COMFYUI_BASE_DIR = base/comfyui/v0.3.10-beta

.PHONY: update-agent
update-agent: build login push deploy

# 构建Agent镜像
.PHONY: build
build:
	docker build -t $(AGENT_IMAGE) .
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
	docker login --username=oyohyee@gmail.com registry.cn-hangzhou.aliyuncs.com

# 推送镜像
.PHONY: push
push:
	docker push $(AGENT_IMAGE)

# 部署到测试函数
.PHONY: deploy
deploy:
	export WEBHOOK_URL="http://dipper-any-post-rwhuiqmhaf.cn-hangzhou.fcapp.run/post?uid=a&projectName=a&environmentName=a&serviceName=a&token=a" \
	&& s deploy -t s-dev-usemodel.yaml

# TODO: 发布新版本agent镜像

# ————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
.PHONY: update-comfyui
update-comfyui: build-comfyui upload-base deploy

# 构建Comfyui镜像
.PHONY: build-comfyui
build-comfyui: build
	docker build -t $(COMFYUI_IMAGE) -f Dockerfile.comfyui .

# 本地测试运行Comfyui
.PHONY: run-comfyui
run-comfyui:
	docker run --gpus all -it --rm -p 9000:9000 -p 8188:8188 $(COMFYUI_IMAGE)

# 本地测试登录Comfyui
.PHONY: exec-comfyui
exec-comfyui:
	docker run --gpus all -it --rm -p 9000:9000 -p 8188:8188 --entrypoint /bin/bash $(COMFYUI_IMAGE)

# 上传到官方OSS源
# sudo -v ; curl https://gosspublic.alicdn.com/ossutil/install.sh | sudo bash
# ossutil config
# endpoint: 内网oss-cn-hangzhou-internal.aliyuncs.com 公网oss-cn-hangzhou.aliyuncs.com
# ak & sk: fc-ide-prod账号包含OSS账号写权限的一组AK SK，可联系zijian
TIMESTAMP := $(shell date +%Y%m%d-%H%M%S)
.PHONY: upload-base
upload-base:
	@echo "Starting upload process..."

	# 创建临时目录并确保清理
	@mkdir -p tmp
	@trap 'rm -rf tmp' EXIT

	# 从容器复制文件
	@echo "Copying files from container..."
	@docker create --name comfyuiImage $(COMFYUI_IMAGE) && \
	docker cp comfyuiImage:/root/comfyui ./tmp/comfyui && \
	docker cp comfyuiImage:/root/venv ./tmp/venv && \
	docker rm comfyuiImage

	# 创建压缩文件
	@echo "Creating venv.tar..."
	@tar -cf ./tmp/venv.tar ./tmp/venv

	# 上传文件到OSS
	@echo "Uploading files to OSS..."
	@ossutil cp -r ./tmp/comfyui oss://$(OSS_BUCKET)/$(OSS_COMFYUI_BASE_DIR)/snapshots/$(TIMESTAMP)/comfyui
	@ossutil cp ./tmp/venv.tar.gz oss://$(OSS_BUCKET)/$(OSS_COMFYUI_BASE_DIR)/snapshots/$(TIMESTAMP)/venv.tar.gz
	@ossutil cp -r ./tmp/comfyui/models oss://$(OSS_BUCKET)/$(OSS_COMFYUI_BASE_DIR)/models

	@echo "Upload completed successfully"
