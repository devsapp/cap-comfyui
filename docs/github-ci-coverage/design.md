# GitHub CI 覆盖率检查 - 设计文档

**创建日期**: 2026-02-25  
**作者**: cici  
**状态**: 设计中

---

## 一、需求概述

### 核心需求
设置 GitHub CI，确保每次代码提交时新增代码的测试覆盖率达到 95% 以上。

### 具体要求
- **测试范围**: src/code/agent 目录
- **触发条件**: 每次 push 到仓库
- **基准分支**: cap
- **覆盖率类型**: 差异覆盖率（Diff Coverage）
- **阈值**: 新增代码覆盖率 ≥ 95%

---

## 二、架构设计

### 2.1 技术方案对比

#### 方案 A: diff-cover 工具方案 ⭐ **推荐**

**核心思路**
使用专门的 diff-cover 工具，它能够：
- 分析 git diff 找出新增/修改的代码行
- 将这些行与 coverage.py 的报告对比
- 仅计算变更代码的覆盖率
- 当差异覆盖率低于阈值时返回非零退出码

**技术栈**
- pytest + pytest-cov：运行测试并生成覆盖率数据
- coverage.py：生成 XML 格式的覆盖率报告
- diff-cover：计算差异覆盖率

**工作流程**
```
1. Checkout 代码（包含完整 git 历史）
2. 设置 Python 3.10 环境
3. 安装依赖（包括 diff-cover）
4. 运行 pytest 生成覆盖率报告
5. 运行 diff-cover 对比 cap 分支
6. 如果差异覆盖率 < 95%，CI 失败
```

**优势**
- ✅ 专业工具，专门用于差异覆盖率分析
- ✅ 支持多种覆盖率报告格式（Cobertura XML、Clover、JaCoCo）
- ✅ 可以生成 HTML 报告供本地查看
- ✅ 明确的退出码，易于 CI 集成
- ✅ 活跃维护，最新版本 9.2.4（2025年3月）

**劣势**
- ❌ 需要额外安装一个工具
- ❌ 需要完整的 git 历史（fetch-depth: 0）

#### 方案 B: 纯 pytest-cov 方案

**核心思路**
使用 pytest-cov 的 `--cov-fail-under` 参数检查整体覆盖率。

**工作流程**
```
1. 运行 pytest --cov --cov-fail-under=95
2. 如果整体覆盖率 < 95%，CI 失败
```

**优势**
- ✅ 简单，无需额外工具
- ✅ 配置少

**劣势**
- ❌ **不符合需求**：检查的是整体覆盖率，不是新增代码覆盖率
- ❌ 当前整体覆盖率 77%，无法通过 95% 阈值
- ❌ 会阻止所有提交，直到整体覆盖率提升到 95%

#### 方案 C: coverage.py 比较 + 脚本方案

**核心思路**
手动编写脚本，对比两个分支的覆盖率数据。

**工作流程**
```
1. 切换到 cap 分支，运行测试，保存覆盖率数据
2. 切换回当前分支，运行测试，生成覆盖率数据
3. 自定义脚本比较两个覆盖率数据
4. 计算新增代码的覆盖率
5. 判断是否达到阈值
```

**优势**
- ✅ 完全自定义，灵活性高

**劣势**
- ❌ 需要手动编写和维护脚本
- ❌ 容易出错，逻辑复杂
- ❌ 难以处理边界情况（重命名、移动文件等）
- ❌ 开发和测试成本高

#### 方案 D: 第三方服务方案（Codecov / Coveralls）

**核心思路**
使用 Codecov 或 Coveralls 等第三方服务，它们提供差异覆盖率检查。

**工作流程**
```
1. 运行 pytest 生成覆盖率报告
2. 上传报告到 Codecov/Coveralls
3. 服务自动分析差异覆盖率
4. 在 PR 中显示覆盖率变化
```

**优势**
- ✅ 功能强大，UI 美观
- ✅ 支持多种语言和框架
- ✅ 提供历史趋势分析

**劣势**
- ❌ 需要外部服务账号和配置
- ❌ 可能涉及数据隐私问题
- ❌ 免费版有使用限制
- ❌ 依赖第三方服务可用性

---

### 2.2 推荐方案：方案 A（diff-cover）

基于以下原因，推荐使用 **方案 A**：

1. **完全符合需求**：diff-cover 专门用于计算差异覆盖率
2. **开源且自主可控**：无需依赖外部服务
3. **成熟稳定**：工具活跃维护，已是生产稳定版本
4. **易于集成**：与现有的 pytest + coverage.py 工具链无缝集成
5. **清晰的失败机制**：当覆盖率不达标时，明确返回非零退出码

---

## 三、详细设计

### 3.1 文件结构

需要创建/修改的文件：

```
cap-comfyui/
├── .github/
│   └── workflows/
│       └── test-coverage.yml          # GitHub Actions workflow
├── src/code/agent/
│   ├── requirements-dev.txt           # 测试依赖（新建）
│   ├── pytest.ini                     # pytest 配置（新建）
│   └── .coveragerc                    # coverage 配置（新建）
└── .gitignore                         # 更新，排除覆盖率文件
```

### 3.2 依赖管理

**requirements-dev.txt**
```
pytest>=8.0.0
pytest-cov>=4.1.0
diff-cover>=9.2.0
```

**说明**：
- pytest: 测试框架
- pytest-cov: pytest 的覆盖率插件
- diff-cover: 差异覆盖率计算工具

### 3.3 pytest 配置

**pytest.ini**
```ini
[pytest]
testpaths = test
python_files = *_test.py
python_classes = Test*
python_functions = test_*
addopts = 
    -v
    --strict-markers
    --tb=short
```

**配置说明**：
- `testpaths`: 测试文件搜索路径
- `python_files`: 测试文件命名模式（匹配现有的 *_test.py）
- `addopts`: 默认选项（详细输出、严格标记、短回溯）

### 3.4 覆盖率配置

**.coveragerc**
```ini
[run]
source = .
omit = 
    */test/*
    */tests/*
    */__pycache__/*
    */venv/*
    */.venv/*
    */htmlcov/*

[report]
precision = 2
show_missing = True
skip_covered = False

[html]
directory = htmlcov

[xml]
output = coverage.xml
```

**配置说明**：
- `source`: 覆盖率分析的源代码目录
- `omit`: 排除测试文件、虚拟环境等
- `precision`: 覆盖率精度（2 位小数）
- `output`: XML 报告输出路径（供 diff-cover 使用）

### 3.5 GitHub Actions Workflow

**.github/workflows/test-coverage.yml**

**核心步骤**：

1. **代码检出**
   ```yaml
   - uses: actions/checkout@v4
     with:
       fetch-depth: 0  # 获取完整 git 历史，diff-cover 需要
   ```

2. **环境设置**
   ```yaml
   - uses: actions/setup-python@v5
     with:
       python-version: '3.10'
   ```

3. **依赖安装**
   ```yaml
   - name: Install dependencies
     working-directory: src/code/agent
     run: |
       pip install -r requirements.txt
       pip install -r requirements-dev.txt
   ```

4. **运行测试并生成覆盖率**
   ```yaml
   - name: Run tests with coverage
     working-directory: src/code/agent
     run: |
       pytest --cov=. --cov-report=xml --cov-report=html --cov-report=term
   ```

5. **检查差异覆盖率**
   ```yaml
   - name: Check diff coverage
     working-directory: src/code/agent
     run: |
       diff-cover coverage.xml --compare-branch=origin/cap --fail-under=95
   ```

**关键参数解释**：
- `--compare-branch=origin/cap`: 与 cap 分支对比
- `--fail-under=95`: 差异覆盖率低于 95% 时失败
- `fetch-depth: 0`: 必须获取完整历史，否则 diff-cover 无法找到基准分支

### 3.6 CI 行为分析

**场景 1: 新增代码覆盖率 ≥ 95%**
```
✅ pytest 通过
✅ diff-cover 通过（差异覆盖率 95%+）
✅ CI 通过
```

**场景 2: 新增代码覆盖率 < 95%**
```
✅ pytest 通过（测试本身没问题）
❌ diff-cover 失败（差异覆盖率不足）
❌ CI 失败
```

**场景 3: 仅修改测试代码**
```
✅ pytest 通过
✅ diff-cover 通过（测试代码被 omit 排除）
✅ CI 通过
```

**场景 4: 没有新增代码**
```
✅ pytest 通过
✅ diff-cover 通过（无差异）
✅ CI 通过
```

---

## 四、技术决策

### 4.1 为什么选择 diff-cover？

| 考虑因素 | diff-cover | pytest-cov | 自定义脚本 | 第三方服务 |
|---------|-----------|-----------|----------|----------|
| 差异覆盖率计算 | ✅ 原生支持 | ❌ 不支持 | ⚠️ 需自己实现 | ✅ 支持 |
| 维护成本 | ✅ 低 | ✅ 低 | ❌ 高 | ✅ 低 |
| 数据隐私 | ✅ 本地运行 | ✅ 本地运行 | ✅ 本地运行 | ❌ 上传到外部 |
| 配置复杂度 | ✅ 简单 | ✅ 简单 | ❌ 复杂 | ⚠️ 需账号配置 |
| 成本 | ✅ 免费 | ✅ 免费 | ✅ 免费 | ⚠️ 可能收费 |

### 4.2 为什么使用 XML 格式？

diff-cover 支持多种格式，选择 XML（Cobertura）的原因：
- coverage.py 原生支持生成 XML
- XML 格式标准化，兼容性好
- diff-cover 对 XML 格式支持最成熟

### 4.3 为什么需要完整 git 历史？

diff-cover 需要：
- 访问基准分支（cap）的提交历史
- 计算当前分支与基准分支的 diff
- 如果使用 `fetch-depth: 1`（浅克隆），无法访问 cap 分支，diff-cover 会失败

**性能考虑**：
- 完整历史克隆会增加 checkout 时间（通常 5-30 秒）
- 但这是必要的代价，无法避免

### 4.4 工作目录设计

**选择**: 在 `src/code/agent` 目录中执行所有操作

**理由**：
- 测试代码位于 `src/code/agent/test/`
- 源代码位于 `src/code/agent/`
- requirements.txt 位于 `src/code/agent/`
- 保持路径简洁，避免复杂的相对路径

**注意事项**：
- coverage.xml 将生成在 `src/code/agent/coverage.xml`
- 需要在 .gitignore 中排除此文件

---

## 五、配置文件设计细节

### 5.1 pytest.ini 设计

**位置**: `src/code/agent/pytest.ini`

**设计考虑**：
- 使用 `testpaths = test` 而不是绝对路径，保持配置简洁
- 匹配现有测试文件命名模式 `*_test.py`
- 添加 `-v` 详细输出，便于 CI 日志调试
- 添加 `--tb=short` 减少错误堆栈输出

### 5.2 .coveragerc 设计

**位置**: `src/code/agent/.coveragerc`

**关键配置**：

1. **source = .**: 从当前目录（src/code/agent）开始分析
2. **omit 列表**: 排除不需要覆盖的文件
   - 测试文件本身（*/test/*）
   - Python 缓存（*/__pycache__/*）
   - 虚拟环境（*/venv/*, */.venv/*）
   - 覆盖率报告目录（*/htmlcov/*）

3. **report 配置**:
   - `precision = 2`: 显示到小数点后两位
   - `show_missing = True`: 显示未覆盖的行号
   - `skip_covered = False`: 报告中包含已覆盖的文件

4. **xml 输出**: `output = coverage.xml`，供 diff-cover 使用

### 5.3 requirements-dev.txt 设计

**位置**: `src/code/agent/requirements-dev.txt`

**版本选择策略**：
- pytest: ≥8.0.0（最新稳定版，2024年初发布）
- pytest-cov: ≥4.1.0（支持 pytest 8.x）
- diff-cover: ≥9.2.0（最新版本，2025年3月）

**为什么分离测试依赖**：
- 生产环境不需要测试工具
- 保持 requirements.txt 简洁
- CI 可以分别安装

---

## 六、GitHub Actions 工作流设计

### 6.1 触发条件

```yaml
on:
  push:
    branches:
      - '**'  # 所有分支的 push 都触发
```

**设计说明**：
- 使用 `'**'` 匹配所有分支（包括 cap、feature 分支等）
- 满足"每次 push 都运行"的需求
- 不限制 PR，push 即触发

### 6.2 作业配置

```yaml
jobs:
  test-coverage:
    runs-on: ubuntu-latest
    steps: [...]
```

**选择 ubuntu-latest 的理由**：
- 项目使用 Linux 环境部署（Dockerfile 基于 python:3.10.16-slim）
- GitHub Actions 的 ubuntu-latest 性能最优
- 与生产环境更接近

### 6.3 关键步骤分析

**Step 1: Checkout with full history**
```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0
```
- 必须获取完整历史，供 diff-cover 对比

**Step 2: Python setup**
```yaml
- uses: actions/setup-python@v5
  with:
    python-version: '3.10'
    cache: 'pip'
```
- 匹配项目的 Python 3.10 版本
- 使用 pip 缓存加速依赖安装

**Step 3: Install dependencies**
```yaml
- run: |
    pip install -r requirements.txt
    pip install -r requirements-dev.txt
```
- 分两步安装，先生产依赖后测试依赖
- 确保测试环境与生产环境一致

**Step 4: Run tests**
```yaml
- run: pytest --cov=. --cov-report=xml --cov-report=term
```
- `--cov=.`: 覆盖当前目录（src/code/agent）
- `--cov-report=xml`: 生成 XML 供 diff-cover 使用
- `--cov-report=term`: 在 CI 日志中显示覆盖率摘要

**Step 5: Check diff coverage**
```yaml
- run: diff-cover coverage.xml --compare-branch=origin/cap --fail-under=95
```
- 对比 origin/cap 分支
- 阈值 95%
- 失败时返回非零退出码，CI 失败

### 6.4 可选增强步骤

**上传覆盖率报告（artifact）**
```yaml
- uses: actions/upload-artifact@v4
  if: always()
  with:
    name: coverage-report
    path: src/code/agent/htmlcov/
```
- 保存 HTML 报告，便于查看详细覆盖率信息
- 使用 `if: always()` 确保即使测试失败也上传

**差异覆盖率 HTML 报告**
```yaml
- run: diff-cover coverage.xml --compare-branch=origin/cap --html-report diff-coverage.html
```
- 生成可视化的差异覆盖率报告

---

## 七、风险评估

### 7.1 潜在风险

**风险 1: 首次运行可能失败**
- **原因**: 现有代码整体覆盖率 77%，如果对现有代码进行修改，可能无法达到 95%
- **应对**: 首次合并时可以临时降低阈值，逐步提升

**风险 2: 基准分支不存在**
- **原因**: GitHub Actions 只 checkout 当前分支，origin/cap 可能不存在
- **应对**: 使用 `fetch-depth: 0` 获取所有分支

**风险 3: 测试依赖冲突**
- **原因**: 新增的测试依赖可能与现有依赖冲突
- **应对**: 使用兼容的版本范围，测试后确认

**风险 4: diff-cover 无法识别重命名**
- **原因**: 文件重命名时，diff-cover 可能误判为删除+新增
- **应对**: diff-cover 较新版本已改进此问题

### 7.2 降级方案

如果 diff-cover 方案遇到问题，可以降级到：
1. 先使用 pytest-cov 的 `--cov-fail-under` 检查整体覆盖率（阈值可设置为 70%）
2. 逐步提升测试覆盖率到 95%
3. 最终再引入 diff-cover

---

## 八、本地开发体验

### 8.1 本地运行命令

开发者可以在本地模拟 CI 流程：

```bash
# 进入 agent 目录
cd src/code/agent

# 安装测试依赖
pip install -r requirements-dev.txt

# 运行测试并生成覆盖率
pytest --cov=. --cov-report=xml --cov-report=html --cov-report=term

# 检查差异覆盖率
diff-cover coverage.xml --compare-branch=cap --fail-under=95

# 查看 HTML 报告
open htmlcov/index.html  # macOS
```

### 8.2 Makefile 集成建议

可以在项目根目录的 Makefile 中添加：

```makefile
.PHONY: test
test:
	cd src/code/agent && pytest

.PHONY: test-cov
test-cov:
	cd src/code/agent && pytest --cov=. --cov-report=html --cov-report=term

.PHONY: test-diff
test-diff:
	cd src/code/agent && \
	pytest --cov=. --cov-report=xml && \
	diff-cover coverage.xml --compare-branch=cap --fail-under=95
```

---

## 九、扩展性考虑

### 9.1 已实现的增强功能

1. **GitHub Pages 自动部署** ✅
   - 在 cap 分支自动部署覆盖率报告
   - 提供美观的导航页面
   - 包含完整覆盖率和差异覆盖率两个报告
   - 永久链接，无需下载即可查看

### 9.2 未来可能的增强

1. **覆盖率徽章**
   - 使用 shields.io 生成覆盖率徽章
   - 在 README 中显示

2. **PR 评论**
   - 使用 GitHub Actions 在 PR 中自动评论覆盖率报告
   - 工具: coverage-comment-action

3. **覆盖率趋势**
   - 存储历史覆盖率数据
   - 生成趋势图表

4. **多 Python 版本测试**
   - 使用 matrix 策略测试多个 Python 版本
   - 例如: 3.9, 3.10, 3.11

### 9.2 其他代码目录

如果将来需要对 `src/code/sd` 目录也进行覆盖率检查：
- 复制相同的配置文件
- 创建单独的 workflow 或使用 matrix 策略

---

## 十、对比总结

| 方案 | 符合需求 | 实施难度 | 维护成本 | 推荐度 |
|-----|---------|---------|---------|--------|
| A: diff-cover | ✅ 完全符合 | ⭐⭐ 简单 | ⭐ 低 | ⭐⭐⭐⭐⭐ |
| B: pytest-cov | ❌ 不符合 | ⭐ 非常简单 | ⭐ 低 | ⭐ |
| C: 自定义脚本 | ⚠️ 可实现 | ⭐⭐⭐⭐⭐ 复杂 | ⭐⭐⭐⭐⭐ 高 | ⭐⭐ |
| D: 第三方服务 | ✅ 符合 | ⭐⭐⭐ 中等 | ⭐⭐ 中等 | ⭐⭐⭐ |

**最终推荐**: 方案 A（diff-cover）

---

## 十一、实施路线图概览

```
阶段 1: 配置文件准备
├── 创建 requirements-dev.txt
├── 创建 pytest.ini
├── 创建 .coveragerc
└── 更新 .gitignore

阶段 2: GitHub Actions 配置
├── 创建 .github/workflows/ 目录
└── 创建 test-coverage.yml

阶段 3: 验证测试
├── 本地测试运行
├── 推送到 GitHub
└── 验证 CI 运行结果

阶段 4: 文档更新
└── 更新 README（可选）
```

---

## 十二、预期效果

实施完成后：
- ✅ 每次 push 自动运行测试
- ✅ 生成详细的覆盖率报告
- ✅ 自动检查新增代码覆盖率
- ✅ 覆盖率不足时 CI 失败，阻止低质量代码合并
- ✅ 开发者可以在本地运行相同的检查
- ✅ 保持现有代码不受影响（仅检查新增代码）
- ✅ cap 分支的覆盖率报告自动部署到 GitHub Pages
- ✅ 团队成员可以随时通过浏览器访问最新覆盖率报告

**GitHub Pages 访问方式**:
```
https://<your-github-username>.github.io/cap-comfyui/
```

**页面内容**:
- 导航页面（index.html）：显示最后更新时间，提供两个报告链接
- 完整覆盖率报告（htmlcov/）：所有源代码的详细覆盖率
- 差异覆盖率报告（diff-coverage.html）：新增代码的覆盖率分析

---

## 附录：diff-cover 命令参考

### 基本用法
```bash
diff-cover coverage.xml --compare-branch=origin/cap
```

### 设置阈值
```bash
diff-cover coverage.xml --compare-branch=origin/cap --fail-under=95
```

### 生成 HTML 报告
```bash
diff-cover coverage.xml --compare-branch=origin/cap --html-report report.html
```

### 指定 diff 范围
```bash
diff-cover coverage.xml --compare-branch=origin/cap --diff-range-notation='..'
```

### 查看帮助
```bash
diff-cover --help
```
