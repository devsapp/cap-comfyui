# 背景
文件名：2026-02-25_1_github-ci-coverage.md
创建于：2026-02-25_17:00:00
创建者：cici
主分支：cap
任务分支：task/github-ci-coverage_2026-02-25_1
功能名称：github-ci-coverage
Yolo模式：Off

# 任务描述
setup 一个 github ci，要求新增代码的测试覆盖率高于 95%

具体要求：
1. 测试执行目录：src/code/agent
2. 覆盖率范围：仅 src/code/agent 目录
3. 基准分支：cap
4. CI 触发条件：每次 push 都运行
5. 新增代码覆盖率阈值：≥ 95%

# 项目概览
- Python 版本: 3.10.16
- 测试框架: pytest + coverage.py v7.13.4
- 当前整体覆盖率: 77%
- 测试文件: 18 个单元测试文件位于 test/unit/ 目录
- 项目类型: Flask 应用，包含 WebSocket、进程管理、任务管理等功能
- 依赖管理: requirements.txt (需要新增测试依赖文件)

# 文档结构
本任务相关的文档：
- 设计文档：`docs/github-ci-coverage/design.md` (INNOVATE 阶段创建)
- 开发文档：`docs/github-ci-coverage/development.md` (PLAN 阶段创建)
- 测试文档：`docs/github-ci-coverage/cases.md` (PLAN 阶段创建)

⚠️ 警告：永远不要修改此部分 ⚠️
# RIPER-5 协议规则摘要

## 模式流程
RESEARCH → INNOVATE → PLAN → EXECUTE → REVIEW

## 核心原则
- 每个响应必须声明当前模式：[MODE: MODE_NAME]
- 未经明确信号不得转换模式
- EXECUTE 模式必须 100% 遵循计划
- REVIEW 模式必须标记任何偏差
- 禁止在未经请求时实施更改

## 模式职责
- RESEARCH: 只读、分析、提问
- INNOVATE: 设计方案、评估优劣、创建 design.md
- PLAN: 详细规划、创建 development.md 和 cases.md
- EXECUTE: 严格按计划实施、更新任务进度
- REVIEW: 验证符合度、准备提交
⚠️ 警告：永远不要修改此部分 ⚠️

# 分析 (RESEARCH 阶段)
## 代码结构分析
- 测试代码位于: src/code/agent/test/unit/
- 18 个测试文件覆盖 utils、services、gateway 等模块
- 使用 pytest fixture 和 mock 进行单元测试
- 已有 htmlcov 目录，说明本地已运行过覆盖率测试

## 现有配置缺失
- 无 .github/workflows/ CI 配置
- 无 pytest.ini 或 pyproject.toml
- 无 .coveragerc 覆盖率配置
- requirements.txt 未包含测试依赖

## 技术约束
- Python 3.10.16
- 使用 pytest + coverage.py v7.13.4
- 需要支持差异覆盖率计算（diff-cover）
- 工作目录: src/code/agent
- 基准分支: cap

## 关键需求
- **差异覆盖率**: 不是检查整体覆盖率，而是仅检查新增/修改代码的覆盖率
- **失败条件**: 当新增代码覆盖率 < 95% 时，CI 应该失败
- **触发频率**: 每次 push 都运行（不仅限于 PR）

# 提议的解决方案 (INNOVATE 阶段)

## 推荐方案：diff-cover 工具方案

采用 **diff-cover** 专业工具实现差异覆盖率检查，这是专门为"仅检查新增代码覆盖率"设计的工具。

### 技术架构
- **测试框架**: pytest + pytest-cov
- **覆盖率工具**: coverage.py（生成 XML 报告）
- **差异分析**: diff-cover（对比 cap 分支）
- **CI 平台**: GitHub Actions

### 核心工作流
1. Checkout 代码（完整 git 历史）
2. 设置 Python 3.10 环境
3. 安装依赖（requirements.txt + requirements-dev.txt）
4. 运行 pytest 生成覆盖率数据（XML + HTML + Terminal）
5. 运行 diff-cover 对比 cap 分支，阈值 95%
6. 失败时 CI 返回非零退出码

### 需要创建的文件
- `.github/workflows/test-coverage.yml` - GitHub Actions 配置
- `src/code/agent/requirements-dev.txt` - 测试依赖
- `src/code/agent/pytest.ini` - pytest 配置
- `src/code/agent/.coveragerc` - 覆盖率配置
- 更新 `.gitignore` - 排除覆盖率文件

### 方案优势
✅ 专业工具，专门用于差异覆盖率  
✅ 与现有 pytest + coverage.py 无缝集成  
✅ 开源免费，本地运行，无隐私问题  
✅ 成熟稳定（v9.2.4，生产级）  
✅ 配置简单，维护成本低  
✅ 支持本地模拟 CI 流程  

详细设计见：`docs/github-ci-coverage/design.md`

# 实施计划摘要 (PLAN 阶段)

## 开发计划
分为 7 个阶段，21 个具体步骤：

**阶段 1: 测试依赖配置文件创建（3 个文件）**
- requirements-dev.txt：pytest、pytest-cov、diff-cover
- pytest.ini：测试路径、命名模式、默认选项
- .coveragerc：覆盖率源、排除规则、XML 输出

**阶段 2: GitHub Actions 工作流创建（2 个步骤）**
- 创建 .github/workflows/ 目录
- 创建 test-coverage.yml 工作流（10 个 CI 步骤，含 GitHub Pages 部署）

**阶段 3: gitignore 配置更新（1 个修改）**
- 在 .gitignore 追加 6 行覆盖率文件排除规则（含 gh-pages-deploy/）

**阶段 4: GitHub Pages 配置（1 个步骤）**
- 在 GitHub 仓库 Settings > Pages 启用，配置 gh-pages 分支

**阶段 5: 本地验证测试（3 个步骤）**
- 安装测试依赖
- 运行 pytest 生成覆盖率
- 运行 diff-cover 验证工具

**阶段 6: 提交与 CI 验证（5 个步骤）**
- 暂存、提交、推送代码
- 查看 GitHub Actions 运行状态
- 确认 CI 成功

**阶段 7: GitHub Pages 部署验证（6 个步骤）**
- 合并到 cap 分支
- 验证 Pages 部署成功
- 访问并测试覆盖率报告页面

详细内容见：`docs/github-ci-coverage/development.md`

## 测试计划
定义 20 个测试用例，覆盖：
- 配置文件验证（2 个）
- 本地集成测试（3 个）
- CI 集成测试（5 个，含 GitHub Pages 部署和自动更新验证）
- 边界场景测试（5 个）
- 兼容性、性能、安全测试（各 1-2 个）

详细内容见：`docs/github-ci-coverage/cases.md`

# 当前执行步骤
"设计技术方案"

# 任务进度 (EXECUTE 阶段)
[待记录]

# 最终审查 (REVIEW 阶段)
[待完成]
