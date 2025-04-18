# 定义变量
REGION ?= cn-hangzhou
COMFYUI_IMAGE = registry.$(REGION).aliyuncs.com/ohyee/fc-demo:cap-comfyui
OSS_BUCKET ?= dipper-cache-$(REGION)
OSS_COMFYUI_BASE_DIR = base/comfyui/v0.3.10-beta

.PHONY: upgrade
upgrade: build upload-base

# 构建镜像, 需要先构建Agent镜像
.PHONY: build
build:
	docker build -t $(COMFYUI_IMAGE) .

# 本地测试运行
# curl -X POST http://localhost:9000/management/start
.PHONY: run
run:
	docker run --gpus all -it --rm -p 9000:9000 -p 8188:8188 $(COMFYUI_IMAGE)

# 本地测试登录
.PHONY: exec
exec:
	docker run --gpus all -it --rm -p 9000:9000 -p 8188:8188 --entrypoint /bin/bash $(COMFYUI_IMAGE)

# 拉取镜像
.PHONY: pull
pull:
	docker pull $(COMFYUI_IMAGE)

# 上传到官方OSS源
# sudo -v ; curl https://gosspublic.alicdn.com/ossutil/install.sh | sudo bash
# ossutil config
# endpoint: 内网oss-cn-hangzhou-internal.aliyuncs.com 公网oss-cn-hangzhou.aliyuncs.com
# ak & sk: fc-ide-prod账号包含OSS账号写权限的一组AK SK，可联系zijian
SNAPSHOT_NAME := dev-$(shell date -u +%Y%m%d-%H%M%S)
.PHONY: upload-base
upload-base:
	@echo "Starting upload process..."
	@rm -rf tmp
	@mkdir -p tmp

	@echo "Copying files from container..."
	@docker rm -f comfyuiImage 2>/dev/null || true
	@docker create --name comfyuiImage $(COMFYUI_IMAGE) && \
	docker cp comfyuiImage:/root/comfyui ./tmp/comfyui && \
	docker cp comfyuiImage:/root/venv ./tmp/venv
	@docker rm comfyuiImage

	@echo "Creating snapshot..."
	@tar -C ./tmp -cf ./tmp/venv.tar venv
	@cd ./tmp && mv ./comfyui/custom_nodes ./ && mv ./comfyui/models ./ && zip -rq comfyui.zip comfyui

	@echo "Uploading files to OSS..."
	@ossutil cp -r ./tmp/models oss://$(OSS_BUCKET)/$(OSS_COMFYUI_BASE_DIR)/models && \
	ossutil cp -r ./tmp/custom_nodes oss://$(OSS_BUCKET)/$(OSS_COMFYUI_BASE_DIR)/custom_nodes && \
	ossutil cp ./tmp/comfyui.zip oss://$(OSS_BUCKET)/$(OSS_COMFYUI_BASE_DIR)/snapshots/$(SNAPSHOT_NAME)/comfyui.zip && \
	ossutil cp ./tmp/venv.tar oss://$(OSS_BUCKET)/$(OSS_COMFYUI_BASE_DIR)/snapshots/$(SNAPSHOT_NAME)/venv.tar

	@rm -rf tmp
	@echo "Upload completed successfully"
