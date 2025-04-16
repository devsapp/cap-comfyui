# 定义变量
REGION ?= cn-hangzhou
SD_IMAGE = registry.$(REGION).aliyuncs.com/ohyee/fc-demo:cap-sd
OSS_BUCKET ?= dipper-cache-$(REGION)
OSS_SD_BASE_DIR = base/sd/v1.10.1-beta

.PHONY: upgrade
upgrade: build upload-base

# 构建镜像, 需要先构建Agent镜像
.PHONY: build
build:
	docker build -t $(SD_IMAGE) .

# 本地测试运行
# curl -X POST http://localhost:9000/management/start
.PHONY: run
run:
	docker run --gpus all -it --rm -p 9000:9000 -p 8188:8188 $(SD_IMAGE)

# 本地测试登录
.PHONY: exec
exec:
	docker run --gpus all -it --rm -p 9000:9000 -p 8188:8188 --entrypoint /bin/bash $(SD_IMAGE)

# 拉取镜像
.PHONY: pull
pull:
	docker pull $(SD_IMAGE)

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
	@docker rm -f sdImage 2>/dev/null || true
	@docker create --name sdImage $(SD_IMAGE) && \
	docker cp sdImage:/root/stable-diffusion-webui ./tmp/stable-diffusion-webui && \
	docker cp sdImage:/root/venv ./tmp/venv && \
	docker cp sdImage:/root/.cache ./tmp/.cache
	@docker rm sdImage

	@echo "Creating snapshot..."
	@tar -C ./tmp -cf ./tmp/venv.tar venv
	@cd ./tmp && mv ./stable-diffusion-webui/models ./ && zip -rq stable-diffusion-webui.zip stable-diffusion-webui
	@cd ./tmp && zip -rq .cache.zip .cache

	@echo "Uploading files to OSS..."
	@ossutil cp -r ./tmp/models oss://$(OSS_BUCKET)/$(OSS_SD_BASE_DIR)/models && \
	ossutil cp ./tmp/stable-diffusion-webui.zip oss://$(OSS_BUCKET)/$(OSS_SD_BASE_DIR)/snapshots/$(SNAPSHOT_NAME)/stable-diffusion-webui.zip && \
	ossutil cp ./tmp/venv.tar oss://$(OSS_BUCKET)/$(OSS_SD_BASE_DIR)/snapshots/$(SNAPSHOT_NAME)/venv.tar && \
	ossutil cp -r ./tmp/.cache.zip oss://$(OSS_BUCKET)/$(OSS_SD_BASE_DIR)/snapshots/$(SNAPSHOT_NAME)/.cache.zip

	@rm -rf tmp
	@echo "Upload completed successfully"
