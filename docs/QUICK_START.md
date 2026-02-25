# 快速入门指南

本指南帮助您快速掌握 RIPER-5 + 三文档体系的开发流程。

## ⚡ 5 分钟快速上手

### 场景：我要开发一个新功能

**第 1 步：启动研究模式**

```
你对 AI 说：ENTER RESEARCH MODE
           我要开发一个任务优先级管理功能
```

AI 会：
- 分析相关代码
- 创建任务文件 `.tasks/2026-02-24_1_task-priority.md`
- 询问需求细节

---

**第 2 步：进入创新模式，生成设计**

```
你说：ENTER INNOVATE MODE
```

AI 会：
- 探索多种设计方案
- 讨论技术选型
- **自动创建** `docs/task-priority/design.md`

---

**第 3 步：进入规划模式，制定计划**

```
你说：ENTER PLAN MODE
```

AI 会：
- 分解开发任务
- **自动创建** `docs/task-priority/development.md`
- **自动创建** `docs/task-priority/cases.md`
- 生成实施清单

---

**第 4 步：审批并执行**

```
你说：ENTER EXECUTE MODE
```

AI 会：
- 严格按照 development.md 中的实施清单执行
- 每完成一项，更新任务进度
- 自动更新 development.md 的进度表

---

**第 5 步：完成后评审**

```
你说：ENTER REVIEW MODE
```

AI 会：
- 验证代码与计划的一致性
- 检查文档是否同步
- 生成最终评审报告
- 准备 Git 提交

---

## 📚 文档在哪里？

完成后，您会得到：

```
.tasks/
└── 2026-02-24_1_task-priority.md    # 任务跟踪文件

docs/
└── task-priority/                    # 功能文档目录
    ├── design.md                     # 设计文档
    ├── development.md                # 开发计划
    └── cases.md                      # 测试用例

src/code/agent/services/
└── task-priority/                    # 代码实现
    ├── __init__.py
    ├── priority_manager.py
    └── ...
```

---

## 🎓 关键命令速查

### 模式切换命令

```bash
ENTER RESEARCH MODE    # 研究和分析
ENTER INNOVATE MODE    # 设计和创新
ENTER PLAN MODE        # 详细规划
ENTER EXECUTE MODE     # 执行实施
ENTER REVIEW MODE      # 审查验证
```

### 文档查看命令

```bash
# 查看所有功能的设计文档
find docs -name "design.md"

# 查看特定功能的所有文档
ls docs/[feature-name]/

# 查看任务文件
ls .tasks/
```

### Git 工作流

```bash
# AI 在 RESEARCH 阶段会自动创建分支
# 分支名格式：task/[task-identifier]_[date]_[number]

# 查看当前分支
git branch

# 查看任务文件（排除在提交之外）
cat .tasks/[task-file].md

# REVIEW 阶段 AI 会自动提交代码（不包含 .tasks/）
```

---

## 💡 使用技巧

### 技巧 1：让 AI 主导流程

不需要记住所有细节，只需：
1. 说"ENTER RESEARCH MODE"
2. 描述你的需求
3. 跟着 AI 的引导，逐个模式推进

### 技巧 2：随时查看文档

在任何阶段，你都可以：

```
你说：查看当前的设计文档
     或
     development.md 的进度如何？
```

### 技巧 3：灵活调整

发现问题时可以回退：

```
你说：回到 PLAN MODE，我需要调整设计
```

### 技巧 4：并行开发

可以同时进行多个功能开发：
- 每个功能有独立的任务文件
- 每个功能有独立的文档目录
- 每个功能有独立的 Git 分支

---

## 🎯 第一次尝试

### 实践项目建议

选择一个简单功能练习流程，例如：

```
功能：添加配置验证器
复杂度：中等
预计时间：2-3 小时
```

### 操作步骤

1. 打开 Cursor
2. 对 AI 说："ENTER RESEARCH MODE，我要开发一个配置验证器功能"
3. 回答 AI 的问题
4. 跟随 AI 的引导完成 5 个模式
5. 查看生成的文档：`docs/config-validator/`

---

## 📊 各模式时间分配参考

| 模式 | 典型耗时 | 产出 |
|------|----------|------|
| RESEARCH | 15-30 分钟 | 需求分析、代码调研 |
| INNOVATE | 20-40 分钟 | design.md |
| PLAN | 30-60 分钟 | development.md + cases.md |
| EXECUTE | 根据任务量 | 代码实现 + 测试 |
| REVIEW | 10-20 分钟 | 验证和评审 |

---

## 🆘 遇到问题？

### AI 没有创建文档？

检查：
- 是否正确进入了相应模式？
- 是否在对话中明确了功能名称？

### 文档内容不满意？

可以：
- 要求 AI 重新生成："请重新生成 design.md，增加架构图"
- 手动编辑文档
- 在 REVIEW 阶段提出修改意见

### 不知道进展到哪一步了？

查看任务文件：

```bash
# 查看当前任务
cat .tasks/[latest-task-file].md

# 或者问 AI
"当前进度如何？"
```

---

## 🔗 相关文档

- [完整文档说明](README.md)
- [RIPER-5 规则](.cursor/rules/riper5.mdc)
- [Python 编码规范](.cursor/rules/python-coding-standards.mdc)

---

**现在就开始您的第一个 RIPER-5 功能开发吧！** 🚀
