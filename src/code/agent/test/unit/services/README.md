## 🚀 运行测试

### 前置条件

```bash
# 安装测试依赖
pip install pytest pytest-cov pytest-mock flask
```

### 运行所有测试

```bash
# 在项目根目录
cd /Users/cici/workspace/code/cap-comfyui/src/code/agent

# 运行单个测试文件
pytest test/unit/services/serverless_api_test.py -v

# 运行所有测试
pytest test/unit/services/ -v

# 显示覆盖率
pytest test/unit/services/serverless_api_test.py --cov=services.serverlessapi --cov-report=html

# 运行特定测试
pytest test/unit/services/serverless_api_test.py::test_api_prompt_success -v
```

### 运行测试并生成报告

```bash
# 生成详细的测试报告
pytest test/unit/services/serverless_api_test.py \
    -v \
    --tb=short \
    --cov=services.serverlessapi \
    --cov-report=term-missing \
    --cov-report=html:coverage_html

# 查看 HTML 报告
open coverage_html/index.html
```

