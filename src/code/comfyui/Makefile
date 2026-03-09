# 定义变量
REGION ?= cn-hangzhou
COMFYUI_IMAGE = registry.$(REGION).aliyuncs.com/ohyee/fc-demo:cap-comfyui
OSS_BUCKET ?= dipper-cache-$(REGION)
OSS_COMFYUI_BASE_DIR = base/comfyui/v0.3.10-beta

# 模型同步：dev OSS <-> prod OSS
DEV_MOUNT ?= /mnt/funart-dev/models
PROD_MOUNT ?= /mnt/funart-prod/models
DEV_OSS_BUCKET ?= dipper-cache-$(REGION)-dev
PROD_OSS_BUCKET ?= dipper-cache-$(REGION)

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

# 根据已发布的snapshot构建生产用的ComfyUI镜像
COMFYUI_IMAGE_PROD = registry.$(REGION).aliyuncs.com/ohyee/fc-demo:cap-comfyui-prod
BUILD_ENV_SNAPSHOT_DIR ?= /mnt/cap-models/your-project-dir/snapshots/your-snapshot-name
.PHONY: build-from-snapshot
build-from-snapshot:
	@echo "Starting build comfyui-image from snapshot..."
	@rm -rf tmp
	@mkdir -p tmp

	@echo "Handling .cache if necessary..."
	@if [ -f $(BUILD_ENV_SNAPSHOT_DIR)/.cache.zip ]; then \
		cp $(BUILD_ENV_SNAPSHOT_DIR)/.cache.zip ./tmp/ && \
		cd ./tmp && unzip -q .cache.zip && rm .cache.zip; \
	fi

	@echo "Handling comfyui source code..."
	@cp $(BUILD_ENV_SNAPSHOT_DIR)/comfyui.zip ./tmp/ && \
	cd ./tmp && unzip -q comfyui.zip && rm comfyui.zip

	@echo "Handling custom_nodes source code..."
	@mkdir -p ./tmp/comfyui/custom_nodes && \
	cp $(BUILD_ENV_SNAPSHOT_DIR)/custom_nodes.zip ./tmp/ && \
	cd ./tmp && unzip -q custom_nodes.zip -d comfyui/custom_nodes && rm custom_nodes.zip

	@echo "Handling python dependencies..."
	@cp $(BUILD_ENV_SNAPSHOT_DIR)/venv.tar ./tmp/ && \
	cd ./tmp && tar xf venv.tar && rm venv.tar

	@echo "Building comfyui-image..."
	@docker build \
		-f Dockerfile.from_snapshot \
		-t $(COMFYUI_IMAGE_PROD) .

	@rm -rf tmp
	@echo "Build completed successfully"

# ===== 模型管理 =====

# 将 models_xxx.json 融入 models.json（主模型列表），已存在的模型不覆盖
# 用法: make merge-models MODELS_JSON=models/models_20260308.json
MODELS_JSON ?=
.PHONY: merge-models
merge-models:
	@if [ -z "$(MODELS_JSON)" ]; then \
		echo "错误: 请指定 MODELS_JSON"; \
		echo "用法: make merge-models MODELS_JSON=models/models_20260308.json"; \
		exit 1; \
	fi
	@python3 models/merge_models.py $(MODELS_JSON) models/models.json

# 列出 dev 有但 prod 没有的模型，生成 diff_YYYYMMDD.json
# 输出文件位于 models/ 目录下
.PHONY: diff-models
diff-models:
	@DEV_MOUNT=$(DEV_MOUNT) \
	 PROD_MOUNT=$(PROD_MOUNT) \
	 bash models/sync_dev_to_prod.sh --diff-only

# 将 dev 有但 prod 没有的模型同步到 prod OSS
.PHONY: sync-models-to-prod
sync-models-to-prod:
	@DEV_MOUNT=$(DEV_MOUNT) \
	 PROD_MOUNT=$(PROD_MOUNT) \
	 DEV_OSS_BUCKET=$(DEV_OSS_BUCKET) \
	 PROD_OSS_BUCKET=$(PROD_OSS_BUCKET) \
	 bash models/sync_dev_to_prod.sh

# 打印将要执行的 ossutil 同步命令（不实际执行）
.PHONY: sync-models-to-prod-dry-run
sync-models-to-prod-dry-run:
	@DEV_MOUNT=$(DEV_MOUNT) \
	 PROD_MOUNT=$(PROD_MOUNT) \
	 DEV_OSS_BUCKET=$(DEV_OSS_BUCKET) \
	 PROD_OSS_BUCKET=$(PROD_OSS_BUCKET) \
	 bash models/sync_dev_to_prod.sh --dry-run