# GitHub CI 覆盖率检查 - 开发文档

**创建日期**: 2026-02-25  
**作者**: cici  
**关联设计**: design.md

---

## 一、任务分解

本任务分为 4 个阶段，按顺序执行：

### 阶段 1: 测试依赖配置文件创建
创建测试所需的配置文件，确保测试环境正确配置。

### 阶段 2: GitHub Actions 工作流创建
创建 CI 配置文件，实现自动化测试和覆盖率检查。

### 阶段 3: gitignore 配置更新
更新 .gitignore，排除覆盖率生成的临时文件。

### 阶段 4: 验证测试
推送代码，验证 CI 是否正常工作。

---

## 二、详细实施规范

### 阶段 1: 测试依赖配置文件创建

#### 文件 1.1: src/code/agent/requirements-dev.txt

**位置**: `/Users/cici/workspace/code/cap-comfyui/src/code/agent/requirements-dev.txt`  
**操作**: 创建新文件  
**内容规范**:

```txt
pytest>=8.0.0
pytest-cov>=4.1.0
diff-cover>=9.2.0
```

**说明**:
- pytest: 测试框架核心
- pytest-cov: pytest 的覆盖率插件
- diff-cover: 差异覆盖率分析工具
- 使用 >= 约束，允许向后兼容的补丁更新

---

#### 文件 1.2: src/code/agent/pytest.ini

**位置**: `/Users/cici/workspace/code/cap-comfyui/src/code/agent/pytest.ini`  
**操作**: 创建新文件  
**内容规范**:

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

**配置项说明**:
- `testpaths = test`: 测试文件搜索路径，指向 test/ 目录
- `python_files = *_test.py`: 匹配现有测试文件命名模式（如 task_manager_test.py）
- `python_classes = Test*`: 测试类以 Test 开头
- `python_functions = test_*`: 测试函数以 test_ 开头
- `addopts`:
  - `-v`: 详细输出模式，显示每个测试的结果
  - `--strict-markers`: 严格标记模式，防止拼写错误的标记
  - `--tb=short`: 使用简短的回溯格式，减少日志输出

---

#### 文件 1.3: src/code/agent/.coveragerc

**位置**: `/Users/cici/workspace/code/cap-comfyui/src/code/agent/.coveragerc`  
**操作**: 创建新文件  
**内容规范**:

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
    */.pytest_cache/*

[report]
precision = 2
show_missing = True
skip_covered = False
exclude_lines =
    pragma: no cover
    def __repr__
    raise AssertionError
    raise NotImplementedError
    if __name__ == .__main__.:
    if TYPE_CHECKING:
    @abstractmethod

[html]
directory = htmlcov

[xml]
output = coverage.xml
```

**配置项说明**:

**[run] 节**:
- `source = .`: 分析当前目录（src/code/agent）的代码
- `omit`: 排除不需要覆盖率统计的文件模式
  - 测试文件本身
  - Python 缓存目录
  - 虚拟环境
  - 覆盖率报告目录

**[report] 节**:
- `precision = 2`: 覆盖率百分比精确到小数点后两位
- `show_missing = True`: 显示未覆盖的行号
- `skip_covered = False`: 报告中包含已覆盖的文件
- `exclude_lines`: 排除特定代码模式（如 pragma 注释、抽象方法等）

**[html] 节**:
- `directory = htmlcov`: HTML 报告输出目录

**[xml] 节**:
- `output = coverage.xml`: XML 报告输出文件（供 diff-cover 使用）

---

### 阶段 2: GitHub Actions 工作流创建

#### 文件 2.1: .github/workflows/test-coverage.yml

**位置**: `/Users/cici/workspace/code/cap-comfyui/.github/workflows/test-coverage.yml`  
**操作**: 创建新文件（需先创建 .github/workflows 目录）  
**内容规范**:

```yaml
name: Test Coverage

on:
  push:
    branches:
      - '**'

permissions:
  contents: write

jobs:
  test-coverage:
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout code with full history
        uses: actions/checkout@v4
        with:
          fetch-depth: 0
      
      - name: Set up Python 3.10
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'
          cache: 'pip'
      
      - name: Install dependencies
        working-directory: src/code/agent
        run: |
          pip install -r requirements.txt
          pip install -r requirements-dev.txt
      
      - name: Run tests with coverage
        working-directory: src/code/agent
        run: |
          pytest --cov=. --cov-report=xml --cov-report=html --cov-report=term
      
      - name: Check diff coverage against cap branch
        working-directory: src/code/agent
        run: |
          diff-cover coverage.xml --compare-branch=origin/cap --fail-under=95
      
      - name: Upload coverage report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: coverage-report
          path: src/code/agent/htmlcov/
          retention-days: 30
      
      - name: Generate diff coverage HTML report
        if: always()
        working-directory: src/code/agent
        run: |
          diff-cover coverage.xml --compare-branch=origin/cap --html-report=diff-coverage.html
      
      - name: Upload diff coverage report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: diff-coverage-report
          path: src/code/agent/diff-coverage.html
          retention-days: 30
      
      - name: Create coverage index page
        if: github.ref == 'refs/heads/cap'
        working-directory: src/code/agent
        run: |
          mkdir -p gh-pages-deploy
          cp -r htmlcov/* gh-pages-deploy/
          cp diff-coverage.html gh-pages-deploy/
          cat > gh-pages-deploy/index.html << 'EOF'
          <!DOCTYPE html>
          <html>
          <head>
            <meta charset="utf-8">
            <title>Coverage Reports - cap-comfyui</title>
            <style>
              body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; }
              h1 { color: #333; }
              .report-card { border: 1px solid #ddd; border-radius: 8px; padding: 20px; margin: 20px 0; background: #f9f9f9; }
              .report-card h2 { margin-top: 0; color: #0366d6; }
              .report-card a { display: inline-block; margin-top: 10px; padding: 8px 16px; background: #0366d6; color: white; text-decoration: none; border-radius: 4px; }
              .report-card a:hover { background: #0256c7; }
              .timestamp { color: #666; font-size: 14px; }
            </style>
          </head>
          <body>
            <h1>Coverage Reports - cap-comfyui Agent</h1>
            <p class="timestamp">Last updated: $(date -u +"%Y-%m-%d %H:%M:%S UTC")</p>
            
            <div class="report-card">
              <h2>📊 Full Coverage Report</h2>
              <p>Complete test coverage report for all source code in src/code/agent/</p>
              <a href="htmlcov/index.html">View Full Coverage Report</a>
            </div>
            
            <div class="report-card">
              <h2>📈 Diff Coverage Report</h2>
              <p>Coverage report for code changes compared to the cap branch</p>
              <a href="diff-coverage.html">View Diff Coverage Report</a>
            </div>
            
            <div class="report-card">
              <h2>ℹ️ About</h2>
              <p>These reports are automatically generated by GitHub Actions on every push to the cap branch.</p>
              <p>Diff coverage threshold: ≥ 95%</p>
            </div>
          </body>
          </html>
          EOF
      
      - name: Deploy to GitHub Pages
        if: github.ref == 'refs/heads/cap'
        uses: peaceiris/actions-gh-pages@v3
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: src/code/agent/gh-pages-deploy
          keep_files: false
```

**权限配置**:
- `permissions: contents: write`: 允许 workflow 向 gh-pages 分支推送内容

**步骤说明**:

1. **Checkout code with full history**
   - 使用 `actions/checkout@v4`（最新版本）
   - `fetch-depth: 0`: 获取完整 git 历史，diff-cover 需要访问 cap 分支

2. **Set up Python 3.10**
   - 使用 `actions/setup-python@v5`
   - 指定 Python 3.10，匹配项目版本
   - `cache: 'pip'`: 缓存 pip 依赖，加速后续运行

3. **Install dependencies**
   - 工作目录: `src/code/agent`
   - 先安装生产依赖，再安装测试依赖
   - 确保环境与本地一致

4. **Run tests with coverage**
   - 工作目录: `src/code/agent`
   - `--cov=.`: 覆盖当前目录
   - `--cov-report=xml`: 生成 coverage.xml（必需，供 diff-cover 使用）
   - `--cov-report=html`: 生成 HTML 报告（可选，便于查看）
   - `--cov-report=term`: 终端输出（可选，CI 日志中显示）

5. **Check diff coverage** ⚠️ **关键步骤**
   - 工作目录: `src/code/agent`
   - `--compare-branch=origin/cap`: 与远程 cap 分支对比
   - `--fail-under=95`: 差异覆盖率低于 95% 时失败
   - 此步骤失败会导致整个 CI 失败

6. **Upload coverage report**
   - `if: always()`: 即使前面步骤失败也上传
   - 保存 HTML 覆盖率报告为 artifact
   - 保留 30 天

7. **Generate diff coverage HTML report**
   - 生成可视化的差异覆盖率报告
   - 显示哪些新增行未被覆盖

8. **Upload diff coverage report**
   - 上传差异覆盖率 HTML 报告
   - 便于查看具体是哪些代码未覆盖

9. **Create coverage index page** 🆕
   - `if: github.ref == 'refs/heads/cap'`: 仅在 cap 分支运行
   - 创建 gh-pages-deploy 临时目录
   - 复制 htmlcov 和 diff-coverage.html
   - 生成 index.html 作为导航页面
   - 显示最后更新时间和报告链接

10. **Deploy to GitHub Pages** 🆕
    - `if: github.ref == 'refs/heads/cap'`: 仅在 cap 分支部署
    - 使用 `peaceiris/actions-gh-pages@v3` action
    - 自动推送到 gh-pages 分支
    - `keep_files: false`: 每次完全替换，避免累积旧文件

---

### 阶段 3: gitignore 配置更新

#### 文件 3.1: .gitignore

**位置**: `/Users/cici/workspace/code/cap-comfyui/.gitignore`  
**操作**: 在现有文件末尾追加内容  
**追加内容**:

```
# Coverage reports
**/.coverage
**/.coverage.*
**/coverage.xml
**/htmlcov/
**/diff-coverage.html
**/gh-pages-deploy/
```

**说明**:
- 排除 coverage.py 生成的所有覆盖率相关文件
- 排除 gh-pages-deploy 临时目录（用于 GitHub Pages 部署）
- 这些文件不应提交到仓库（每次运行都会重新生成）

---

### 阶段 4: GitHub Pages 配置

#### 配置 4.1: 启用 GitHub Pages

**操作步骤**:
1. 打开 GitHub 仓库网页
2. 导航到 **Settings** > **Pages**
3. 在 **Source** 部分选择：
   - Branch: `gh-pages`
   - Folder: `/ (root)`
4. 点击 **Save**

**说明**:
- gh-pages 分支会在首次部署时自动创建
- 无需手动创建该分支
- peaceiris/actions-gh-pages action 会自动处理

**访问链接**:
部署后，覆盖率报告将可通过以下链接访问：
```
https://<username>.github.io/<repo>/
```

**示例结构**:
```
https://<your-github-username>.github.io/cap-comfyui/
├── index.html              # 导航页面
├── htmlcov/               # 完整覆盖率报告
│   └── index.html
└── diff-coverage.html     # 差异覆盖率报告
```

---

### 阶段 5: 本地验证测试

#### 验证步骤 5.1: 本地测试

**命令序列**:
```bash
cd src/code/agent
pip install -r requirements-dev.txt
pytest --cov=. --cov-report=xml --cov-report=term
diff-cover coverage.xml --compare-branch=cap --fail-under=95
```

**预期结果**:
- pytest 应该全部通过
- coverage.xml 生成成功
- diff-cover 执行成功（可能失败，取决于当前分支的变更）

**注意**: 如果当前分支相对 cap 没有代码变更，diff-cover 会显示 "No lines with coverage information in this diff"

#### 验证步骤 6.1: 推送并观察 CI

**命令序列**:
```bash
git add .github/workflows/test-coverage.yml
git add src/code/agent/requirements-dev.txt
git add src/code/agent/pytest.ini
git add src/code/agent/.coveragerc
git add .gitignore
git add docs/github-ci-coverage/
git add .tasks/
git commit -m "feat: add GitHub CI with 95% diff coverage check and GitHub Pages deployment"
git push -u origin task/github-ci-coverage_2026-02-25_1
```

**预期结果**:
- GitHub Actions 自动触发
- 在 GitHub 仓库的 Actions 标签页可以看到运行状态
- CI 运行约 2-5 分钟
- 检查 CI 是否成功

#### 验证步骤 6.2: GitHub Pages 部署验证

**前置条件**: 
- CI 在功能分支成功运行
- 代码已合并到 cap 分支

**命令序列**:
```bash
# 合并到 cap 分支（在 CI 验证通过后）
git checkout cap
git merge task/github-ci-coverage_2026-02-25_1
git push origin cap
```

**验证步骤**:
1. 推送到 cap 分支后，等待 CI 运行完成
2. 在 GitHub Actions 页面确认 "Deploy to GitHub Pages" 步骤成功
3. 在 Settings > Pages 查看部署状态
4. 访问 GitHub Pages 链接（格式：`https://<username>.github.io/<repo>/`）
5. 验证 index.html 导航页面正常显示
6. 点击链接，验证完整覆盖率报告和差异覆盖率报告可访问

**预期结果**:
- ✅ gh-pages 分支自动创建
- ✅ 覆盖率报告部署成功
- ✅ 可以通过浏览器访问报告
- ✅ 页面显示最后更新时间
- ✅ 两个报告链接都正常工作

---

## 三、文件清单与路径映射

| 序号 | 文件路径 | 操作类型 | 描述 |
|-----|---------|---------|------|
| 1 | src/code/agent/requirements-dev.txt | 创建 | 测试依赖配置 |
| 2 | src/code/agent/pytest.ini | 创建 | pytest 配置 |
| 3 | src/code/agent/.coveragerc | 创建 | coverage 配置 |
| 4 | .github/workflows/test-coverage.yml | 创建 | GitHub Actions 工作流（含 Pages 部署） |
| 5 | .gitignore | 修改 | 追加覆盖率文件排除规则 |
| 6 | GitHub Pages 设置 | 配置 | 在仓库 Settings 中启用 |

---

## 四、依赖关系

```
阶段 1 (配置文件) 
    └─> 阶段 2 (GitHub Actions)
            └─> 阶段 3 (.gitignore)
                    └─> 阶段 4 (GitHub Pages 配置)
                            └─> 阶段 5 (本地验证)
                                    └─> 阶段 6 (提交与部署验证)
```

**依赖说明**:
- 阶段 1 必须先完成，因为 GitHub Actions 依赖这些配置文件
- 阶段 2 和阶段 3 可以并行，但建议顺序执行
- 阶段 4 (GitHub Pages 配置) 可以在推送后再配置
- 阶段 5 在文件创建后本地验证
- 阶段 6 需要所有配置完成后执行

---

## 五、实施清单

### 前置准备
- [x] 创建任务分支 `task/github-ci-coverage_2026-02-25_1`
- [x] 创建任务文件 `.tasks/2026-02-25_1_github-ci-coverage.md`
- [x] 创建设计文档 `docs/github-ci-coverage/design.md`
- [x] 创建开发文档 `docs/github-ci-coverage/development.md`
- [x] 创建测试文档 `docs/github-ci-coverage/cases.md`

### 阶段 1: 测试依赖配置文件创建
1. 创建文件 `src/code/agent/requirements-dev.txt`，包含 3 行依赖（pytest>=8.0.0、pytest-cov>=4.1.0、diff-cover>=9.2.0）
2. 创建文件 `src/code/agent/pytest.ini`，配置 testpaths=test、python_files=*_test.py、python_classes=Test*、python_functions=test_*、addopts=-v/--strict-markers/--tb=short
3. 创建文件 `src/code/agent/.coveragerc`，配置 [run] source=./omit 测试文件、[report] precision=2/show_missing=True、[html] directory=htmlcov、[xml] output=coverage.xml

### 阶段 2: GitHub Actions 工作流创建
4. 创建目录 `.github/workflows/`
5. 创建文件 `.github/workflows/test-coverage.yml`，包含 name=Test Coverage、on push all branches、permissions contents write、jobs test-coverage with 10 steps（checkout、setup python、install、test、check diff、upload artifacts×2、create index、deploy pages）

### 阶段 3: gitignore 配置更新
6. 在 `.gitignore` 文件末尾追加 6 行覆盖率文件排除规则（.coverage*、coverage.xml、htmlcov/、diff-coverage.html、gh-pages-deploy/）

### 阶段 4: GitHub Pages 配置
7. 在 GitHub 仓库 Settings > Pages 中配置 Source 为 gh-pages 分支、目录为 root

### 阶段 5: 本地验证测试
8. 在 src/code/agent 目录执行 `pip install -r requirements-dev.txt` 安装测试依赖
9. 在 src/code/agent 目录执行 `pytest --cov=. --cov-report=xml --cov-report=html --cov-report=term` 运行测试
10. 在 src/code/agent 目录执行 `diff-cover coverage.xml --compare-branch=cap` 验证 diff-cover 工具

### 阶段 6: 提交与 CI 验证
11. 暂存所有新增文件（git add .github/ src/code/agent/requirements-dev.txt src/code/agent/pytest.ini src/code/agent/.coveragerc .gitignore docs/ .tasks/）
12. 提交更改（git commit -m "feat: add GitHub CI with 95% diff coverage check and GitHub Pages deployment"）
13. 推送到远程仓库（git push -u origin task/github-ci-coverage_2026-02-25_1）
14. 在 GitHub Actions 页面查看 workflow 运行状态
15. 确认所有 CI 步骤执行成功（除 GitHub Pages 部署外，因为不在 cap 分支）

### 阶段 7: GitHub Pages 部署验证（需要合并到 cap 后）
16. 创建 Pull Request 或直接合并到 cap 分支
17. 推送到 cap 分支触发 GitHub Pages 部署
18. 等待 CI 完成并检查 "Deploy to GitHub Pages" 步骤成功
19. 访问 GitHub Pages URL（https://\<username\>.github.io/\<repo\>/）验证导航页面
20. 点击 "View Full Coverage Report" 验证完整报告可访问
21. 点击 "View Diff Coverage Report" 验证差异报告可访问

---

## 六、工作量估算

| 阶段 | 文件数量 | 预估复杂度 | 风险等级 |
|-----|---------|-----------|---------|
| 阶段 1 | 3 个文件 | 低 | 低 |
| 阶段 2 | 1 个文件 | 中 | 中 |
| 阶段 3 | 1 个文件 | 低 | 低 |
| 阶段 4 | GitHub 配置 | 低 | 低 |
| 阶段 5 | 本地验证 | 中 | 中 |
| 阶段 6 | CI+Pages 验证 | 中 | 中 |

**总计**: 5 个文件修改/创建，1 个 GitHub 配置，17 个实施步骤

---

## 七、潜在问题与解决方案

### 问题 1: 首次运行 diff-cover 可能找不到 cap 分支

**原因**: GitHub Actions 默认只 checkout 当前分支

**解决**: 
- 使用 `fetch-depth: 0` 获取完整历史
- diff-cover 使用 `origin/cap` 而不是 `cap`

### 问题 2: 如果当前分支是 cap 分支本身

**现象**: diff-cover 会显示 "No lines with coverage information in this diff"

**解决**: 这是正常行为，因为没有差异

### 问题 3: Python 3.10 在 GitHub Actions 中可能不是默认版本

**解决**: 明确指定 `python-version: '3.10'` 在 setup-python action 中

### 问题 4: working-directory 设置错误导致找不到文件

**解决**: 所有与测试相关的步骤都设置 `working-directory: src/code/agent`

### 问题 5: 依赖安装失败

**可能原因**: 
- requirements.txt 中的某些包无法安装
- 网络问题

**解决**: 
- 本地先测试依赖安装
- 如果遇到问题，检查包版本兼容性

### 问题 6: GitHub Pages 部署权限问题

**原因**: workflow 没有写入 gh-pages 分支的权限

**解决**: 
- 在 workflow 顶层添加 `permissions: contents: write`
- 使用内置的 `${{ secrets.GITHUB_TOKEN }}`

### 问题 7: GitHub Pages 未启用

**现象**: 部署成功但无法访问页面

**解决**: 
- 在仓库 Settings > Pages 中配置 Source 为 gh-pages 分支
- 等待几分钟让 GitHub Pages 生效

### 问题 8: GitHub Pages 显示 404

**可能原因**: 
- Pages 配置的分支或目录错误
- 部署未成功
- index.html 不存在

**解决**: 
- 检查 gh-pages 分支是否存在且有内容
- 确认 Settings > Pages 配置正确
- 查看 Actions 日志确认部署步骤成功

---

## 八、验证清单

实施完成后，验证以下内容：

### 配置文件验证
- [ ] requirements-dev.txt 内容正确
- [ ] pytest.ini 配置项完整
- [ ] .coveragerc 配置项完整
- [ ] test-coverage.yml 语法正确（YAML 格式）
- [ ] .gitignore 已更新

### 本地验证
- [ ] 可以成功安装 requirements-dev.txt
- [ ] pytest 可以发现并运行所有测试
- [ ] coverage.xml 生成成功
- [ ] diff-cover 可以正常执行

### CI 验证
- [ ] GitHub Actions workflow 出现在仓库中
- [ ] Push 后自动触发 CI
- [ ] CI 日志中可以看到所有步骤
- [ ] pytest 步骤显示测试结果
- [ ] diff-cover 步骤显示差异覆盖率
- [ ] artifact 上传成功（coverage-report 和 diff-coverage-report）

---

## 九、回滚计划

如果实施后发现问题：

1. **配置错误**:
   - 修改对应的配置文件
   - 重新提交

2. **CI 持续失败**:
   - 检查 GitHub Actions 日志
   - 确认错误原因
   - 根据错误调整配置

3. **阻碍正常开发**:
   - 临时降低 `--fail-under` 阈值（如 80%）
   - 逐步提升覆盖率
   - 最终恢复到 95%

4. **完全回滚**:
   - 删除 `.github/workflows/test-coverage.yml`
   - 或暂时禁用 workflow（在文件中添加 `if: false`）

---

## 十、后续优化建议

实施完成后，可以考虑的增强功能：

1. **PR 评论集成**
   - 使用 GitHub Actions 在 PR 中自动评论覆盖率信息
   - 工具: py-cov-action/python-coverage-comment-action

2. **覆盖率徽章**
   - 生成动态徽章显示在 README 中
   - 工具: shields.io

3. **多 Python 版本测试**
   - 使用 matrix 策略测试 Python 3.9, 3.10, 3.11
   - 确保跨版本兼容性

4. **Makefile 集成**
   - 在项目根目录 Makefile 中添加 `make test-diff` 命令
   - 便于开发者快速运行差异覆盖率检查

5. **通知集成**
   - 失败时发送通知到 Slack/钉钉等
   - 使用 GitHub Actions 的通知 action

---

## 十一、技术债务

无新增技术债务。

现有技术债务：
- 整体测试覆盖率 77%，建议逐步提升到 90%+

---

## 十二、进度跟踪

| 步骤 | 状态 | 完成时间 | 备注 |
|-----|------|---------|------|
| 1. requirements-dev.txt | 待执行 | - | - |
| 2. pytest.ini | 待执行 | - | - |
| 3. .coveragerc | 待执行 | - | - |
| 4. .github/workflows/ | 待执行 | - | - |
| 5. test-coverage.yml | 待执行 | - | - |
| 6. .gitignore | 待执行 | - | - |
| 7-14. 验证测试 | 待执行 | - | - |

---

## 十三、参考资料

- [diff-cover 官方文档](https://diff-cover.readthedocs.io/)
- [pytest-cov 文档](https://pytest-cov.readthedocs.io/)
- [GitHub Actions 文档](https://docs.github.com/en/actions)
- [coverage.py 文档](https://coverage.readthedocs.io/)
