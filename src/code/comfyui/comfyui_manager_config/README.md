# ComfyUI Manager 配置文件

## 目录说明

此目录包含 ComfyUI Manager 的配置文件，用于解决线上服务器无法访问 GitHub 导致的 ComfyUI Manager 无法获取插件列表的问题。

## 文件说明

### config.ini
ComfyUI Manager 的主配置文件，包含：
- 镜像源地址配置
- 自动更新开关
- 本地频道列表开关

### channels.list
插件频道列表文件，包含可访问的插件源地址。

## 使用方式

在 upload-base 时上传到 OSS

在 Makefile 的 `upload-base` 目标中，这些配置文件会一起上传到 OSS。部署时，将其下载到 `/output/default/ComfyUI-Manager/`

容器启动时，这些配置文件会覆盖 ComfyUI Manager 的默认配置，使其使用内网镜像源。

## 配置更新

当需要更新镜像源地址或频道列表时：
1. 修改此目录下的配置文件
2. 重新构建镜像：`make build`
3. 上传到 OSS：`make upload-base`
