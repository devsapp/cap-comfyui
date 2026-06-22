# 执行历史持久化设计

**日期**：2026-05-23  
**适用版本**：ComfyUI v0.3.77 / v0.16.4  
**模块**：`services/gateway/task/history_manager.py`

---

## 背景

在 CPU+GPU 双函数架构中，用户通过 CPU 函数（gateway）提交 workflow，由 GPU 函数执行。CPU 函数的 Agent 通过轮询 GPU 异步调用结果获取执行状态和输出信息，存储在内存中的 `HistoryManager`。

**问题**：`HistoryManager` 是纯内存存储，CPU 函数实例重建（部署更新、弹性缩容、冷启动）后历史数据全部丢失，前端媒体资产面板显示为空。

此问题在 v0.3.77（`/api/history`）和 v0.16.4（`/api/jobs`）中均存在。

---

## 方案选型

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| JSON 文件 | 简单 | 每次全量重写、大文件加载慢 | 否 |
| SQLite on NAS | 增量写入、stdlib 无依赖、索引查询 | NFS 上多写者有风险 | **采用** |
| SQLite on 本地磁盘 | 性能最好 | 实例销毁后丢失，不满足需求 | 否 |
| GPU 函数 DB 共享 | 减少数据同步 | 多 GPU 实例并发写同一 DB 会损坏 | 否 |

**选择 SQLite on NAS 的理由**：CPU 函数每个项目只有一个实例（gateway），单写者场景下 NFS 上的 SQLite 完全可靠。

---

## 架构设计

```
┌──────────────────────────────────────────┐
│           CPU 函数 (Gateway)              │
│                                          │
│  ┌─────────────────────┐                 │
│  │   HistoryManager    │                 │
│  │  (内存 dict, 快速读) │                 │
│  └──────┬──────────────┘                 │
│         │ 任务完成 → 标记 dirty           │
│         │ 3s 去抖                         │
│         ▼                                │
│  ┌─────────────────────┐                 │
│  │  _flush_to_disk()   │                 │
│  │  增量 INSERT/DELETE  │                 │
│  └──────┬──────────────┘                 │
│         │                                │
└─────────┼────────────────────────────────┘
          ▼
   ${MNT_DIR}/output/.history.db  (NAS)
          ▲
          │ 启动时 SELECT ... LIMIT 2000
          │
┌─────────┼────────────────────────────────┐
│  ┌──────┴──────────────┐                 │
│  │  _load_from_disk()  │                 │
│  └─────────────────────┘                 │
│       新实例启动                          │
└──────────────────────────────────────────┘
```

---

## 数据模型

### SQLite 表结构

```sql
CREATE TABLE history (
    prompt_id  TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    outputs    TEXT,          -- JSON: 节点输出（图片文件名等）
    meta       TEXT,          -- JSON: 节点元数据
    status     TEXT,          -- JSON: 执行状态和消息
    create_time INTEGER DEFAULT 0  -- 毫秒时间戳
);

CREATE INDEX idx_user_id ON history(user_id);
CREATE INDEX idx_create_time ON history(create_time);
```

### 精简策略

只持久化展示所需的最小字段集，**丢弃完整的 workflow prompt 数据**：

| 字段 | 来源 | 用途 |
|------|------|------|
| `outputs` | `history_item["outputs"]` | 前端展示生成的图片 |
| `meta` | `history_item["meta"]` | 节点 display_node 映射 |
| `status` | `history_item["status"]` | 完成/失败状态、时间戳 |
| `user_id` | `history_item["user_id"]` | 多租户隔离 |
| `create_time` | `prompt[3]["create_time"]` | 排序 |

**不持久化**：`prompt[2]`（完整 workflow graph，几十 KB/条）、`prompt[4]`（outputs_to_execute）。

---

## 写入机制

### 增量写入（Dirty Tracking）

```python
self._dirty_prompt_ids: set   # 新完成的记录，需要 INSERT OR REPLACE
self._deleted_prompt_ids: set # 被删除的记录，需要 DELETE
```

- 任务完成（success/error）→ `_dirty_prompt_ids.add(prompt_id)`
- 删除/清空 → `_deleted_prompt_ids.add(prompt_id)`
- 3 秒去抖后批量刷盘

### 去抖（Debounce）

高频场景（如批量执行 workflow）下，多个任务短时间内完成。去抖合并写入避免频繁 I/O：

```python
def _schedule_flush(self):
    # 取消上一个 timer，重新计时 3s
    self._flush_timer = Timer(3, self._flush_to_disk)
```

### 原子性保证

- SQLite 自身的事务保证单次 flush 的原子性
- `_flush_to_disk` 先在内存锁下拷贝 dirty/deleted 集合并清空，再释放锁后写 DB
- DB 写入失败不影响内存数据，下次 flush 时会重新收集

---

## 加载机制

启动时加载最近 2000 条到内存：

```python
SELECT prompt_id, user_id, outputs, meta, status, create_time
FROM history ORDER BY create_time DESC LIMIT 2000
```

- DB 不限制总条目数，历史永久保留
- 内存中只保留最近 2000 条供 API 查询
- 更早的历史仍在 DB 中，后续可按需实现分页查询

---

## 降级策略

| 场景 | 行为 |
|------|------|
| NAS 未挂载 / 目录不存在 | `_init_db` 失败 → warning 日志，内存正常工作，无持久化 |
| DB 文件损坏 | `_load_from_disk` 失败 → warning，从空状态开始 |
| 单次 flush 失败 | warning 日志，dirty 集合已清空（丢失本批次），后续新完成的任务正常写入 |
| 旧版本部署（无 DB 文件） | 首次启动自动创建表，零配置 |

---

## 兼容性

| 场景 | 影响 |
|------|------|
| 旧版本 ComfyUI (v0.3.77) | 零影响。sqlite3 是 Python 标准库，DB 自动创建 |
| GPU 函数 | 启动时 load DB（读），不会写入（无任务完成事件走这条路径） |
| 多租户禁用时 | user_id 为 "default"，正常工作 |
| `jobs_handler` 读取磁盘记录 | 兼容：`create_time` 优先从 `prompt[3]` 读取，fallback 到顶层字段 |

---

## 文件清单

| 文件 | 改动 |
|------|------|
| `services/gateway/task/history_manager.py` | 新增 SQLite 持久化逻辑 |
| `services/gateway/handlers/jobs_handler.py` | 兼容从 DB 加载的精简记录格式 |
