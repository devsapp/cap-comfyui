# 自定义 ComfyUI 镜像构建与部署指南

本目录提供了自定义 ComfyUI 镜像构建和部署到阿里云函数计算的完整解决方案。您可以根据需要定制 ComfyUI 版本、添加自定义节点、预置模型等。

## 📋 目录结构

```
build-your-own/
├── comfyui/            # ComfyUI 配置目录
│   ├── Dockerfile      # 镜像构建文件
│   ├── s.yaml          # Serverless Devs 部署配置
└── └── README.md       # 本文档
```

## 🐳 构建镜像

### 准备工作

确保您已安装以下工具：
- [Docker](https://docs.docker.com/get-docker/)
- [Serverless Devs CLI](https://docs.serverless-devs.com/serverless-devs/install)

### 自定义操作

在构建镜像前，您可以根据需要修改 `comfyui/Dockerfile` 文件：

#### 1. 修改 ComfyUI 版本

在 Dockerfile 第 21 行修改版本号：

```dockerfile
git checkout "v0.3.50"  # 修改为您需要的版本
```

查看可用版本：[ComfyUI Releases](https://github.com/comfyanonymous/ComfyUI/releases)

#### 2. 添加自定义节点

取消注释并修改 Dockerfile 第 32-43 行，添加您需要的插件：

```dockerfile
# 添加单个插件
RUN cd ${COMFYUI_DIR}/custom_nodes && \
    git clone https://github.com/your-username/your-plugin.git && \
    cd your-plugin && \
    git checkout "v1.0.0"  # 指定版本（可选）

# 添加多个插件
RUN cd ${COMFYUI_DIR}/custom_nodes && \
    git clone https://github.com/Fannovel16/comfyui_controlnet_aux && \
    git clone https://github.com/cubiq/ComfyUI_IPAdapter_plus
```

#### 3. 预置模型（可选）

在 `models` 阶段添加模型下载：

```dockerfile
# 使用 aria2c 下载大文件
RUN aria2c -x 16 -s 16 -k 1M \
    "https://huggingface.co/runwayml/stable-diffusion-v1-5/resolve/main/v1-5-pruned-emaonly.safetensors" \
    -d "/models/checkpoints" -o "sd1.5.safetensors"
```

#### 4. 添加 Python 依赖

在 `dependencies` 阶段添加额外的 Python 包：

```dockerfile
RUN --mount=type=cache,target=/root/.cache/pip \
    venv/bin/pip install --no-cache-dir \
        opencv-python \
        transformers \
        your-custom-package
```

### 构建命令

```bash
# 进入 comfyui 目录
make build-comfyui
```
## ☁️ 部署至阿里云函数计算

### 前期准备

1. **安装 Serverless Devs CLI**，[参考文档](https://help.aliyun.com/zh/functioncompute/fc-3-0/developer-reference/serverless-devs-1/)
   ```bash
   npm install -g @serverless-devs/g
   ```
   
2. **配置阿里云访问凭证**，[参考文档](https://docs.serverless-devs.com/user-guide/config/)
   ```bash
   s config add
   ```
   按提示输入您的 AccessKey ID 和 AccessKey Secret

3. **验证配置**
   ```bash
   s config get
   ```

### 配置部署参数

编辑 `comfyui/s.yaml` 文件，根据需要修改以下配置：

#### 基本配置

```yaml
vars:
  region: "cn-hangzhou"                    # 部署地域
  image: "your-registry/comfyui:custom"   # 您的自定义镜像地址
  functionName: "my-comfyui"              # 函数名称
  instanceConcurrency: 100                # 实例并发度
```

#### 资源配置

```yaml
resources:
  comfyui:
    props:
      runtime: "custom-container"
      timeout: 600                # 函数超时时间（秒）
      memorySize: 32768          # 内存大小（MB）
      cpu: 8                     # CPU 核数
      diskSize: 61440           # 磁盘大小（MB）
      gpuConfig:
        gpuMemorySize: 49152    # GPU 内存（MB）
        gpuType: fc.gpu.ada.1   # GPU 型号
```

#### 网络与存储配置

```yaml
      vpcConfig: auto           # VPC 配置（自动创建）
      nasConfig: auto          # NAS 配置（自动创建）
      logConfig: auto          # 日志配置（自动创建）
```

### 部署命令

#### 完整部署流程

```bash
# 1. 进入部署目录
cd comfyui

# 2. 预检查配置
s plan

# 3. 部署函数
s deploy --skip-push
```

### 验证部署

部署成功后，您将获得类似以下的输出：

```
✔ Deploy completed

comfyui: 
  region:   cn-hangzhou
  function: 
    name: my-comfyui
    runtime: custom-container
    handler: 'true'
    timeout: 600
    internetAccess: true
  url: 
    system_url:    https://12345-cn-hangzhou.fcapp.run
    custom_domain: https://your-domain.com (if configured)
  triggers: 
    - triggerName: defaultTrigger
      type:        http
      status:      Enabled
```

访问提供的 URL 即可使用您的自定义 ComfyUI。

### 常用管理命令

```bash
# 查看函数信息
s info

# 查看函数日志
s logs --tail

# 删除函数
s remove

# 查看函数指标
s metrics

# 进入函数实例终端
s exec
```

## 🚀 调用方式
部署完成后，您可以通过两种方式使用 ComfyUI：WebUI 界面调用和 API 调用。

### 上传模型至 models
将模型上传至配置的 OSS models 目录下即可。
OSS 目录在 s.yaml 中配置

### 调用方式一：WebUI 调用

WebUI 调用提供了图形化的操作界面，适合交互式使用和调试。
部署完成后，会生成一个有一天访问时间的临时域名，您直接在浏览器中打开域名即可访问 ComfyUI：

```
https://comfyui.devsapp.net
```
### 调用方式二：通过 API 调用
对于 API 调用，建议将实例并发度设置为 1：

```yaml
vars:
  instanceConcurrency: 1  # API 调用建议设置为 1
```
调用方式参考 [文档](https://help.aliyun.com/zh/functioncompute/fc-3-0/call-the-comfyui-api)



## 🔧 高级配置

### 自定义域名

在 `s.yaml` 中添加自定义域名配置：

```yaml
customDomains:
  - domainName: your-domain.com
    protocol: HTTP,HTTPS
    routeConfig:
      routes:
        - path: /*
          methods:
            - GET
            - POST
          functionName: ${vars.functionName}
```

### 环境变量

```yaml
environmentVariables:
  BACKEND_TYPE: 'comfyui'
  CUSTOM_VAR: 'your-value'
  PYTHON_PATH: '/root/venv/bin/python'
```

### VPC 和 NAS 手动配置

如果需要使用特定的 VPC 或 NAS，可以手动指定：

```yaml
vpcConfig:
  vpcId: vpc-xxxxxxx
  securityGroupId: sg-xxxxxxx
  vswitchIds:
    - vsw-xxxxxxx

nasConfig:
  userId: 10003
  groupId: 10003
  mountPoints:
    - serverAddr: "xxxxxxx-xxx.cn-hangzhou.nas.aliyuncs.com"
      nasDir: "/comfyui"
      fcDir: "/mnt/auto"
```

## 📊 监控与调试

### 查看函数日志

### 调试方法

1. **本地测试镜像**
   ```bash
   docker run --gpus all -it --rm -p 9000:9000 -p 8188:8188 -v ~/mnt:/mnt/auto -e SKIP_SNAPSHOT_LOADING=true -e AUTO_LAUNCH_SNAPSHOT_NAME=latest comfyui:v1
   ```

2. **进入函数实例**
   ```bash
   s exec -it {containerid} "/bin/bash"
   ```

## ❗ 常见问题

### 构建问题

**Q: 构建时网络超时怎么办？**
A: 设置代理或使用镜像源：
```dockerfile
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/
RUN git config --global http.proxy http://your-proxy:port
```

**Q: 镜像太大怎么办？**
A: 优化 Dockerfile：
- 使用多阶段构建
- 清理不必要的缓存
- 选择更小的基础镜像

### 部署问题

### 使用问题

**Q: 如何持久化模型和数据？**
A: 配置 NAS 存储：
```yaml
nasConfig: auto  # 自动创建并挂载 NAS
```

## 📚 参考资源

- [ComfyUI 官方仓库](https://github.com/comfyanonymous/ComfyUI)
- [Serverless Devs 文档](https://docs.serverless-devs.com/)
- [阿里云函数计算文档](https://help.aliyun.com/product/50980.html)
- [容器镜像服务文档](https://help.aliyun.com/product/60716.html)

## 💬 获得帮助

如果您在使用过程中遇到问题：

1. 查看 [常见问题](#❗-常见问题) 部分
2. 查看 [comfyui/readme.md](comfyui/readme.md) 中的详细配置说明
3. 在项目 Issues 中提问
4. 加入 Serverless Devs 社区群讨论

---

🎉 **祝您使用愉快！**如果本指南对您有帮助，欢迎 Star 本项目！
