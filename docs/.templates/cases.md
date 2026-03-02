# [功能名称] 测试用例

> 本文档在 PLAN 阶段创建，定义测试用例和验收标准

## 1. 测试概述

### 测试范围
- **功能范围**：描述测试覆盖的功能模块
- **测试类型**：
  - ✅ 单元测试
  - ✅ 集成测试
  - ⬜ 端到端测试
  - ⬜ 性能测试

### 测试环境
- **Python 版本**：3.x
- **测试框架**：pytest + unittest.mock
- **依赖服务**：[列出需要的外部服务]
- **测试数据**：[描述测试数据来源]

---

## 2. 单元测试用例

### 2.1 [类名/模块名]

#### 测试用例 1.1：正常流程 - [具体场景]

**测试目标**：验证正常情况下的功能行为

**前置条件**：
- 条件 1
- 条件 2

**测试步骤**：
1. 初始化测试对象
2. 调用目标方法
3. 验证返回结果

**预期结果**：
- 返回值符合预期
- 状态正确更新

**实现代码**：

```python
def test_normal_flow(self):
    """测试用例 1.1: 正常流程"""
    # Given - 准备测试数据
    manager = TargetClass()
    
    # When - 执行操作
    result = manager.method(param1="value1")
    
    # Then - 验证结果
    assert result is not None
    assert result.status == "success"
```

**状态**：⏳ 待实现 / 🔄 开发中 / ✅ 已通过 / ❌ 失败

---

#### 测试用例 1.2：异常处理 - [具体异常场景]

**测试目标**：验证异常情况的处理

**前置条件**：
- 模拟错误条件

**测试步骤**：
1. 准备异常触发条件
2. 调用目标方法
3. 验证异常抛出

**预期结果**：
- 抛出正确的异常类型
- 异常消息准确
- 错误码正确

**实现代码**：

```python
def test_error_handling(self):
    """测试用例 1.2: 异常处理"""
    # Given
    manager = TargetClass()
    
    # When & Then
    with pytest.raises(ExpectedError) as exc_info:
        manager.method(param1=None)
    
    assert exc_info.value.code == 400
    assert "expected message" in str(exc_info.value)
```

**状态**：⏳ 待实现

---

#### 测试用例 1.3：边界值测试

**测试目标**：验证边界条件处理

**测试数据**：
- 空值：`None`, `""`, `[]`, `{}`
- 边界值：最大值、最小值、零值
- 特殊值：负数、超大数值

**实现代码**：

```python
@pytest.mark.parametrize("input_value,expected", [
    (None, InvalidRequestError),
    ("", InvalidRequestError),
    ("valid_value", "success"),
    (0, "success"),
    (-1, InvalidRequestError),
])
def test_boundary_values(self, input_value, expected):
    """测试用例 1.3: 边界值测试"""
    # 测试逻辑
    pass
```

**状态**：⏳ 待实现

---

### 2.2 [另一个类名/模块名]

（按需添加更多测试用例）

---

## 3. 集成测试用例

### 3.1 端到端流程测试

#### 测试用例 3.1：完整业务流程

**测试目标**：验证完整的业务流程

**测试场景**：
描述一个完整的用户使用场景

**测试步骤**：
1. 步骤 1 - 初始化
2. 步骤 2 - 执行主流程
3. 步骤 3 - 验证结果

**预期结果**：
- 流程顺利完成
- 各个环节数据正确传递
- 最终状态符合预期

**实现代码**：

```python
def test_end_to_end_flow(self, app, manager):
    """测试用例 3.1: 完整业务流程"""
    # Given
    # 准备完整流程的测试数据
    
    # When
    # 执行完整流程
    
    # Then
    # 验证各个环节
    pass
```

**状态**：⏳ 待实现

---

## 4. 特殊场景测试

### 4.1 并发测试

**测试目标**：验证多线程/多进程场景下的正确性

**测试场景**：
- 并发读
- 并发写
- 并发读写混合

**实现代码**：

```python
def test_concurrent_operations(self):
    """测试用例 4.1: 并发操作"""
    import threading
    
    results = []
    def worker():
        result = manager.method()
        results.append(result)
    
    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    # 验证并发安全性
    assert len(results) == 10
    assert all(r.is_valid for r in results)
```

**状态**：⏳ 待实现

---

### 4.2 性能测试

**测试目标**：验证性能指标

**性能指标**：
- 响应时间：< X ms
- 吞吐量：> Y req/s
- 内存使用：< Z MB

**实现代码**：

```python
def test_performance_under_load(self):
    """测试用例 4.2: 性能测试"""
    import time
    
    start = time.time()
    for _ in range(1000):
        manager.method()
    elapsed = time.time() - start
    
    assert elapsed < 1.0  # 1000次操作应在1秒内完成
```

**状态**：⏳ 待实现

---

## 5. Mock 策略

### 需要 Mock 的组件

| 组件 | Mock 方式 | 原因 |
|------|-----------|------|
| 外部 API | `@patch('requests.post')` | 避免真实网络调用，加速测试 |
| 数据库 | Mock 对象 | 隔离数据库依赖 |
| 文件 I/O | `@patch('builtins.open')` | 避免实际文件操作 |
| 时间函数 | `@patch('time.time')` | 控制时间相关逻辑 |

### Mock Fixture 示例

```python
@pytest.fixture
def mock_external_service():
    """Mock 外部服务"""
    with patch('services.external.ExternalService') as mock:
        mock_instance = Mock()
        mock_instance.call_api.return_value = {'status': 'success'}
        mock.return_value = mock_instance
        yield mock_instance

@pytest.fixture
def mock_database():
    """Mock 数据库连接"""
    with patch('database.connection.get_connection') as mock:
        mock_conn = Mock()
        mock_conn.execute.return_value = []
        mock.return_value = mock_conn
        yield mock_conn
```

---

## 6. 测试覆盖率

### 覆盖率目标

- **核心业务逻辑**：≥ 90%
- **工具函数**：≥ 85%
- **异常处理**：≥ 80%
- **总体目标**：≥ 85%

### 当前覆盖率

| 模块 | 行覆盖率 | 分支覆盖率 | 目标 | 状态 |
|------|----------|-----------|------|------|
| module1.py | 0% | 0% | 90% | ⏳ 待测试 |
| module2.py | 0% | 0% | 85% | ⏳ 待测试 |
| **总计** | **0%** | **0%** | **85%** | ⏳ 待测试 |

### 运行测试命令

```bash
# 运行所有单元测试
pytest test/unit/services/[feature]/ -v

# 查看测试覆盖率
pytest test/unit/services/[feature]/ --cov=src/code/agent/services/[feature] --cov-report=html

# 运行特定测试类
pytest test/unit/services/[feature]/test_module.py::TestClassName -v
```

---

## 7. 测试数据

### 正常测试数据

```python
VALID_TEST_DATA = {
    "case1": {
        "input": {"param1": "value1", "param2": 123},
        "expected": {"status": "success", "result": "..."}
    },
    "case2": {
        "input": {"param1": "value2", "param2": 456},
        "expected": {"status": "success", "result": "..."}
    },
}
```

### 异常测试数据

```python
INVALID_TEST_DATA = {
    "null_case": {
        "input": {"param1": None},
        "expected_error": InvalidRequestError
    },
    "empty_case": {
        "input": {"param1": ""},
        "expected_error": InvalidRequestError
    },
    "type_error_case": {
        "input": {"param1": 123},  # 应该是字符串
        "expected_error": TypeError
    },
}
```

---

## 8. 已知问题

测试过程中发现的问题和待办事项：

- [ ] **问题1**：[描述]
  - 严重程度：高/中/低
  - 发现时间：[YYYY-MM-DD]
  - 影响范围：[描述]
  - 责任人：[姓名]
  - 状态：待修复

- [x] **问题2**：[描述]（已修复）
  - 修复时间：[YYYY-MM-DD]
  - 修复方案：[简要说明]

### 待补充的测试用例

- [ ] 场景1：[描述]
- [ ] 场景2：[描述]

---

**测试负责人**：[姓名]  
**创建时间**：[YYYY-MM-DD]  
**最后更新**：[YYYY-MM-DD]  
**测试状态**：⏳ 待开始 / 🔄 测试中 / ✅ 测试完成
