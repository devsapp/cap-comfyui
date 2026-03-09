# 定义变量
REGION ?= cn-hangzhou
COMFYUI_IMAGE = comfyui:v0.3.77-beta
OSS_BUCKET ?= dipper-cache-$(REGION)
OSS_COMFYUI_BASE_DIR = base/comfyui/v0.3.77-beta

.PHONY: upgrade
upgrade: build upload-base

# 构建镜像, 需要先构建Agent镜像
# 注意：从 src/code 目录构建，以便访问 agent 和 comfyui 目录
.PHONY: build
build:
	cd .. && docker build -f comfyui/Dockerfile -t $(COMFYUI_IMAGE) .

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
	@# 使用 tar 流式复制并排除 custom_nodes，避免拷贝大量无用文件，提高速度
	docker run --rm --entrypoint tar $(COMFYUI_IMAGE) -cf - -C /root --exclude 'comfyui/custom_nodes' comfyui venv | tar -x -C ./tmp

	@echo "Creating snapshot..."
	tar -cf - -C ./tmp venv | zstd -10 -T0 -o ./tmp/venv.tar.zst
	mv ./tmp/comfyui/models ./tmp/ && tar -cf - -C ./tmp comfyui | zstd -10 -T0 -o ./tmp/comfyui.tar.zst
	mkdir -p ./tmp/custom_nodes

	@echo "Uploading files to OSS..." 
	ossutil cp -r ./tmp/models oss://$(OSS_BUCKET)/$(OSS_COMFYUI_BASE_DIR)/models && \
	ossutil cp -r ./tmp/custom_nodes oss://$(OSS_BUCKET)/$(OSS_COMFYUI_BASE_DIR)/custom_nodes && \
	ossutil cp ./tmp/comfyui.tar.zst oss://$(OSS_BUCKET)/$(OSS_COMFYUI_BASE_DIR)/snapshots/$(SNAPSHOT_NAME)/comfyui.tar.zst && \
	ossutil cp ./tmp/venv.tar.zst oss://$(OSS_BUCKET)/$(OSS_COMFYUI_BASE_DIR)/snapshots/$(SNAPSHOT_NAME)/venv.tar.zst
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

# 更新 Top N 自定义插件列表
# 用法: make update-custom-nodes n=200
# 默认获取 top 100 插件
.PHONY: update-custom-nodes
update-custom-nodes:
	@if [ -z "$(n)" ]; then \
		echo "❌ 错误: 请指定插件数量，例如: make update-custom-nodes n=200"; \
		exit 1; \
	fi
	@echo "🚀 开始获取 Top $(n) ComfyUI 插件..."
	@cd custom_nodes_config && python3 update_topn_plugins.py $(n)
	@echo "✅ 插件列表更新完成！"

# 查看可用的 Makefile 命令
.PHONY: help
help:
	@echo "ComfyUI Makefile 命令列表"
	@echo ""
	@echo "镜像构建与部署："
	@echo "  make build                    - 构建 ComfyUI 镜像"
	@echo "  make run                      - 本地运行镜像"
	@echo "  make exec                     - 进入镜像终端"
	@echo "  make upload-base              - 上传基础镜像到 OSS"
	@echo "  make build-from-snapshot      - 从快照构建生产镜像"
	@echo ""
	@echo "插件管理："
	@echo "  make update-custom-nodes n=50 - 生成 Top N 插件列表"
	@echo "                                  (示例: n=50, n=100, n=200)"
	@echo ""
