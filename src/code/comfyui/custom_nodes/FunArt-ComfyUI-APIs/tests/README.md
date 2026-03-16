# 测试目录

本目录包含项目的所有测试代码，分为两类：

## 📂 目录结构

```
tests/
├── __init__.py           # 测试包初始化
├── conftest.py           # pytest 全局配置
├── pytest.ini            # pytest 配置文件
├── manual/               # 手动测试（需要 API Key）
│   ├── test_dashscope_image.py
│   └── README.md
└── unit/                 # 单元测试（使用 pytest）
    └── README.md
```

## 🧪 测试类型

### 1. Manual Tests（手动测试）

位置：`tests/manual/`

**特点：**
- 需要 API Key 和网络连接
- 用于验证真实的 API 调用
- 在实现 ComfyUI 节点前验证 SDK 功能
- 直接运行 Python 脚本

**运行方式：**
```bash
# 设置 API Key
export DASHSCOPE_API_KEY='your-api-key-here'

# 运行测试
python tests/manual/test_dashscope_image.py
```

**详细文档：** [tests/manual/README.md](manual/README.md)

### 2. Unit Tests（单元测试）

位置：`tests/unit/`

**特点：**
- 使用 pytest 框架
- 不依赖外部 API 或网络
- 快速、独立、可重复
- 适合 CI/CD 自动化

**运行方式：**
```bash
# 运行所有单元测试
pytest tests/unit/ -v

# 查看覆盖率
pytest tests/unit/ --cov=src --cov-report=html
```

**详细文档：** [tests/unit/README.md](unit/README.md)

## 🚀 快速开始

### 运行手动测试

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 设置 API Key
export DASHSCOPE_API_KEY='your-api-key-here'

# 3. 运行图像生成测试
python tests/manual/test_dashscope_image.py
```

### 运行单元测试

```bash
# 安装开发依赖
pip install -r requirements-dev.txt

# 运行测试
pytest
```

## 📝 添加新测试

### 添加手动测试

1. 在 `tests/manual/` 创建新的测试脚本
2. 文件名以 `test_` 开头
3. 脚本应该可以直接运行：`python tests/manual/test_xxx.py`
4. 更新 `tests/manual/README.md`

### 添加单元测试

1. 在 `tests/unit/` 创建测试文件（`test_xxx.py`）
2. 使用 pytest 规范编写测试
3. 运行 `pytest tests/unit/` 验证
4. 更新 `tests/unit/README.md`

## ⚙️ 配置说明

### pytest.ini

```ini
[pytest]
testpaths = unit              # 只运行 unit 目录
norecursedirs = .. manual     # 不运行 manual 目录
```

这样 `pytest` 命令只会运行单元测试，不会尝试运行手动测试。

### conftest.py

全局 pytest 配置，自动将项目根目录添加到 Python 路径。

## 🎯 测试策略

### 什么时候写手动测试？

- ✅ 验证第三方 API 功能
- ✅ 需要真实网络请求
- ✅ 需要查看实际输出（如图片）
- ✅ 探索性测试和原型验证

### 什么时候写单元测试？

- ✅ 测试业务逻辑
- ✅ 测试数据处理函数
- ✅ 测试边界条件
- ✅ 测试错误处理
- ✅ CI/CD 自动化测试

## 📚 相关资源

- pytest 文档: https://docs.pytest.org/
- DashScope 文档: https://help.aliyun.com/zh/dashscope/
- ComfyUI 节点开发: https://docs.comfy.org/essentials/custom_node_overview

