# Zstd 压缩优化升级指南

## 📝 更新内容

本次更新将 snapshot 的压缩格式从 `tar/zip` 升级到 `tar.zst`（zstd 压缩），显著提升传输速度和减少 NAS 带宽占用。

### 主要改动

1. **file_ops.py**
   - 新增 `compress_with_zstd()` - 使用 zstd 压缩目录
   - 新增 `extract_zstd()` - 解压 zstd 压缩文件

2. **snapshot_saver.py**
   - `ComfyUISnapshotSaver` - 使用 zstd 压缩 venv 和 comfyui
   - `SDSnapshotSaver` - 使用 zstd 压缩 venv、stable-diffusion-webui 和 cache

3. **snapshot_loader.py**
   - 所有 Loader 类支持 zstd 格式
   - **向后兼容**：自动降级到旧的 tar/zip 格式

---

## 🚀 预期收益

假设原始配置：
- venv: 5 GB (tar 无压缩)
- comfyui: 2 GB (zip 压缩)
- NAS 带宽: 100 MB/s

### 优化前
```
下载时间: 50s (venv) + 20s (comfyui) = 70s
解压时间: 30s (venv) + 10s (comfyui) = 40s
总时间: 110s
```

### 优化后（zstd -10）
```
venv: 0.8 GB (-84%)
comfyui: 0.5 GB (-75%)

下载时间: 8s (venv) + 5s (comfyui) = 13s ⬇️ 81%
解压时间: 6s (venv) + 3s (comfyui) = 9s ⬇️ 77%
总时间: 22s ⬇️ 80%
```

**启动时间从 110 秒降到 22 秒！**

---

## ✅ 环境要求

### 1. 安装 zstd

确保所有运行环境（开发/生产镜像）都安装了 zstd：

```bash
# Debian/Ubuntu
apt-get update && apt-get install -y zstd

# CentOS/RedHat
yum install -y zstd

# macOS
brew install zstd
```

### 2. 验证安装

```bash
# 检查 zstd 是否可用
which zstd
zstd --version

# 检查 tar 是否支持 zstd（可选）
tar --help | grep zstd
```

---

## 📦 迁移步骤

### 方案 A：逐步迁移（推荐，零风险）

#### 阶段 1：测试新格式
```bash
# 1. 在测试环境部署新代码
# 2. 创建一个测试 snapshot
# 3. 验证新 snapshot 可以正常加载

# 手动测试压缩和解压
cd /root
tar -cf - venv | zstd -10 -T0 -o test_venv.tar.zst
zstd -d -c test_venv.tar.zst | tar -xf - -C /tmp
```

#### 阶段 2：生产环境使用新格式
```bash
# 部署新代码到生产环境
# 新创建的 snapshot 将自动使用 zstd 格式
# 旧的 snapshot 仍然可以正常加载（向后兼容）
```

#### 阶段 3：转换旧 snapshot（可选）
```bash
# 如果想转换旧 snapshot 为 zstd 格式以节省存储空间
cd /mnt/auto/snapshots/prod-20231126-120000

# 转换 venv
tar -xf venv.tar
tar -cf - venv | zstd -10 -T0 -o venv.tar.zst
rm -rf venv venv.tar

# 转换 comfyui
unzip comfyui.zip
tar -cf - comfyui | zstd -10 -T0 -o comfyui.tar.zst
rm -rf comfyui comfyui.zip
```

### 方案 B：直接升级（快速）

```bash
# 1. 确保所有环境都安装了 zstd
# 2. 部署新代码
# 3. 创建新的 snapshot（自动使用 zstd）
# 4. 旧 snapshot 保持不变，仍然可用
```

---

## 🧪 测试验证

### 1. 基础功能测试

```bash
# 测试压缩
cd /root
tar -cf - venv | zstd -10 -T0 -o test_venv.tar.zst
ls -lh test_venv.tar.zst

# 测试解压
mkdir -p /tmp/test_extract
zstd -d -c test_venv.tar.zst | tar -xf - -C /tmp/test_extract
ls /tmp/test_extract/venv/

# 清理
rm test_venv.tar.zst
rm -rf /tmp/test_extract
```

### 2. Snapshot 保存测试

```python
# 在 Python 代码中测试
from services.workspace.snapshot_manager import SnapshotManager

manager = SnapshotManager()
result = manager.save("prod")  # 将使用 zstd 压缩

# 检查生成的文件
# ls /mnt/auto/snapshots/prod-YYYYMMDD-HHMMSS/
# 应该看到 venv.tar.zst 和 comfyui.tar.zst
```

### 3. Snapshot 加载测试

```python
# 测试加载新格式
manager = SnapshotManager()
result = manager.load("latest-prod")

# 测试加载旧格式（如果还有旧 snapshot）
# 代码会自动降级到 tar/zip 格式
```

---

## 🔧 故障排查

### 问题 1：找不到 zstd 命令

**错误信息：**
```
FileNotFoundError: [Errno 2] No such file or directory: 'zstd'
```

**解决方案：**
```bash
# 安装 zstd
apt-get update && apt-get install -y zstd
```

### 问题 2：tar 不支持 --zstd 选项

**错误信息：**
```
tar: Conflicting compression options
```

**原因：** 代码已经使用管道方式，这个错误不应该出现。

**如果出现，检查：**
```bash
# 确认 zstd 版本
zstd --version

# 确认 tar 版本
tar --version
```

### 问题 3：旧 snapshot 加载失败

**错误信息：**
```
Failed to copy .../venv.tar.zst to ..., reason: [Errno 2] No such file or directory
```

**原因：** 旧 snapshot 只有 tar/zip 格式。

**解决方案：** 代码已经支持向后兼容，会自动降级。如果仍然失败，检查：
```bash
# 确认旧 snapshot 的文件格式
ls /mnt/auto/snapshots/old-snapshot-name/
# 应该看到 venv.tar 或 venv.tar.zst
```

### 问题 4：解压速度没有提升

**检查项：**
```bash
# 1. 确认使用了 zstd 格式
ls -lh /mnt/auto/snapshots/xxx/
# 应该看到 .tar.zst 文件

# 2. 查看日志确认使用了 zstd
# 日志中应该显示 "extract_zstd" 而不是 "extract"

# 3. 确认多线程是否生效
htop  # 解压时应该看到多个 CPU 核心被使用
```

---

## 📊 监控建议

### 1. 记录压缩解压时间

代码已经通过 timer 记录各阶段耗时：
```python
result = manager.load("latest-prod")
print(result)
# {'snapshot': 'prod-xxx', 'time_clear': 1.2, 'time_download': 13.5, 'time_extract': 9.1}
```

### 2. 对比优化前后

```bash
# 优化前
time_download: 70s
time_extract: 40s

# 优化后
time_download: 13s
time_extract: 9s
```

### 3. 监控 NAS 存储空间

```bash
# 查看 snapshot 目录大小
du -sh /mnt/auto/snapshots/*

# 对比新旧格式的大小
ls -lh /mnt/auto/snapshots/prod-old/venv.tar
ls -lh /mnt/auto/snapshots/prod-new/venv.tar.zst
```

---

## 🎯 最佳实践

### 1. 压缩级别选择

当前使用 **级别 10**（平衡压缩比和速度）：

| 级别 | 场景 | 压缩比 | 速度 |
|-----|------|-------|------|
| -3 | 频繁更新的 snapshot | 低 | 极快 |
| -10 | **推荐**（当前配置） | 中 | 快 |
| -19 | 长期存储的归档 | 高 | 中 |

### 2. 修改压缩级别

如果需要调整，修改 `snapshot_saver.py`：

```python
# 更快的压缩（压缩比稍低）
file_ops.compress_with_zstd(..., level=3)

# 更高的压缩比（速度稍慢）
file_ops.compress_with_zstd(..., level=15)
```

### 3. 定期清理旧 snapshot

```bash
# 删除 7 天前的旧 snapshot
find /mnt/auto/snapshots -type d -mtime +7 -exec rm -rf {} \;

# 或者保留最近 5 个 snapshot
cd /mnt/auto/snapshots
ls -t | tail -n +6 | xargs rm -rf
```

---

## 📚 技术细节

### 压缩实现

使用管道方式实现流式压缩：
```python
tar -cf - venv | zstd -10 -T0 -o venv.tar.zst
```

### 解压实现

使用管道方式实现流式解压：
```python
zstd -d -c venv.tar.zst | tar -xf - -C /root
```

### 向后兼容逻辑

```python
# 优先使用 zstd 格式
if os.path.exists(f"{snapshot_path}/venv.tar.zst"):
    # 使用 zstd
else:
    # 降级到旧格式
```

---

## ✅ 回滚方案

如果需要回滚到旧版本：

1. **代码回滚**：恢复到之前的 commit
2. **Snapshot 兼容**：旧代码无法读取 zstd 格式，需要：
   - 使用旧的 snapshot（tar/zip 格式）
   - 或手动转换 zstd 格式回 tar/zip

```bash
# 将 zstd 转回 tar
zstd -d -c venv.tar.zst | tar -cf venv.tar -
```

---

## 📞 支持

如有问题，请检查：
1. zstd 是否正确安装
2. 日志中的错误信息
3. snapshot 目录的文件格式

升级愉快！🎉

