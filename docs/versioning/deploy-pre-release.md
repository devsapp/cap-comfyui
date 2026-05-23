# FunArt 预发部署流程

## 概述

FunArt 的预发部署涉及两个仓库：

| 仓库 | 作用 | 部署产物 |
|------|------|---------|
| `cap-comfyui` | 构建 ComfyUI 容器镜像 + 上传 OSS 快照 | ACR 镜像 + OSS 数据 |
| `serverless-deployment-functions` | 部署 FunArt 控制台后端（DevsInnerApis） | FC 函数 |

预发和生产使用**同一套镜像**（prod tag），区别仅在 DevsInnerApis 的部署目标不同。

## 完整发布流程

### Phase 1：构建镜像（cap-comfyui 仓库）

在远程构建机 `root@43.106.16.112` 上执行：

```bash
cd /root/cap-comfyui
git fetch origin && git checkout <branch> && git pull origin <branch>

# 1. 构建 ComfyUI 全量镜像（含 agent + ComfyUI + 插件 + venv）
make build-comfyui COMFYUI_VERSION=v0.16.4
# 产物：comfyui:v1.6.7-comfyui-v0.16.4（本地镜像名由 Makefile.common 决定）

# 2. 上传 OSS 快照（ComfyUI + venv 数据，供部署时同步到 NAS）
make upload-comfyui-base COMFYUI_VERSION=v0.16.4
# 上传到：oss://dipper-cache-{region}/base/comfyui/v0.16.4-gamma/
# 注意：不会覆盖旧版本目录（如 v0.3.77-gamma），安全
```

### Phase 2：推送镜像到 ACR（远程构建机）

```bash
REGISTRY="cap-demo-public-registry.cn-hangzhou.cr.aliyuncs.com/cap-app"
LOCAL_IMAGE="comfyui:v1.6.7-comfyui-v0.16.4"

# 1. Tag 为 prod 镜像
docker tag $LOCAL_IMAGE $REGISTRY/image-generation-comfyui-agent:v1.3.12

# 2. 登录 ACR + Push
cd /root/cap-comfyui
make login
docker push $REGISTRY/image-generation-comfyui-agent:v1.3.12

# 3. 预热（预发只需 cn-hangzhou）
make warmup AGENT_IMAGE="$REGISTRY/image-generation-comfyui-agent:v1.3.12" WARMUP_REGIONS="cn-hangzhou"

# 4.（可选）Tag 为 funart-comfyui source image，供后续 agent 构建引用
docker tag $LOCAL_IMAGE cap-demo-public-registry.cn-hangzhou.cr.aliyuncs.com/aliyunfc/funart-comfyui:v1.6.7
```

### Phase 3：更新模板（serverless-deployment-functions 仓库）

本地操作：

```bash
cd ~/projects/nodejs/serverless-deployment-functions
git checkout master && git pull origin master
git checkout -b feat/comfyui-v0.16.4
```

修改 `DevsInnerApis/src/apis/image-gen/templates/1.6.7/config.js`：

```javascript
// 修改前
let image = '...image-generation-comfyui-agent:v1.3.11';
let baseVersion = 'v0.3.77-gamma';

// 修改后
let image = '...image-generation-comfyui-agent:v1.3.12';
let baseVersion = 'v0.16.4-gamma';
```

提交并推送：

```bash
git add DevsInnerApis/src/apis/image-gen/templates/1.6.7/config.js
git commit -m "feat(image-gen): 升级模板 1.6.7 至 ComfyUI v0.16.4"
git push origin feat/comfyui-v0.16.4
```

### Phase 4：部署 DevsInnerApis 到预发

```bash
cd ~/projects/nodejs/serverless-deployment-functions/DevsInnerApis
npm install
s deploy -t s3-hangzhou-pre.yaml -y --use-local
```

#### 前置条件

需要配置 `s` CLI 的 access：

```bash
s config add -a fc-console
# 输入 AccountID: 1813774388953700
# 输入 AccessKeyID 和 AccessKeySecret（找 AK 管理员获取）
```

access 配置保存在 `~/.s/access.yaml`。

#### IP 白名单

`fc-console` AK 有 RAM IP 白名单限制。如果本地 IP 不在白名单内（报 401 错误），可以：
1. 让 AK 管理员添加你的出口 IP
2. 在阿里云 ECS 上执行部署（ECS IP 通常已在白名单内）

### Phase 5：预发验证

预发 FunArt 控制台地址：https://pre-functionai.console.aliyun.com/funart/cn-hangzhou/comfyui/workspaces/

在预发 FunArt 控制台创建新 ComfyUI 项目，验证：
1. 新项目使用 v0.16.4 镜像
2. ComfyUI 正常启动
3. 多租插件正常工作

注意：只有**新创建**的项目使用新模板，已有项目不受影响。

### Phase 6：部署生产

预发验证通过后，部署到生产：

```bash
cd ~/projects/nodejs/serverless-deployment-functions/DevsInnerApis

# 杭州 + 新加坡
s deploy -t s3-hangzhou-prod.yaml -y --use-local
s deploy -t s3-singapore-prod.yaml -y --use-local

# 北京 + 上海 + 深圳 + 其他
s deploy -t s3-beijing-prod.yaml -y --use-local
s deploy -t s3-shanghai-prod.yaml -y --use-local
s deploy -t s3-shenzhen-prod.yaml -y --use-local
s deploy -t s3-alcatraz-prod.yaml -y --use-local
s deploy -t s3-hongkong-prod.yaml -y --use-local
```

生产部署前需要：
1. 所有 region 的镜像已 push + warmup
2. 所有 region 的 OSS 快照已上传

## 关键文件

### cap-comfyui 仓库

| 文件 | 作用 |
|------|------|
| `Makefile` | 顶层构建入口（`make build-comfyui`, `make release`, `make warmup`） |
| `src/code/comfyui/v0.16.4/Makefile` | v0.16.4 版本构建配置（`COMFYUI_VERSION`, `OSS_COMFYUI_BASE_DIR`） |
| `src/code/comfyui/shared/Makefile.common` | 共享构建逻辑（`build`, `upload-base`, 镜像命名） |
| `src/code/comfyui/shared/Dockerfile.template` | ComfyUI 全量镜像 Dockerfile |
| `src/code/agent/Dockerfile` | Agent 镜像 Dockerfile |

### serverless-deployment-functions 仓库

| 文件 | 作用 |
|------|------|
| `DevsInnerApis/src/apis/image-gen/templates/templates.js` | 模板入口，`CUR_VERSION` 决定新项目默认版本 |
| `DevsInnerApis/src/apis/image-gen/templates/1.6.7/config.js` | 模板配置（`image`, `baseVersion`, `multiModelConfig`） |
| `DevsInnerApis/s3-hangzhou-pre.yaml` | 预发部署配置（`IS_STAGING=true`） |
| `DevsInnerApis/s3-hangzhou-prod.yaml` | 生产部署配置（`IS_STAGING=false`） |

## 预发 vs 生产的区别

| 配置项 | 预发 | 生产 |
|--------|------|------|
| yaml 文件 | `s3-hangzhou-pre.yaml` | `s3-hangzhou-prod.yaml` |
| FC 函数名 | `fc-console-service-pre$DevsInnerApis` | `fc-console-service$DevsInnerApis` |
| `IS_STAGING` | `true` | `false` |
| logstore | `fc-console-function-pre` | `fc-console-function-prod` |
| 镜像 | 与生产相同（prod tag） | prod tag |

## 注意事项

1. **Makefile 中的 `build-pre-fc3` 命令已失效** — 它引用的 `s3-hangzhou.yaml` 文件不存在，实际预发文件名是 `s3-hangzhou-pre.yaml`，需要直接用 `s deploy` 命令
2. **镜像必须先 warmup** — 否则 FC 冷启动拉取镜像极慢
3. **OSS 快照按版本隔离** — `upload-base` 上传到 `base/comfyui/{version}-gamma/`，不会影响其他版本
4. **只有新创建的项目使用新模板** — 已有项目的 `artConfig.version` 固化在函数 annotations 中，不会改变
