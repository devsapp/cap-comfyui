# 系统版本与 ComfyUI 版本的关系

## 两套版本号

FunArt 平台存在两套独立的版本号体系：

| 版本类型 | 格式 | 示例 | 含义 |
|---------|------|------|------|
| **系统版本** (System Version) | `A.B.C` | `1.6.7` | FunArt 平台的**服务配置模板**版本，决定 FC 函数的配置结构（单函数/双函数架构、环境变量、部署参数等） |
| **ComfyUI 版本** (COMFYUI_VERSION) | `vX.Y.Z` 或 `vX.Y.Z-suffix` | `v0.3.77-gamma`, `v0.16.4` | ComfyUI 全量镜像的版本，决定**运行时内容**（ComfyUI 源码 + 插件 + Python venv） |

两者**独立演进、互不依赖**：

- 系统版本 `1.6.5` 和 `1.6.6` 都使用 ComfyUI 版本 `v0.3.77-gamma`
- 系统版本 `1.6.7` 仍然使用 `v0.3.77-gamma`
- 新的 ComfyUI 版本 `v0.16.4` 可以搭配系统版本 `1.6.6` 或更高

## 系统版本在哪里定义和使用

### 1. 模板定义（DevsInnerApis 仓库）

```
serverless-deployment-functions/
  DevsInnerApis/src/apis/image-gen/templates/
    templates.js          ← CUR_VERSION = '1.6.7'（新项目默认版本）
    1.6.5/config.js       ← 每个版本的具体配置
    1.6.6/config.js
    1.6.7/config.js       ← 当前默认
```

`templates.js` 中的入口逻辑：

```javascript
const CUR_VERSION = '1.6.7';

const fetchIGStagedConfigs = async (fcContext, params) => {
  const { backend, customization } = params;
  const version = customization || CUR_VERSION;  // customization 可覆盖
  const fetchStagedConfigs = selectFuncWithVersion(backend, version);
  return await fetchStagedConfigs(fcContext, params);
};
```

### 2. 每个模板版本定义的内容

以 `1.6.7/config.js` 为例，核心配置项：

| 配置项 | 值 | 说明 |
|--------|-----|------|
| `image` | `...comfyui-agent:v1.3.11` | Agent 容器镜像 |
| `baseVersion` | `v0.3.77-gamma` | OSS 上的 ComfyUI 快照目录名 |
| `multiModelConfig.files[0].source.path` | `base/comfyui/v0.3.77-gamma/` | 部署时从 OSS 同步到 NAS 的路径 |
| `environmentVariables` | `{BACKEND_TYPE, REGION, MODEL_ASSET_DIR}` | 函数环境变量 |

### 3. 系统版本固化到函数配置

当用户在 FunArt 控制台创建项目时，系统版本被写入函数的 `annotations`：

```javascript
annotations: {
  modelConfig: multiModelConfig,
  artConfig: {
    version: VERSION,  // 如 '1.6.7'
  }
}
```

已创建的项目版本号**不会**随 `CUR_VERSION` 更新而变化，只有**新创建**的项目使用最新默认版本。

### 4. 发布（Publish）时的版本路由

`publish/helper.js` 中的 `_selectAndFillProdConfig()` 根据系统版本选择不同的 Prod 配置架子：

```
version >= 1.6.2  → 双函数架构（CPU + GPU）+ 模型共享
version >= 1.6.1  → 双函数架构（CPU + GPU）
version >= 1.6.0  → FC3 组件单函数
version < 1.6.0   → Model 组件单函数
```

## ComfyUI 版本在哪里定义和使用

### 1. 构建时（Dockerfile）

`src/code/comfyui/shared/Dockerfile.template` 中：
- `COMFYUI_VERSION` 作为 build arg 传入
- `.funart-comfyui-version` 文件写入 ComfyUI 的版本号
- `version.txt` 写入**系统版本**（如 `1.6.6`），用于 built-in 插件兼容性检查

### 2. 运行时（Agent）

`src/code/agent/constants.py` 读取版本：

```python
# 读取 ComfyUI 版本（用于快照目录路由）
COMFYUI_VERSION_FILE = os.path.join(COMFYUI_DIR, '.funart-comfyui-version')
COMFYUI_VERSION = open(COMFYUI_VERSION_FILE).read().strip()  # 如 'v0.16.4'

# 快照目录按 ComfyUI 版本隔离
SNAPSHOT_DIR = os.path.join(MNT_DIR, 'snapshots', COMFYUI_VERSION)
# 结果：/mnt/auto/snapshots/v0.16.4/
```

### 3. OSS 数据（部署时同步）

OSS 上按 ComfyUI 版本组织目录：

```
oss://dipper-cache-{region}/
  base/comfyui/
    v0.3.77-gamma/        ← 旧版本的 ComfyUI + venv 快照
    v0.16.4/              ← 新版本（需要 upload-base）
    v0.3.77-gamma-deepgpu/ ← deepGPU 特殊版本
```

## 版本关系图

```
FunArt 控制台创建项目
  │
  ├── CUR_VERSION = '1.6.7'（系统版本）
  │     │
  │     └── 选择 templates/1.6.7/config.js
  │           │
  │           ├── image = 'comfyui-agent:v1.3.11'     ← 容器镜像
  │           ├── baseVersion = 'v0.3.77-gamma'       ← ComfyUI 版本
  │           │     │
  │           │     └── multiModelConfig.files[0] = 'base/comfyui/v0.3.77-gamma/'
  │           │           │
  │           │           └── 部署时从 OSS 同步到 NAS（一次性）
  │           │
  │           └── ossMountConfig → /mnt/shared/models（只读 FUSE 挂载，与版本无关）
  │
  └── annotations.artConfig.version = '1.6.7'（固化，不随后续 CUR_VERSION 更新变化）
```

## 升级新 ComfyUI 版本需要改什么

以从 `v0.3.77-gamma` 升级到 `v0.16.4` 为例：

1. **cap-comfyui 仓库**：构建新镜像 → `make build-comfyui COMFYUI_VERSION=v0.16.4`
2. **OSS 数据**：`make upload-base` 上传快照到 `base/comfyui/v0.16.4/`
3. **DevsInnerApis 仓库**：创建新模板（或修改现有模板），更新 `image` 和 `baseVersion`
4. **部署 DevsInnerApis**：先预发 `deploy-pre`，验证后生产 `build-prod-*`

只更新镜像而不更新 OSS 数据和模板是**不够的**，因为：
- 新镜像启动时需要从 NAS 加载 snapshot
- Snapshot 数据从 OSS 同步，路径由 `multiModelConfig` 中的 `baseVersion` 决定
- 如果 OSS 上 `base/comfyui/v0.16.4/` 不存在，部署会因找不到数据而失败

## 当前线上状态（2026-05-23）

| 环境 | CUR_VERSION | 镜像 | baseVersion |
|------|-------------|------|-------------|
| **生产线上** | `1.6.6` | `comfyui-agent:v1.3.10` | `v0.3.77-gamma` |
| **代码 master** | `1.6.7` | `comfyui-agent:v1.3.11` | `v0.3.77-gamma` |

- `1.6.7` 已合入 master 但**未部署到生产**
- `1.6.6` → `1.6.7` 差异仅为镜像小版本升级（`v1.3.10` → `v1.3.11`），无架构变化
- v0.16.4 上线计划：修改 `1.6.7/config.js` 的 `image` 和 `baseVersion` 指向新版本，随 `1.6.7` 一起部署到生产
- 镜像和构建产物中的 `version.txt` / `dependency_version.txt` 统一使用 `1.6.7`

### 镜像版本命名规则

**生产镜像** `image-generation-comfyui-agent`：tag 对应 git tag，遵循 semver 递增

| Git Tag / Image Tag | 对应模板版本 |
|---------------------|-------------|
| `v1.0.3-beta.0` | 1.3.0 |
| `v1.0.4-beta.0` | 1.4.0 |
| `v1.1.0-beta.0` | 1.5.0 |
| `v1.2.0` | 1.6.1 |
| `v1.3.1` ~ `v1.3.11` | 1.6.2 ~ 1.6.7 |

**Dev 镜像** `image-generation-comfyui-agent-dev`：tag 为时间戳（如 `20260523143000`），无 git tag，仅供开发测试使用。

镜像版本与系统模板版本**没有固定对应关系**，只是各自递增。

### 构建命令

| 命令 | 构建内容 | 镜像名 | Tag | 预热范围 |
|------|---------|--------|-----|---------|
| `make all` | 仅 Agent 代码 | `agent-dev` | 时间戳 | cn-hangzhou |
| `make release VERSION=v1.4.0` | 仅 Agent 代码 | `agent` | git tag | 全部 5 region |
| `make build-comfyui COMFYUI_VERSION=v0.16.4` | Agent + ComfyUI 全量 | 本地产物，需手动 tag/push/warmup | 自定义 | 手动指定 |

注意：`make all` 和 `make release` 只构建 Agent 镜像，其中的 `/root/built-in/custom_nodes` 来自 Agent Dockerfile 第 1 行硬编码的 source image（`funart-comfyui:v1.6.5`），**不会包含本地 `src/code/comfyui/custom_nodes/` 的修改**。修改了自研插件（如多租插件）必须用 `make build-comfyui`。

## 灰度发布策略

历史上没有使用过 `customization` 参数做灰度。标准做法是：

1. 创建新模板目录 → 更新 `CUR_VERSION`
2. 先部署到**预发环境**（`s3-hangzhou-pre.yaml`，`IS_STAGING=true`）
3. 在预发环境创建新项目验证
4. 验证通过后部署到**生产环境**（`s3-hangzhou-prod.yaml`，`IS_STAGING=false`）
5. 只有部署后**新创建**的项目使用新版本，已有项目不受影响
