# 手动测试指南

## 📋 测试说明

本目录包含需要手动运行的集成测试脚本，主要用于：
- 验证 DashScope API 功能
- 测试 Wan 模型的图像生成
- 在实现 ComfyUI 节点前验证 SDK 用法

## 🚀 快速开始

### 1. 安装依赖

```bash
cd /Users/wzj/FCProject/ComfyUI-FunArt-APIs/funart_apis
pip install -r requirements.txt
```

需要的依赖：
- `dashscope` - 阿里云 DashScope SDK
- `requests` - 用于下载生成的图片

### 2. 设置 API Key

```bash
# 设置环境变量
export DASHSCOPE_API_KEY='your-api-key-here'

# 验证是否设置成功
echo $DASHSCOPE_API_KEY
```

**获取 API Key：**
1. 访问 https://dashscope.console.aliyun.com/apiKey
2. 登录阿里云账号
3. 创建或复制 API Key

**永久设置（可选）：**
```bash
# 添加到 ~/.zshrc 或 ~/.bashrc
echo "export DASHSCOPE_API_KEY='your-api-key-here'" >> ~/.zshrc
source ~/.zshrc
```

### 3. 运行测试

```bash
# 图像生成测试
python tests/manual/test_dashscope_image.py
```

## 📝 测试脚本

### test_dashscope_image.py - 图像生成测试

测试 DashScope ImageSynthesis（图像生成）功能：

**功能：**
- 使用 **wan2.5-i2i-preview** 模型
- 支持多图输入（图1 + 图2）
- 自动下载并保存生成的图片
- 可自定义提示词和参数

**图片输入方式（三选一）：**

1. **公网URL**（默认，无需准备图片）
   ```python
   image_url_1 = "https://img.alicdn.com/..."
   image_url_2 = "https://img.alicdn.com/..."
   ```

2. **本地文件**
   ```python
   # 绝对路径
   image_url_1 = "file:///path/to/your/image_1.png"
   
   # 相对路径
   image_url_1 = "file://./test_images/image_1.png"
   ```

3. **Base64编码**
   ```python
   # 使用 encode_file 函数
   image_url_1 = encode_file("./test_images/image_1.png")
   ```

**支持的参数：**
```python
ImageSynthesis.call(
    api_key=API_KEY,
    model="wan2.5-i2i-preview",
    prompt="图像生成提示词",
    images=[image_1, image_2],
    
    # 可选参数
    negative_prompt="模糊,低质量",  # 负面提示词
    n=1,                            # 生成图片数量 (1-4)
    size="1280*1280",               # 输出尺寸
    watermark=False,                # 是否添加水印
    seed=12345,                     # 随机种子
)
```

**预期输出：**
```
============================================================
🚀 DashScope ImageSynthesis 图像生成测试
============================================================

【测试】Wan 2.5 图生图模型
------------------------------------------------------------

📷 输入图片:
  图1: https://img.alicdn.com/imgextra/...
  图2: https://img.alicdn.com/imgextra/...

⏳ 正在调用 ImageSynthesis API...

✅ 调用成功!
请求ID: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
生成图片数量: 1

📥 下载图片 1...
  ✅ 已保存: ./output_wan_0_xxxxx.png
  🔗 原始URL: https://...

============================================================
🎉 测试完成!
============================================================
```

**生成的文件：**
- 图片保存在当前目录：`output_wan_0_xxxxx.png`
- 大小通常在 1-2 MB

## 🔧 自定义测试

### 修改提示词

编辑 `test_dashscope_image.py`，找到：
```python
response = ImageSynthesis.call(
    ...
    prompt="将图1中的闹钟放置到图2的餐桌上",  # 修改这里
    ...
)
```

### 使用本地图片

```python
# 替换图片URL
image_url_1 = "file://./my_images/photo1.jpg"
image_url_2 = "file://./my_images/photo2.jpg"
```

### 调整生成参数

```python
response = ImageSynthesis.call(
    ...
    n=2,                    # 生成2张图片
    size="1024*1024",       # 指定尺寸
    seed=54321,             # 改变随机种子
    watermark=True,         # 添加水印
)
```

## ⚠️ 常见问题

### Q: 提示未设置 API Key？

确保运行前已设置环境变量：
```bash
export DASHSCOPE_API_KEY='your-api-key-here'
```

### Q: 提示 dashscope 未安装？

```bash
pip install dashscope requests
```

### Q: 图片格式不支持？

支持的格式：JPG、JPEG、PNG、WebP、GIF

### Q: 使用本地文件时找不到图片？

检查：
1. 路径是否正确（建议使用绝对路径）
2. 文件名是否包含特殊字符
3. 是否添加了 `file://` 前缀

### Q: API 调用超时？

图像生成通常需要 10-30 秒，请耐心等待。如果持续超时：
1. 检查网络连接
2. 验证 API Key 是否有效
3. 检查账户余额

### Q: Base64 编码失败？

确保：
1. 图片文件存在且可读
2. 图片格式正确
3. 文件大小不要太大（建议 < 10MB）

## 🎯 开发流程

1. **运行测试验证 SDK**
   ```bash
   python tests/manual/test_dashscope_image.py
   ```

2. **查看生成的图片**
   ```bash
   open output_wan_0_*.png
   ```

3. **理解 API 调用方式**
   - 查看测试脚本中的代码
   - 了解参数配置
   - 掌握错误处理

4. **实现到 ComfyUI 节点**
   - 在 `nodes_wan/nodes.py` 中创建节点类
   - 参考测试脚本的 API 调用代码
   - 添加 ComfyUI 节点的输入输出定义
   - 处理图片格式转换

## 📚 相关文档

### 官方文档
- DashScope 官方文档: https://help.aliyun.com/zh/dashscope/
- ImageSynthesis API: https://help.aliyun.com/zh/dashscope/developer-reference/api-details-9
- Wan 模型介绍: https://help.aliyun.com/zh/dashscope/developer-reference/tongyi-wanxiang

### 控制台
- API Key 管理: https://dashscope.console.aliyun.com/apiKey
- 百炼控制台: https://bailian.console.aliyun.com/
- 用量统计: https://dashscope.console.aliyun.com/

### SDK 参考
```python
from dashscope import ImageSynthesis
from http import HTTPStatus

# 调用图像生成
response = ImageSynthesis.call(...)

# 检查返回状态
if response.status_code == HTTPStatus.OK:
    # 处理成功结果
    for result in response.output.results:
        print(result.url)
```

## 💡 提示

1. **测试环境隔离**：手动测试不影响单元测试
2. **API 调用成本**：每次测试会消耗 API 配额，请注意用量
3. **结果复现**：使用相同的 `seed` 可以复现相同的结果
4. **网络要求**：需要能够访问阿里云 API 和 OSS
5. **图片存储**：生成的图片URL有效期约30天

## 🔄 后续步骤

测试通过后：
1. ✅ 验证 API 功能正常
2. ✅ 理解参数配置方式
3. ✅ 掌握错误处理机制
4. → 开始实现 `nodes_wan` 中的 ComfyUI 节点
5. → 在 ComfyUI 中测试节点功能

