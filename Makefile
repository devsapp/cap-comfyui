# 定义变量
AGENT_IMAGE = registry.cn-hangzhou.aliyuncs.com/ohyee/fc-demo:cap-agent-v15
COMFYUI_IMAGE = registry.cn-hangzhou.aliyuncs.com/ohyee/fc-demo:cap-comfyui-v19
SD_IMAGE = registry.cn-hangzhou.aliyuncs.com/ohyee/fc-demo:cap-sd-v3
OSS_BUCKET = dipper-cache-cn-hangzhou
OSS_COMFYUI_BASE_DIR = base/comfyui/v0.3.10-beta
OSS_SD_BASE_DIR = base/sd/v1.10.1-alpha

.PHONY: update-agent
update-agent: build login push deploy

# 构建Agent镜像
.PHONY: build
build:
	docker build -t $(AGENT_IMAGE) -f src/code/agent/Dockerfile src/code/agent
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
	&& s deploy -t src/code/s-dev-usemodel.yaml

# TODO: 发布新版本agent镜像

# ————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
.PHONY: update-comfyui
update-comfyui: build-comfyui upload-comfyui-base deploy

# 构建Comfyui镜像
.PHONY: build-comfyui
build-comfyui: build
	docker build -t $(COMFYUI_IMAGE) -f src/code/comfyui/Dockerfile.comfyui src/code/comfyui

# 本地测试运行Comfyui
# curl -X POST http://localhost:9000/management/start
.PHONY: run-comfyui
run-comfyui:
	docker run --gpus all -it --rm -p 9000:9000 -p 8188:8188 $(COMFYUI_IMAGE)

# 本地测试登录Comfyui
.PHONY: exec-comfyui
exec-comfyui:
	docker run --gpus all -it --rm -p 9000:9000 -p 8188:8188 --entrypoint /bin/bash $(COMFYUI_IMAGE)

# 拉取Comfyui镜像
.PHONY: pull-comfyui
pull-comfyui:
	docker pull $(COMFYUI_IMAGE)

# 上传到官方OSS源
# sudo -v ; curl https://gosspublic.alicdn.com/ossutil/install.sh | sudo bash
# ossutil config
# endpoint: 内网oss-cn-hangzhou-internal.aliyuncs.com 公网oss-cn-hangzhou.aliyuncs.com
# ak & sk: fc-ide-prod账号包含OSS账号写权限的一组AK SK，可联系zijian
TIMESTAMP := $(shell date +%Y%m%d-%H%M%S)
.PHONY: upload-comfyui-base
upload-comfyui-base:
	@echo "Starting upload process..."
	@rm -rf tmp
	@mkdir -p tmp

	@echo "Copying files from container..."
	@docker rm -f comfyuiImage 2>/dev/null || true
	@docker create --name comfyuiImage $(COMFYUI_IMAGE) && \
	docker cp comfyuiImage:/root/comfyui ./tmp/comfyui && \
	docker cp comfyuiImage:/root/venv ./tmp/venv
	@docker rm comfyuiImage

	@echo "Creating venv.tar..."
	@tar -C ./tmp -cf ./tmp/venv.tar venv

	@echo "Uploading files to OSS..."
	@ossutil cp -r ./tmp/comfyui oss://$(OSS_BUCKET)/$(OSS_COMFYUI_BASE_DIR)/snapshots/$(TIMESTAMP)/comfyui && \
	ossutil cp ./tmp/venv.tar oss://$(OSS_BUCKET)/$(OSS_COMFYUI_BASE_DIR)/snapshots/$(TIMESTAMP)/venv.tar && \
	ossutil cp -r ./tmp/comfyui/models oss://$(OSS_BUCKET)/$(OSS_COMFYUI_BASE_DIR)/models

	@rm -rf tmp
	@echo "Upload completed successfully"

# ————————————————————————————————————————————————————————————————————————————————————————————————————————————————————
.PHONY: update-sd
update-sd: build-sd upload-sd-base deploy

# 构建SD镜像
.PHONY: build-sd
build-sd: build
	docker build -t $(SD_IMAGE) -f src/code/sd/Dockerfile.sd src/code/sd

# 本地测试运行SD
# curl -X POST http://localhost:9000/management/start
.PHONY: run-sd
run-sd:
	docker run --gpus all -it --rm -p 9000:9000 -p 7860:7860 $(SD_IMAGE)

# 本地测试登录SD
.PHONY: exec-sd
exec-sd:
	docker run --gpus all -it --rm -p 9000:9000 -p 7860:7860 --entrypoint /bin/bash $(SD_IMAGE)

# 拉取SD镜像
.PHONY: pull-sd
pull-sd:
	docker pull $(SD_IMAGE)

# 上传到官方OSS源
# sudo -v ; curl https://gosspublic.alicdn.com/ossutil/install.sh | sudo bash
# ossutil config
# endpoint: 内网oss-cn-hangzhou-internal.aliyuncs.com 公网oss-cn-hangzhou.aliyuncs.com
# ak & sk: fc-ide-prod账号包含OSS账号写权限的一组AK SK，可联系zijian
TIMESTAMP := $(shell date +%Y%m%d-%H%M%S)
.PHONY: upload-sd-base
upload-sd-base:
	@echo "Starting upload process..."
	@rm -rf tmp
	@mkdir -p tmp

	@echo "Copying files from container..."
	@docker rm -f sdImage 2>/dev/null || true
	@docker create --name sdImage $(SD_IMAGE) && \
	docker cp sdImage:/root/stable-diffusion-webui ./tmp/stable-diffusion-webui && \
	docker cp sdImage:/root/venv ./tmp/venv && \
	docker cp sdImage:/root/.cache ./tmp/.cache
	@docker rm sdImage

	@echo "Creating venv.tar..."
	@tar -C ./tmp -cf ./tmp/venv.tar venv

	@echo "Uploading files to OSS..."
	@ossutil cp -r ./tmp/stable-diffusion-webui oss://$(OSS_BUCKET)/$(OSS_SD_BASE_DIR)/snapshots/$(TIMESTAMP)/stable-diffusion-webui && \
	ossutil cp ./tmp/venv.tar oss://$(OSS_BUCKET)/$(OSS_SD_BASE_DIR)/snapshots/$(TIMESTAMP)/venv.tar && \
	ossutil cp -r ./tmp/.cache oss://$(OSS_BUCKET)/$(OSS_SD_BASE_DIR)/snapshots/$(TIMESTAMP)/.cache && \
	ossutil cp -r ./tmp/stable-diffusion-webui/models oss://$(OSS_BUCKET)/$(OSS_SD_BASE_DIR)/models

	@rm -rf tmp
	@echo "Upload completed successfully"
