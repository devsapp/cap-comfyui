# ComfyUI 启动逻辑与 ModelConfig 的作用

## 整体流程概览

从用户在 FunArt 控制台点击"创建项目"到 ComfyUI 实例可用，涉及两个阶段：

```
阶段一：部署（Deploy）                          阶段二：运行时启动（Runtime）
┌─────────────────────────────────┐          ┌─────────────────────────────────┐
│  FunArt 控制台                    │          │  FC 实例启动                      │
│    │                             │          │    │                             │
│    ├── 选择模板 (1.6.7/config.js) │          │    ├── 拉取容器镜像                 │
│    ├── 生成 FC 函数配置            │          │    ├── 挂载 NAS / OSS              │
│    ├── modelConfig → 同步 OSS→NAS │          │    ├── /initialize 生命周期         │
│    └── 创建 FC 函数               │          │    │   ├── 加载 snapshot            │
│                                  │          │    │   ├── 安装 custom_nodes        │
│                                  │          │    │   ├── 启动 ComfyUI 子进程       │
│                                  │          │    │   └── 等待就绪（TCP probe）      │
│                                  │          │    └── 开始接受流量                  │
└─────────────────────────────────┘          └─────────────────────────────────┘
```

---

## 阶段一：部署时的数据同步

### ModelConfig 是什么

`modelConfig` 是 FunArt 平台（DevsInnerApis）生成的数据同步配置，用于在**部署时**将 OSS 上的 ComfyUI 快照数据一次性复制到 NAS。

```javascript
// 1.6.7/config.js 中的 modelConfig 定义
let multiModelConfig = {
  solution: 'funArt',
  source: {
    uri: `oss://dipper-cache-${region}.oss-${region}.aliyuncs.com`  // OSS 源
  },
  target: {
    uri: `nas://auto`  // NAS 目标
  },
  downloadStrategy: {
    mode: 'once',  // 只同步一次
  },
  files: [
    {
      source: { path: `base/comfyui/v0.3.77-gamma/` },  // OSS 上的快照路径
      target: { path: '' }                                // NAS 目标路径（相对于函数挂载点）
    }
  ]
}
```

### ModelConfig 怎么传递到服务端

FunArt 控制台生成配置后，通过两种方式之一部署到 FC：

#### 路径 A：FunArt 平台（fc3 组件） → FC CreateFunction API

```
FunArt 控制台
  └── fetchIGStagedConfigs()（templates/1.6.7/config.js）
        └── 生成 gpuProps，其中：
              ├── annotations.modelConfig = multiModelConfig  ← 存入 annotations
              └── 其他 FC 函数配置
```

`modelConfig` 存储在函数的 `annotations` 中，供平台后续读取和更新使用。FC 函数本身不处理 `modelConfig`——数据同步由 FunArt 平台的部署流程（DevsInnerApis）负责编排。

#### 路径 B：s-yaml 直接部署（model@0.2.32 组件） → deployCustomContainer API

```
s deploy -t s-dev-v0164-gray.yaml
  └── model@0.2.32 组件
        └── newCustomContainerDeploy()
              ├── 构造 DeployCustomContainerRequest
              │     ├── modelConfig = { sourceType: 'multi', multiModelConfig: [...] }
              │     └── 其他 FC 函数配置
              └── 调用 devs.cn-hangzhou.aliyuncs.com/deployCustomContainer
                    └── 服务端执行 OSS → NAS 数据同步
```

注意两种路径的 `modelConfig` **格式不同**：

| 字段 | fc3 组件（FunArt 平台） | model@0.2.32 组件（s-yaml） |
|------|------------------------|---------------------------|
| 格式 | `{solution, source, target, downloadStrategy, files}` | `{sourceType: 'multi', multiModelConfig: [{type: 'oss', bucket, path, region}]}` |
| 数据同步 | 平台编排 | `deployCustomContainer` API 服务端执行 |

两者最终效果相同：将 OSS 上的快照数据复制到 NAS。

### ModelConfig vs ossMountConfig

这是两个**完全独立**的机制：

| 特性 | modelConfig | ossMountConfig |
|------|-------------|----------------|
| 时机 | 部署时，一次性 | 运行时，持续挂载 |
| 方式 | OSS → NAS 文件复制 | OSS FUSE 只读挂载 |
| 用途 | ComfyUI 快照（源码 + venv + 插件） | 共享模型池（checkpoints, loras 等） |
| OSS 路径 | `base/comfyui/{version}/` | `/function-art/comfyui/models/` |
| 挂载点 | NAS → `/mnt/auto/snapshots/{version}/` | `/mnt/shared/models`（只读） |
| 可写 | 是（NAS） | 否（只读 FUSE） |

```
实例内目录结构：

/mnt/auto/                          ← NAS 挂载（可读写）
  snapshots/
    v0.3.77-gamma/                  ← modelConfig 同步的快照数据
      comfyui/                      ←   ComfyUI 源码
      venv.tar                      ←   Python 虚拟环境
  custom_nodes/                     ← 用户安装的插件（NAS 持久化）
  input/ output/                    ← 用户数据

/mnt/shared/models/                 ← ossMountConfig 的只读挂载
  checkpoints/                      ← 平台公共模型
  loras/
  vae/
```

---

## 阶段二：运行时启动

### 入口：entrypoint.bash

1. 根据 `$REGION` 判断是否国内，国内则配置 HF/GitHub/UV 镜像代理
2. 启动 Flask agent（`main.py`），监听 9000 端口

### FC 生命周期：/initialize

FC 冷启动时调用 `/initialize`，由 `routes.routes.Routes` 处理：

```python
# routes/routes.py - /initialize 处理逻辑
def _initialize():
    # 1. 加载快照
    management_service.start(snapshot_name)

    # 2. 如果配置了 PREWARM_PROMPT，预热模型
    if PREWARM_PROMPT:
        management_service.prewarm(PREWARM_PROMPT)
```

### ManagementService.start() 详细流程

```
ManagementService.start(snapshot_name)
  │
  ├── 1. SnapshotManager.load_snapshot()
  │     │
  │     ├── 选择 Loader：
  │     │   ├── ComfyUIDevSnapshotLoader（工作空间模式）
  │     │   └── ComfyUIProdSnapshotLoader（API/在线服务模式）
  │     │
  │     └── Loader 执行：
  │           ├── 从 NAS 找到快照目录
  │           │   路径：/mnt/auto/snapshots/{COMFYUI_VERSION}/{snapshot_name}/
  │           │
  │           ├── 解压 venv.tar → /root/venv/
  │           │
  │           └── 创建软链接：
  │               ├── models/* → /mnt/auto/snapshots/.../comfyui/models/*
  │               ├── custom_nodes/* → /mnt/auto/snapshots/.../comfyui/custom_nodes/*
  │               └── .cache → /mnt/auto/snapshots/.../comfyui/.cache
  │
  ├── 2. 设置 built-in 插件（delta 机制）
  │     │
  │     └── setup_builtin_custom_nodes()
  │           ├── 扫描 /root/built-in/custom_nodes/（镜像内预置）
  │           ├── 创建 /root/built-in/custom_nodes_delta/ 目录
  │           │   └── 对每个 built-in 插件：如果用户 NAS 中无同名插件，创建软链接
  │           └── 写入 extra_model_paths.yaml
  │               └── funart_builtin_custom_nodes → /root/built-in/custom_nodes_delta/
  │
  ├── 3. 安装 custom_nodes 依赖（仅工作空间模式）
  │     │
  │     └── 根据 AUTO_INSTALL_NODES 环境变量：
  │           ├── "*"      → 安装所有插件的 requirements.txt
  │           ├── JSON dict → 安装指定插件
  │           └── 其他     → 跳过（API 模式默认跳过）
  │
  ├── 4. 启动 ComfyUI 子进程
  │     │
  │     └── ComfyUIProcessManager.start()
  │           ├── 构造启动命令：
  │           │   python main.py --listen 0.0.0.0 --port 8188
  │           │     --input-directory /mnt/auto/input/{user}
  │           │     --output-directory /mnt/auto/output/{user}
  │           │     --extra-model-paths-config /root/comfyui/extra_model_paths.yaml
  │           │     {CUSTOM_BOOT_ARGS}
  │           │
  │           └── 等待就绪（TCP probe 端口 8188，超时 READINESS_TIMEOUT=900s）
  │
  └── 5. 状态 → RUNNING，开始接受流量
```

### 两种运行模式

同一个 Agent 代码根据环境变量进入不同模式：

```
AUTO_LAUNCH_SNAPSHOT_NAME 设置?
  │
  ├── 否 → 工作空间模式（Project-Development）
  │         ├── USE_API_MODE = False
  │         ├── 用户通过浏览器访问 ComfyUI UI
  │         ├── 快照类型：dev（pre-stop 时自动保存）
  │         ├── custom_nodes 安装：执行
  │         └── 流量路由：catch-all proxy → 127.0.0.1:8188
  │
  └── 是 → API/在线服务模式
            ├── USE_API_MODE = True
            ├── 通过 /api/serverless/* 执行 workflow
            ├── 快照类型：prod（由 publish 流程生成）
            ├── custom_nodes 安装：跳过
            └── 流量路由：ServerlessApiRoutes 处理

COMFYUI_MODE = cpu|gpu
  │
  ├── gpu（默认）→ 正常启动 ComfyUI，GPU 推理
  └── cpu → ComfyUI 加 --cpu 启动，用于双函数架构的前端网关
```

### COMFYUI_VERSION 与快照目录路由

Agent 启动时通过 `.funart-comfyui-version` 文件确定 ComfyUI 版本，从而定位快照目录：

```python
# constants.py
COMFYUI_VERSION = read_file('/root/comfyui/.funart-comfyui-version').strip()
# 结果如 'v0.16.4'

SNAPSHOT_DIR = os.path.join(MNT_DIR, 'snapshots', COMFYUI_VERSION)
# 结果：/mnt/auto/snapshots/v0.16.4/
```

这意味着：
- 不同 ComfyUI 版本的快照**互相隔离**
- 部署时 `modelConfig` 同步的数据必须放到对应版本目录
- 镜像中的 `.funart-comfyui-version` 和 `modelConfig` 中的 `baseVersion` 必须匹配

---

## 端到端数据流

以下是从创建项目到 ComfyUI 可用的完整数据流：

```
1. 创建项目
   FunArt 控制台 → DevsInnerApis → templates/1.6.7/config.js
     → image = 'comfyui-agent:v1.3.11'
     → baseVersion = 'v0.3.77-gamma'
     → modelConfig.files = [{source: 'base/comfyui/v0.3.77-gamma/', target: ''}]

2. 部署函数
   DevsInnerApis → FC CreateFunction
     → 创建 GPU 函数 art-{projectName}-{random}
     → modelConfig 数据同步：
        OSS: dipper-cache-{region}/base/comfyui/v0.3.77-gamma/
          → NAS: /mnt/auto/snapshots/v0.3.77-gamma/（包含 comfyui/ 和 venv.tar）
     → ossMountConfig 配置 FUSE 挂载：
        OSS: /function-art/comfyui/models/ → /mnt/shared/models（只读）

3. 实例冷启动
   FC 拉取镜像 comfyui-agent:v1.3.11
     → 容器内 /root/comfyui/.funart-comfyui-version = 'v0.3.77-gamma'
     → SNAPSHOT_DIR = /mnt/auto/snapshots/v0.3.77-gamma/

4. /initialize
   Agent 加载快照：
     /mnt/auto/snapshots/v0.3.77-gamma/latest-dev/
       → 解压 venv.tar → /root/venv/
       → 软链接 models, custom_nodes → /root/comfyui/
     设置 built-in 插件 delta
     启动 ComfyUI 子进程

5. Ready
   ComfyUI 监听 8188，Agent 代理流量 9000 → 8188
   共享模型通过 /mnt/shared/models/ 可用（OSS FUSE 挂载，与快照独立）
```

---

## 关键配置文件对照表

| 文件位置 | 说明 | 格式 |
|---------|------|------|
| `DevsInnerApis/.../templates/1.6.7/config.js` | FunArt 平台模板，定义 image、baseVersion、modelConfig | JS |
| `DevsInnerApis/.../publish/helper.js` | Publish 逻辑，从 dev 配置生成 prod 配置 | JS |
| `src/code/comfyui/s-dev-v0164-gray.yaml` | s-yaml 直接部署配置（model@0.2.32 组件） | YAML |
| `src/code/agent/constants.py` | Agent 运行时常量，读取 COMFYUI_VERSION | Python |
| `src/code/agent/services/workspace/snapshot_loader.py` | 快照加载器，从 NAS 恢复工作空间 | Python |
| `src/code/agent/services/custom_nodes/builtin_custom_nodes.py` | Built-in 插件 delta 机制 | Python |
