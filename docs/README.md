# 项目文档中心

本目录包含项目所有功能的设计、开发和测试文档。

## 📁 目录结构

```
docs/
├── README.md                    # 本文件 - 文档使用指南
├── .templates/                  # 文档模板
│   ├── design.md               # 设计文档模板
│   ├── development.md          # 开发计划模板
│   └── cases.md                # 测试用例模板
│
└── [feature-name]/             # 每个功能的文档目录
    ├── design.md               # 设计文档
    ├── development.md          # 开发计划
    └── cases.md                # 测试用例
```

---

## 🎯 三文档体系

每个功能包含三个核心文档：

### 1️⃣ design.md - 设计文档

**创建阶段**：INNOVATE（创新阶段）

**用途**：记录功能的设计思路和技术方案

**包含内容**：
- 功能概述和背景
- 架构设计（组件关系、数据流）
- 数据模型和接口设计
- 技术决策和权衡
- 依赖关系
- 风险和限制
- 未来扩展方向

---

### 2️⃣ development.md - 开发计划

**创建阶段**：PLAN（规划阶段）

**用途**：分解任务、跟踪进度、管理风险

**包含内容**：
- 任务分解（按阶段组织）
- 实施清单（原子操作列表）
- 开发进度表
- 技术债务记录
- 里程碑跟踪
- 风险管理
- 变更记录

---

### 3️⃣ cases.md - 测试文档

**创建阶段**：PLAN（规划阶段）

**用途**：定义测试用例和验收标准

**包含内容**：
- 测试范围和环境
- 单元测试用例（正常、异常、边界）
- 集成测试用例
- 并发和性能测试
- Mock 策略
- 测试覆盖率目标
- 已知问题和待办

---

## 🚀 使用 RIPER-5 流程开发新功能

### 完整流程

```
[MODE: RESEARCH]   → 分析代码、理解需求
                   → 记录在任务文件的"分析"部分

[MODE: INNOVATE]   → 探索方案、设计架构
                   → 创建 docs/[feature]/design.md

[MODE: PLAN]       → 制定计划、分解任务
                   → 创建 docs/[feature]/development.md
                   → 创建 docs/[feature]/cases.md

[MODE: EXECUTE]    → 按计划实施、更新进度
                   → 更新 development.md 的任务状态

[MODE: REVIEW]     → 验证实施、评审文档
                   → 确认文档与代码一致
```

### 启动新功能开发

1. **进入 RESEARCH 模式**：
   ```
   用户：ENTER RESEARCH MODE
        我要开发 [功能描述]
   ```

2. **AI 会自动**：
   - 分析相关代码
   - 创建任务文件 `.tasks/YYYY-MM-DD_n_[task-name].md`
   - 询问澄清问题

3. **进入 INNOVATE 模式**：
   ```
   用户：ENTER INNOVATE MODE
   ```

4. **AI 会创建**：
   - `docs/[feature]/design.md` 设计文档
   - 在任务文件中记录设计摘要

5. **进入 PLAN 模式**：
   ```
   用户：ENTER PLAN MODE
   ```

6. **AI 会创建**：
   - `docs/[feature]/development.md` 开发计划
   - `docs/[feature]/cases.md` 测试用例
   - 在任务文件中记录实施清单

7. **批准并执行**：
   ```
   用户：ENTER EXECUTE MODE
   ```

8. **完成后评审**：
   ```
   用户：ENTER REVIEW MODE
   ```

---

## 📖 模板使用

### 获取模板

模板位置：`docs/.templates/`

```bash
# 查看可用模板
ls docs/.templates/

# 输出：
# design.md        - 设计文档模板
# development.md   - 开发计划模板
# cases.md         - 测试文档模板
```

### 手动创建文档（如需要）

```bash
# 创建功能文档目录
mkdir -p docs/your-feature

# 复制模板
cp docs/.templates/design.md docs/your-feature/design.md
cp docs/.templates/development.md docs/your-feature/development.md
cp docs/.templates/cases.md docs/your-feature/cases.md

# 编辑文档
# 将 [功能名称] 替换为实际功能名
```

---

## 💡 最佳实践

### ✅ 推荐做法

1. **设计先行**
   - 在 INNOVATE 阶段充分讨论设计方案
   - 评审设计文档后再进入 PLAN 阶段

2. **小步快跑**
   - 将大功能拆分为小任务
   - 每个任务控制在 2-4 小时内完成

3. **持续更新**
   - EXECUTE 阶段完成任务时更新 development.md
   - 发现新问题时更新 cases.md

4. **文档同步**
   - 代码变更时同步更新设计文档
   - 重要决策记录在文档中

### ❌ 避免做法

1. **跳过文档创建**
   - 不要直接跳到 EXECUTE 阶段
   - 文档是理清思路的过程

2. **文档与代码脱节**
   - 避免"先写代码后补文档"
   - 避免文档更新滞后

3. **文档过于简单或冗长**
   - 简单：缺乏关键信息，后续维护困难
   - 冗长：维护成本高，难以阅读

---

## 📋 Code Review 检查清单

提交 PR 前，确认：

### 文档检查
- [ ] `docs/[feature]/design.md` 存在且内容完整
- [ ] `docs/[feature]/development.md` 所有任务已完成
- [ ] `docs/[feature]/cases.md` 测试用例已实现
- [ ] 文档中的技术方案与代码实现一致
- [ ] 变更记录已更新

### 代码检查
- [ ] 遵循 Python 编码规范
- [ ] 所有函数有类型注解
- [ ] 异常处理恰当
- [ ] 日志记录合理

### 测试检查
- [ ] 所有测试用例已实现并通过
- [ ] 测试覆盖率达标（≥ 85%）
- [ ] 包含异常场景测试
- [ ] Mock 使用恰当

---

## 🔍 查找现有文档

```bash
# 查找所有设计文档
find docs -name "design.md"

# 查找所有开发计划
find docs -name "development.md"

# 查找所有测试文档
find docs -name "cases.md"

# 查看特定功能的文档
ls -lh docs/[feature-name]/
```

---

## 📚 相关规范

- **RIPER-5 工作模式**：`.cursor/rules/riper5.mdc`
  - 定义 5 个工作模式
  - 任务文件模板
  - 文档创建流程

- **Python 编码规范**：`.cursor/rules/python-coding-standards.mdc`
  - 类型注解、命名约定
  - 错误处理、测试模式
  - 代码质量标准

---

## ❓ 常见问题

### Q1: 什么时候创建文档？

**A**: 
- **design.md**：INNOVATE 阶段（编码前）
- **development.md + cases.md**：PLAN 阶段（编码前）

### Q2: 小功能也需要三个文档吗？

**A**: 根据复杂度决定：
- 简单工具函数：只需代码文档字符串
- 独立类或模块：至少需要 design.md
- 完整服务或子系统：需要完整三个文档

### Q3: AI 会自动创建文档吗？

**A**: 是的！当您使用 RIPER-5 模式时：
- INNOVATE 阶段会自动创建 design.md
- PLAN 阶段会自动创建 development.md 和 cases.md

### Q4: 如何保持文档不过期？

**A**: 
- 在 Code Review 中检查文档更新
- 重大变更时在 development.md 的变更记录中记录
- REVIEW 阶段验证文档与代码一致性

### Q5: 文档应该多详细？

**A**: 以"三个月后自己或新同事能看懂"为标准。重点是：
- **设计文档**：为什么这样设计（而不是做了什么）
- **开发文档**：任务划分和依赖关系
- **测试文档**：主要测试场景和验收标准

---

## 🎓 示例学习

建议按以下顺序学习：

1. **阅读本文档**（10 分钟）
2. **查看模板**：`docs/.templates/` 目录（15 分钟）
3. **实践**：用 RIPER-5 模式开发一个小功能（1-2 小时）

---

**维护人**：开发团队  
**创建时间**：2026-02-24  
**最后更新**：2026-02-24
