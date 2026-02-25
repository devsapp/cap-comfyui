# 工作空间快照管理 测试用例

> 本文档在 PLAN 阶段创建 | 示例文档供参考

## 1. 测试概述

### 测试范围
- **功能范围**：工作空间快照的加载、保存和选择功能
- **测试类型**：
  - ✅ 单元测试
  - ✅ 集成测试
  - ⬜ 端到端测试（由上层服务负责）
  - ⬜ 性能测试（后续补充）

### 测试环境
- **Python 版本**：3.9+
- **测试框架**：pytest + unittest.mock
- **依赖服务**：无外部服务依赖，仅需文件系统
- **测试数据**：Mock 数据，避免真实文件操作

---

## 2. 单元测试用例

### 2.1 SnapshotManager.load()

#### 测试用例 1.1：正常流程 - 加载指定快照

**测试目标**：验证加载指定名称的快照

**前置条件**：
- 快照目录存在
- 快照文件完整

**测试步骤**：
1. 创建 SnapshotManager 实例
2. Mock 快照目录和 Loader
3. 调用 load("dev-20260115-120000")
4. 验证返回结果和状态更新

**预期结果**：
- 返回字典包含快照名称
- cur_snapshot_name 被正确设置
- Loader 被正确调用

**实现代码**：

```python
def test_load_specified_snapshot_success(self, snapshot_manager):
    """测试用例 1.1: 加载指定快照成功"""
    # Given
    snapshot_name = "dev-20260115-120000"
    
    with patch('os.path.exists', return_value=True):
        with patch('services.workspace.snapshot_loader.ComfyUIDevSnapshotLoader') as mock_loader:
            mock_loader.return_value.load.return_value = {"timing": {"load": 1000}}
            
            # When
            result = snapshot_manager.load(snapshot_name)
            
            # Then
            assert result["snapshot"] == snapshot_name
            assert snapshot_manager.cur_snapshot_name == snapshot_name
```

**状态**：✅ 已通过

---

#### 测试用例 1.2：异常处理 - 快照不存在

**测试目标**：验证加载不存在快照时抛出 RuntimeError

**前置条件**：
- 快照目录不存在

**测试步骤**：
1. Mock os.path.exists 返回 False
2. 调用 load("non-existent")
3. 捕获并验证异常

**预期结果**：
- 抛出 RuntimeError
- 错误消息包含快照名称和 "not found"

**实现代码**：

```python
def test_load_nonexistent_snapshot_error(self, snapshot_manager):
    """测试用例 1.2: 快照不存在抛出异常"""
    # Given
    snapshot_name = "non-existent-snapshot"
    
    # When & Then
    with patch('os.path.exists', return_value=False):
        with pytest.raises(RuntimeError) as exc_info:
            snapshot_manager.load(snapshot_name)
        
        assert snapshot_name in str(exc_info.value)
        assert "not found" in str(exc_info.value).lower()
```

**状态**：✅ 已通过

---

#### 测试用例 1.3：边界值测试 - latest-dev 自动选择

**测试目标**：验证使用 "latest-dev" 自动选择最新开发快照

**前置条件**：
- 存在多个开发快照

**测试步骤**：
1. Mock _select_latest_snapshot 返回最新快照
2. 调用 load("latest-dev")
3. 验证调用了正确的选择方法

**预期结果**：
- 调用 _select_latest_snapshot("dev")
- 加载返回的最新快照

**实现代码**：

```python
def test_load_latest_dev_snapshot(self, snapshot_manager):
    """测试用例 1.3: 使用 latest-dev 加载最新快照"""
    # Given
    latest_snapshot = "dev-20260120-150000"
    
    with patch.object(snapshot_manager, '_select_latest_snapshot', return_value=latest_snapshot):
        with patch('os.path.exists', return_value=True):
            with patch('services.workspace.snapshot_loader.ComfyUIDevSnapshotLoader') as mock_loader:
                mock_loader.return_value.load.return_value = {}
                
                # When
                result = snapshot_manager.load("latest-dev")
                
                # Then
                assert result["snapshot"] == latest_snapshot
                snapshot_manager._select_latest_snapshot.assert_called_once_with("dev")
```

**状态**：✅ 已通过

---

#### 测试用例 1.4：边界值测试 - 幂等性

**测试目标**：验证重复加载已加载的快照会跳过

**测试步骤**：
1. 设置 cur_snapshot_name
2. 再次加载同一快照
3. 验证直接返回，不执行实际加载

**预期结果**：
- 直接返回快照名称
- 不调用 Loader

**实现代码**：

```python
def test_load_same_snapshot_twice_idempotent(self, snapshot_manager):
    """测试用例 1.4: 重复加载同一快照（幂等性）"""
    # Given
    snapshot_name = "dev-20260115"
    snapshot_manager.cur_snapshot_name = snapshot_name
    
    # When
    result = snapshot_manager.load(snapshot_name)
    
    # Then
    assert result["snapshot"] == snapshot_name
```

**状态**：✅ 已通过

---

### 2.2 SnapshotManager.save()

#### 测试用例 2.1：正常流程 - 自动生成名称

**测试目标**：验证保存快照时自动生成时间戳名称

**实现代码**：

```python
def test_save_snapshot_auto_name(self, snapshot_manager):
    """测试用例 2.1: 保存快照自动生成名称"""
    # Given
    snapshot_type = "dev"
    
    with patch('services.workspace.snapshot_saver.SnapshotSaver') as mock_saver:
        mock_saver.return_value.save.return_value = {"snapshot": "dev-20260124-120000"}
        
        # When
        result = snapshot_manager.save(snapshot_type)
        
        # Then
        assert "snapshot" in result
        assert result["snapshot"].startswith("dev-")
```

**状态**：✅ 已通过

---

#### 测试用例 2.2：正常流程 - 指定名称

**测试目标**：验证使用指定名称保存快照

**实现代码**：

```python
def test_save_snapshot_custom_name(self, snapshot_manager):
    """测试用例 2.2: 使用自定义名称保存快照"""
    # Given
    snapshot_type = "prod"
    custom_name = "pre-stop-backup"
    
    with patch('services.workspace.snapshot_saver.SnapshotSaver') as mock_saver:
        mock_saver.return_value.save.return_value = {"snapshot": custom_name}
        
        # When
        result = snapshot_manager.save(snapshot_type, snapshot_name=custom_name)
        
        # Then
        assert result["snapshot"] == custom_name
```

**状态**：✅ 已通过

---

### 2.3 SnapshotManager._select_latest_snapshot()

#### 测试用例 3.1：正常流程 - 多个候选

**测试目标**：验证从多个快照中选择最新的

**实现代码**：

```python
def test_select_latest_snapshot_multiple(self, snapshot_manager):
    """测试用例 3.1: 从多个快照中选择时间最新的"""
    # Given
    snapshots = [
        "dev-20260120-100000",
        "dev-20260122-100000",  # 最新
        "dev-20260119-100000",
        "prod-20260121-100000", # 不同类型，应被过滤
    ]
    
    with patch('os.listdir', return_value=snapshots):
        # When
        result = snapshot_manager._select_latest_snapshot("dev")
        
        # Then
        assert result == "dev-20260122-100000"
```

**状态**：✅ 已通过

---

#### 测试用例 3.2：边界值测试 - 无匹配快照

**测试目标**：验证没有匹配类型的快照时返回 None

**实现代码**：

```python
def test_select_latest_snapshot_none_found(self, snapshot_manager):
    """测试用例 3.2: 无匹配快照返回 None"""
    # Given
    snapshots = ["prod-20260120-100000"]  # 只有 prod 类型
    
    with patch('os.listdir', return_value=snapshots):
        # When
        result = snapshot_manager._select_latest_snapshot("dev")
        
        # Then
        assert result is None
```

**状态**：✅ 已通过

---

## 3. 集成测试用例

### 3.1 完整流程测试

#### 测试用例 4.1：端到端 - 保存并加载

**测试目标**：验证保存后能正确加载的完整流程

**测试场景**：
用户保存当前工作空间为快照，然后加载该快照恢复状态

**测试步骤**：
1. 调用 save("dev") 保存快照
2. 获取返回的快照名称
3. 调用 load(snapshot_name) 加载
4. 验证状态一致

**预期结果**：
- 保存成功返回快照名称
- 加载成功恢复状态
- cur_snapshot_name 正确更新

**状态**：✅ 已通过

---

## 4. 特殊场景测试

### 4.1 并发测试

#### 测试用例 5.1：并发加载不同快照

**测试目标**：验证多线程同时加载不同快照的安全性

**实现代码**：

```python
def test_concurrent_load_different_snapshots(self):
    """测试用例 5.1: 并发加载不同快照"""
    import threading
    
    results = []
    def load_snapshot(name):
        result = snapshot_manager.load(name)
        results.append(result)
    
    threads = [
        threading.Thread(target=load_snapshot, args=(f"dev-snapshot-{i}",))
        for i in range(5)
    ]
    
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    # 验证所有加载都完成（注：当前实现可能有竞态条件）
    assert len(results) == 5
```

**状态**：⚠️ 已通过（标记为技术债务：需要添加并发保护）

---

## 5. Mock 策略

### 需要 Mock 的组件

| 组件 | Mock 方式 | 原因 |
|------|-----------|------|
| 文件系统 | `@patch('os.path.exists')` | 避免实际文件操作，加速测试 |
| 目录列表 | `@patch('os.listdir')` | 控制快照列表，测试选择逻辑 |
| SnapshotLoader | `@patch('services.workspace.snapshot_loader.ComfyUIDevSnapshotLoader')` | 隔离加载器实现 |
| SnapshotSaver | `@patch('services.workspace.snapshot_saver.SnapshotSaver')` | 隔离保存器实现 |

### Mock Fixture

```python
@pytest.fixture
def snapshot_manager():
    """创建测试用的 SnapshotManager 实例"""
    manager = SnapshotManager()
    yield manager

@pytest.fixture
def mock_snapshot_dir():
    """Mock 快照目录存在"""
    with patch('os.path.exists', return_value=True):
        with patch('os.listdir', return_value=["dev-20260115", "prod-20260116"]):
            yield
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
| snapshot_manager.py | 88% | 85% | 90% | ⚠️ 接近目标 |
| snapshot_loader.py | 92% | 90% | 90% | ✅ 达标 |
| snapshot_saver.py | 91% | 88% | 90% | ✅ 达标 |
| **总计** | **90%** | **88%** | **85%** | ✅ 达标 |

### 未覆盖代码

- `snapshot_manager.py:156-158` - 磁盘满异常分支（难以模拟）
- `snapshot_manager.py:201` - 日志记录代码（非关键路径）

### 运行测试命令

```bash
# 运行快照管理器测试
pytest test/unit/services/workspace/snapshot_manager_test.py -v

# 查看覆盖率
pytest test/unit/services/workspace/ --cov=src/code/agent/services/workspace --cov-report=html

# 运行特定测试
pytest test/unit/services/workspace/snapshot_manager_test.py::TestSnapshotManager::test_load_specified_snapshot_success -v
```

---

## 7. 测试数据

### 正常测试数据

```python
VALID_SNAPSHOTS = {
    "dev": [
        "dev-20260115-120000",
        "dev-20260116-120000",
        "dev-20260120-150000",
    ],
    "prod": [
        "prod-20260115-090000",
        "prod-20260116-090000",
    ],
}
```

### 异常测试数据

```python
INVALID_INPUTS = {
    "null": None,
    "empty": "",
    "invalid_path": "../../../etc/passwd",  # 路径遍历
    "nonexistent": "snapshot-does-not-exist",
}
```

---

## 8. 已知问题

### 测试中发现的问题

- [x] **问题1：大快照加载超时**
  - 严重程度：中
  - 发现时间：2026-01-18
  - 影响范围：超过 5GB 的快照加载时间超过 30 秒
  - 责任人：张三
  - 状态：✅ 已修复（添加了超时配置和进度显示）
  - 修复时间：2026-01-19

- [x] **问题2：并发保存导致文件损坏**
  - 严重程度：高
  - 发现时间：2026-01-21
  - 影响范围：多个进程同时保存可能导致文件不完整
  - 责任人：李四
  - 状态：✅ 已修复（添加了文件锁机制）
  - 修复时间：2026-01-22

- [x] **问题3：重复加载浪费性能**
  - 严重程度：低
  - 发现时间：2026-01-27
  - 影响范围：重复加载已加载快照会执行冗余操作
  - 责任人：张三
  - 状态：✅ 已修复（添加了幂等性检查）
  - 修复时间：2026-01-27

### 待补充的测试用例

- [ ] **场景1：磁盘空间不足**
  - 描述：保存快照时磁盘空间不足的处理
  - 优先级：低
  - 原因：难以模拟，实际场景罕见

- [ ] **场景2：快照损坏恢复**
  - 描述：加载损坏快照时的降级处理
  - 优先级：中
  - 原因：需要实现快照完整性校验

- [ ] **场景3：性能压测**
  - 描述：超大快照（>10GB）的加载性能
  - 优先级：低
  - 原因：需要准备大规模测试数据

---

**测试负责人**：赵六  
**创建时间**：2026-01-15  
**最后更新**：2026-01-30  
**测试状态**：✅ 测试完成（覆盖率达标 90%）
