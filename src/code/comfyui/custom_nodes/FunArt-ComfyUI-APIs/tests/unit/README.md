# 单元测试

本目录包含使用 pytest 运行的单元测试。

## 运行测试

```bash
# 运行所有单元测试
pytest tests/unit/ -v

# 运行特定测试文件
pytest tests/unit/test_wan_nodes.py -v

# 查看测试覆盖率
pytest tests/unit/ --cov=src --cov-report=html
```

## 测试规范

- 测试文件以 `test_` 开头
- 测试类以 `Test` 开头
- 测试方法以 `test_` 开头
- 使用 pytest fixtures 管理测试数据
- 不依赖外部 API 或网络连接

## TODO

- [ ] 添加 nodes_wan 的单元测试
- [ ] 添加 nodes_fc 的单元测试
- [ ] 添加工具函数的单元测试

