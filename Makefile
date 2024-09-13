SHELL := bash

.PHONY: help
help: ## 帮助文件
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {sub("\\\\n",sprintf("\n%22c"," "), $$2);printf "\033[36m%-40s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: FORCE
FORCE:

.PHONY: clean
clean: ## 清理构建文件
	@rm -rf ./src/dist

src/dist/gateway: $(shell find src/code/gateway/ -name "*.go")
	cd src/code/gateway && CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o ../../dist/gateway main.go
	
.PHONY: build
build: src/dist/gateway ## 构建 gateway

.PHONY: registry
registry: build ## 发布到线上
	s registry publish