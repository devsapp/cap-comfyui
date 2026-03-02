# GitHub CI 覆盖率检查 - 测试文档

**创建日期**: 2026-02-25  
**作者**: cici  
**关联设计**: design.md  
**关联开发**: development.md

---

## 一、测试策略

### 1.1 测试范围

本任务主要是配置文件和 CI 流程的创建，测试策略包括：

1. **配置文件语法验证**: 确保 YAML、INI 等配置文件格式正确
2. **本地集成测试**: 验证 pytest + coverage + diff-cover 工具链在本地正常工作
3. **CI 集成测试**: 验证 GitHub Actions 工作流正确执行
4. **边界场景测试**: 测试各种 git diff 场景下的行为

### 1.2 测试类型

- **手动测试**: 本地运行命令验证
- **集成测试**: GitHub Actions 自动运行
- **场景测试**: 模拟不同代码变更场景

---

## 二、配置文件验证测试

### 测试用例 2.1: YAML 语法验证

**测试目标**: `.github/workflows/test-coverage.yml`  
**测试方法**: 使用 YAML linter 或 GitHub Actions 语法检查

**步骤**:
1. 创建 workflow 文件
2. 使用在线工具或命令行工具验证 YAML 语法
3. 或者推送到 GitHub，查看是否有语法错误提示

**预期结果**: 
- ✅ YAML 格式正确，无语法错误
- ✅ 所有必需字段存在
- ✅ 缩进正确

**失败处理**: 根据错误提示修正 YAML 语法

---

### 测试用例 2.2: INI 配置验证

**测试目标**: `pytest.ini` 和 `.coveragerc`  
**测试方法**: 运行相关工具，检查是否正确加载配置

**步骤**:
```bash
cd src/code/agent

# 验证 pytest.ini
pytest --collect-only

# 验证 .coveragerc
coverage run --help
```

**预期结果**:
- ✅ pytest 正确识别配置文件
- ✅ coverage 正确加载 .coveragerc
- ✅ 无警告或错误信息

**失败处理**: 检查配置项名称和值是否正确

---

## 三、本地集成测试

### 测试用例 3.1: 完整测试流程

**测试目标**: 验证整个测试和覆盖率流程在本地正常工作  
**前置条件**: 安装了 requirements-dev.txt 中的所有依赖

**步骤**:
```bash
cd src/code/agent

# Step 1: 运行测试
pytest --cov=. --cov-report=xml --cov-report=html --cov-report=term

# Step 2: 检查生成的文件
ls -la coverage.xml htmlcov/

# Step 3: 运行 diff-cover
diff-cover coverage.xml --compare-branch=cap
```

**预期结果**:
- ✅ 所有测试通过（或至少运行完成）
- ✅ coverage.xml 文件生成
- ✅ htmlcov/ 目录生成，包含 HTML 报告
- ✅ diff-cover 成功执行，显示差异覆盖率

**失败场景**:
- ❌ 测试失败: 检查测试代码，修复失败的测试
- ❌ coverage.xml 未生成: 检查 .coveragerc 配置
- ❌ diff-cover 报错: 检查 git 分支状态和配置

---

### 测试用例 3.2: diff-cover 阈值测试

**测试目标**: 验证 diff-cover 的 `--fail-under` 参数正常工作  
**测试方法**: 故意设置一个很高的阈值，观察是否失败

**步骤**:
```bash
cd src/code/agent

# 运行测试生成覆盖率
pytest --cov=. --cov-report=xml

# 设置不可能达到的阈值（100%）
diff-cover coverage.xml --compare-branch=cap --fail-under=100
```

**预期结果**:
- ❌ diff-cover 应该返回非零退出码
- ❌ 终端显示覆盖率不足的信息

**验证命令**:
```bash
echo $?  # 应该显示非零值（通常是 1）
```

---

### 测试用例 3.3: 覆盖率排除规则测试

**测试目标**: 验证 .coveragerc 的 omit 配置正确排除测试文件  
**测试方法**: 检查覆盖率报告中是否包含测试文件

**步骤**:
```bash
cd src/code/agent
pytest --cov=. --cov-report=term

# 查看报告，确认测试文件被排除
```

**预期结果**:
- ✅ 覆盖率报告中不包含 `test/` 目录下的文件
- ✅ 只统计源代码文件的覆盖率

---

## 四、CI 集成测试

### 测试用例 4.1: 首次 CI 运行测试

**测试目标**: 验证 GitHub Actions workflow 正确触发并执行  
**触发条件**: 推送配置文件到远程仓库

**步骤**:
1. 提交所有配置文件
2. 推送到 GitHub: `git push -u origin task/github-ci-coverage_2026-02-25_1`
3. 在 GitHub 网页打开仓库
4. 导航到 Actions 标签页
5. 查看最新的 workflow 运行

**预期结果**:
- ✅ Workflow 自动触发
- ✅ 所有步骤依次执行
- ✅ Checkout、Setup Python、Install dependencies 步骤成功
- ✅ Run tests 步骤成功（所有测试通过）
- ✅ Check diff coverage 步骤执行（可能成功或失败，取决于覆盖率）
- ✅ Upload artifact 步骤成功

**失败场景处理**:
- 如果 Checkout 失败: 检查仓库权限
- 如果 Install dependencies 失败: 检查 requirements 文件路径和内容
- 如果 Run tests 失败: 检查测试代码本身的问题
- 如果 Check diff coverage 失败: 这是预期行为（如果覆盖率不足）

---

### 测试用例 4.2: Artifact 上传验证

**测试目标**: 验证覆盖率报告正确上传为 artifact  
**前置条件**: CI 已运行完成（无论成功或失败）

**步骤**:
1. 在 GitHub Actions 运行页面，点击具体的 workflow run
2. 在页面底部查看 Artifacts 部分
3. 应该看到两个 artifacts:
   - coverage-report
   - diff-coverage-report
4. 下载并解压查看

**预期结果**:
- ✅ coverage-report 包含完整的 htmlcov 目录
- ✅ diff-coverage-report 包含 diff-coverage.html 文件
- ✅ HTML 文件可以在浏览器中打开并查看

---

### 测试用例 4.3: 触发条件验证

**测试目标**: 验证所有分支的 push 都触发 CI  
**测试方法**: 在不同分支 push 代码

**场景 A: 在功能分支 push**
```bash
git checkout task/github-ci-coverage_2026-02-25_1
echo "test" >> README.md
git commit -am "test: trigger CI"
git push
```
**预期**: 
- ✅ CI 触发
- ✅ 测试和覆盖率检查步骤运行
- ⏭️ GitHub Pages 部署步骤跳过（不是 cap 分支）

**场景 B: 在 cap 分支 push**
```bash
git checkout cap
git merge task/github-ci-coverage_2026-02-25_1
git push
```
**预期**: 
- ✅ CI 触发
- ✅ 测试和覆盖率检查步骤运行
- ✅ GitHub Pages 部署步骤执行

---

### 测试用例 4.4: GitHub Pages 部署验证

**测试目标**: 验证覆盖率报告成功部署到 GitHub Pages  
**前置条件**: 
- 已在 Settings > Pages 启用 GitHub Pages
- 代码已推送到 cap 分支
- CI 运行完成

**步骤**:
1. 在 GitHub Actions 页面查看 cap 分支的 workflow run
2. 展开 "Deploy to GitHub Pages" 步骤
3. 确认步骤成功，没有错误
4. 在 Settings > Pages 查看部署状态（应显示绿色 ✅）
5. 复制 GitHub Pages URL（显示在 Settings > Pages）
6. 在浏览器中访问该 URL
7. 验证 index.html 导航页面加载
8. 点击 "View Full Coverage Report" 链接
9. 验证完整覆盖率报告显示
10. 返回导航页，点击 "View Diff Coverage Report" 链接
11. 验证差异覆盖率报告显示

**预期结果**:
- ✅ GitHub Pages 显示绿色勾，状态为 "Active"
- ✅ 导航页面正常加载，显示最后更新时间
- ✅ 两个报告链接都可点击
- ✅ 完整覆盖率报告显示所有模块的覆盖率
- ✅ 差异覆盖率报告显示与 cap 分支的差异

**失败处理**:
- 如果 404: 检查 Pages 配置和 gh-pages 分支内容
- 如果链接失效: 检查文件路径是否正确
- 如果报告空白: 检查 HTML 文件生成是否成功

---

### 测试用例 4.5: GitHub Pages 自动更新验证

**测试目标**: 验证每次 cap 分支更新时，GitHub Pages 自动刷新  
**测试方法**: 在 cap 分支进行新的提交，观察 Pages 更新

**步骤**:
```bash
# 在 cap 分支做一个小改动
git checkout cap
echo "# Update" >> readme.md
git commit -am "docs: update readme"
git push

# 等待 CI 运行
```

**验证**:
1. 等待 CI 完成（约 3-5 分钟）
2. 刷新 GitHub Pages 页面
3. 检查页面上的 "Last updated" 时间是否更新

**预期结果**:
- ✅ CI 运行完成后，Pages 自动更新
- ✅ 时间戳更新为最新
- ✅ 如有覆盖率变化，报告反映最新数据

---

## 五、边界场景测试

### 测试用例 5.1: 无代码变更场景

**场景**: 只修改文档或配置文件（非 Python 代码）

**模拟步骤**:
```bash
echo "# Update" >> README.md
git commit -am "docs: update readme"
git push
```

**预期结果**:
- ✅ CI 运行
- ✅ pytest 通过
- ✅ diff-cover 显示 "No lines with coverage information in this diff" 或 100%
- ✅ CI 通过

---

### 测试用例 5.2: 仅新增测试文件场景

**场景**: 只添加新的测试文件，没有修改源代码

**模拟步骤**:
```bash
# 创建一个新的测试文件
touch src/code/agent/test/unit/services/new_test.py
git add src/code/agent/test/unit/services/new_test.py
git commit -m "test: add new test"
git push
```

**预期结果**:
- ✅ CI 运行
- ✅ pytest 发现并运行新测试
- ✅ diff-cover 忽略测试文件（因为 omit 配置）
- ✅ CI 通过

---

### 测试用例 5.3: 新增未测试代码场景

**场景**: 新增 Python 代码但没有对应测试

**模拟步骤**:
```bash
# 在某个源文件中添加一个未测试的函数
# 例如在 utils/logger.py 中添加新函数
git commit -am "feat: add new untested function"
git push
```

**预期结果**:
- ✅ CI 运行
- ✅ pytest 通过（现有测试仍然通过）
- ❌ diff-cover 失败（新增代码覆盖率 < 95%）
- ❌ CI 失败，阻止合并

**CI 输出示例**:
```
Diff Coverage: 50.00%
```

---

### 测试用例 5.4: 新增代码并添加完整测试场景

**场景**: 新增 Python 代码，并添加完整测试（覆盖率 ≥ 95%）

**模拟步骤**:
```bash
# 1. 添加新函数
# 2. 添加对应测试，覆盖所有代码路径
git commit -am "feat: add new function with tests"
git push
```

**预期结果**:
- ✅ CI 运行
- ✅ pytest 通过（包括新测试）
- ✅ diff-cover 通过（差异覆盖率 ≥ 95%）
- ✅ CI 通过

---

### 测试用例 5.5: 修改现有低覆盖率代码场景

**场景**: 修改现有代码中覆盖率较低的部分，但没有增加测试

**预期结果**:
- ❌ diff-cover 失败
- ❌ CI 失败
- 💡 这会强制开发者为修改的代码添加测试

---

## 六、Mock 策略

本任务不涉及新的源代码编写，因此无需 Mock 策略。

如果将来需要测试 GitHub Actions 本身（单元测试 workflow）：
- 可以使用 `act` 工具在本地运行 GitHub Actions
- 或使用 GitHub 的 workflow 测试功能

---

## 七、测试覆盖率目标

| 测试类型 | 目标覆盖率 | 说明 |
|---------|-----------|------|
| 配置文件验证 | N/A | 手动验证 |
| 本地集成测试 | 100% | 所有工具链步骤必须成功 |
| CI 集成测试 | 100% | 所有 CI 步骤必须执行 |
| 边界场景测试 | 80% | 覆盖主要场景 |

**注意**: 本任务的"测试"是指验证 CI 配置，不是编写新的单元测试。

---

## 八、测试执行计划

### Phase 1: 配置创建后的即时验证

**时机**: 创建每个配置文件后立即验证

**测试清单**:
- [ ] requirements-dev.txt 可以被 pip 安装
- [ ] pytest.ini 配置被 pytest 识别
- [ ] .coveragerc 配置被 coverage 识别
- [ ] test-coverage.yml YAML 语法正确

---

### Phase 2: 本地集成测试

**时机**: 所有配置文件创建完成后，推送到 GitHub 之前

**测试清单**:
- [ ] 执行测试用例 3.1（完整测试流程）
- [ ] 执行测试用例 3.2（阈值测试）
- [ ] 执行测试用例 3.3（排除规则测试）

**通过条件**: 所有测试用例通过

---

### Phase 3: CI 集成测试

**时机**: 推送到 GitHub 后

**测试清单**:
- [ ] 执行测试用例 4.1（首次 CI 运行）
- [ ] 执行测试用例 4.2（Artifact 上传验证）
- [ ] 执行测试用例 4.3（触发条件验证）

**通过条件**: CI 成功运行，所有步骤执行完成

---

### Phase 4: 边界场景测试

**时机**: CI 验证通过后，可选的额外验证

**测试清单**:
- [ ] 执行测试用例 5.1（无代码变更）
- [ ] 执行测试用例 5.2（仅测试文件）
- [ ] 执行测试用例 5.3（未测试代码）
- [ ] 执行测试用例 5.4（完整测试代码）

**通过条件**: 各场景行为符合预期

---

## 九、失败场景与诊断

### 场景 A: pytest 无法发现测试

**症状**:
```
collected 0 items
```

**可能原因**:
1. pytest.ini 中的 `testpaths` 配置错误
2. `python_files` 模式不匹配测试文件名
3. 测试文件中没有符合命名规范的函数/类

**诊断步骤**:
```bash
pytest --collect-only -v  # 查看 pytest 尝试收集哪些文件
```

**解决方案**:
- 检查 pytest.ini 中的 `testpaths` 是否正确（应该是 `test`）
- 检查 `python_files` 是否匹配 `*_test.py`
- 确认测试文件在正确的目录

---

### 场景 B: coverage.xml 未生成

**症状**: diff-cover 报错 "No such file: coverage.xml"

**可能原因**:
1. pytest-cov 未安装
2. --cov 参数错误
3. --cov-report=xml 参数缺失

**诊断步骤**:
```bash
pip list | grep pytest-cov  # 确认已安装
pytest --cov=. --cov-report=xml -v  # 详细输出
ls -la coverage.xml  # 检查文件是否存在
```

**解决方案**:
- 安装 pytest-cov: `pip install pytest-cov`
- 确认 --cov 和 --cov-report=xml 参数都存在

---

### 场景 C: diff-cover 找不到 cap 分支

**症状**:
```
fatal: ambiguous argument 'cap': unknown revision or path not in the working tree
```

**可能原因**:
1. 本地没有 cap 分支
2. GitHub Actions 中 fetch-depth 设置错误

**诊断步骤**:
```bash
git branch -a  # 查看所有分支
git fetch origin cap  # 手动拉取 cap 分支
```

**解决方案**:
- 本地测试: 使用 `diff-cover coverage.xml --compare-branch=cap`
- GitHub Actions: 使用 `diff-cover coverage.xml --compare-branch=origin/cap`
- 确保 checkout action 使用 `fetch-depth: 0`

---

### 场景 D: CI 运行但没有触发

**症状**: 推送代码后，GitHub Actions 页面没有新的运行记录

**可能原因**:
1. workflow 文件路径错误（不在 .github/workflows/）
2. YAML 语法错误导致 workflow 被忽略
3. GitHub Actions 未启用

**诊断步骤**:
1. 检查文件路径: `.github/workflows/test-coverage.yml`
2. 在 GitHub 仓库的 Settings > Actions 检查是否启用
3. 在 Actions 页面查看是否有错误提示

**解决方案**:
- 确保文件在正确路径
- 启用 GitHub Actions
- 修正 YAML 语法错误

---

### 场景 E: CI 运行但步骤失败

**症状**: CI 运行但某个步骤显示红色 ❌

**诊断步骤**:
1. 点击失败的 workflow run
2. 展开失败的步骤，查看日志
3. 根据错误信息定位问题

**常见失败原因**:

| 失败步骤 | 可能原因 | 解决方案 |
|---------|---------|---------|
| Install dependencies | 包名错误或版本冲突 | 修正 requirements 文件 |
| Run tests | 测试代码有 bug | 修复测试 |
| Check diff coverage | 覆盖率不足 | 添加测试提升覆盖率 |

---

## 十、回归测试

每次修改 CI 配置后，应该运行以下回归测试：

### 回归测试清单
- [ ] 配置文件语法验证（测试用例 2.1, 2.2）
- [ ] 本地完整流程（测试用例 3.1）
- [ ] CI 触发验证（测试用例 4.1）
- [ ] GitHub Pages 部署验证（测试用例 4.4）
- [ ] 至少一个边界场景（测试用例 5.3 或 5.4）

---

## 十一、性能测试

### 测试用例 11.1: CI 运行时间测试

**测试目标**: 确保 CI 运行时间在可接受范围内  
**测试方法**: 观察 GitHub Actions 运行时长

**性能基准**:
- Checkout: < 30 秒（完整历史）
- Setup Python: < 30 秒（有缓存）
- Install dependencies: < 60 秒（有缓存）
- Run tests: < 300 秒（取决于测试数量）
- Check diff coverage: < 10 秒
- Upload artifacts: < 30 秒
- Create index page: < 5 秒
- Deploy to Pages: < 30 秒（仅 cap 分支）

**总计**: 
- 功能分支: < 8 分钟
- cap 分支: < 9 分钟（含 Pages 部署）

**优化建议**:
- 如果 Install dependencies 太慢，使用 pip cache（已配置）
- 如果 Checkout 太慢，考虑是否真的需要完整历史（必需）
- Pages 部署是异步的，不会阻塞 CI

---

## 十二、安全测试

### 测试用例 12.1: 敏感信息泄露检查

**测试目标**: 确保配置文件中不包含敏感信息  
**检查清单**:
- [ ] requirements-dev.txt 不包含密码或 token
- [ ] test-coverage.yml 不包含硬编码的密钥
- [ ] .coveragerc 不暴露敏感路径

**预期结果**: ✅ 所有配置文件安全

---

## 十三、兼容性测试

### 测试用例 13.1: Python 版本兼容性

**测试目标**: 验证配置在 Python 3.10 环境下正常工作  
**前置条件**: Python 3.10.x 环境

**步骤**:
```bash
python --version  # 确认版本
cd src/code/agent
pip install -r requirements-dev.txt
pytest --cov=. --cov-report=xml
diff-cover coverage.xml --compare-branch=cap
```

**预期结果**: ✅ 所有工具正常运行

---

### 测试用例 13.2: 操作系统兼容性

**测试目标**: 验证配置在不同操作系统下的兼容性

**测试环境**:
- Ubuntu (GitHub Actions 使用)
- macOS (本地开发)
- Windows (可选)

**预期结果**: 
- ✅ Ubuntu: 完全兼容
- ✅ macOS: 完全兼容
- ⚠️ Windows: 路径可能需要调整（但 CI 不受影响）

---

## 十四、测试数据

### 当前项目测试数据

**现有测试文件**: 18 个
- utils: 3 个测试文件
- services: 15 个测试文件（包括 gateway、workspace、pip 等子模块）

**测试命名模式**: `*_test.py`

**现有覆盖率**: 77%

**测试框架**: pytest + unittest.mock

---

## 十五、验收标准

任务完成的验收标准：

### 功能验收
- [x] 所有配置文件创建完成
- [x] GitHub Actions workflow 正确配置
- [ ] 本地可以运行完整测试流程
- [ ] CI 自动触发并执行
- [ ] diff-cover 正确计算差异覆盖率
- [ ] 覆盖率不足时 CI 失败
- [ ] 覆盖率达标时 CI 通过
- [ ] GitHub Pages 在 cap 分支成功部署
- [ ] 覆盖率报告可通过浏览器访问

### 质量验收
- [ ] 配置文件格式正确
- [ ] 无语法错误
- [ ] 文档完整（design.md、development.md、cases.md）
- [ ] .gitignore 正确排除覆盖率文件
- [ ] GitHub Pages 导航页面美观友好

### 用户体验验收
- [ ] 开发者可以在本地运行相同的检查
- [ ] CI 失败信息清晰，指出覆盖率不足
- [ ] Artifact 可以下载查看详细报告
- [ ] GitHub Pages 提供永久链接，无需下载即可查看
- [ ] 导航页面清晰，易于找到所需报告

---

## 十六、测试报告模板

每个测试用例执行后，记录结果：

```markdown
### 测试用例 X.X 执行记录

**执行时间**: YYYY-MM-DD HH:MM:SS  
**执行人**: cici  
**结果**: ✅ 通过 / ❌ 失败

**输出摘要**:
[命令输出或 CI 日志关键信息]

**问题**:
[如果失败，记录问题]

**解决方案**:
[如果失败，记录如何解决]
```

---

## 十七、持续监控

CI 部署后，需要持续监控：

1. **每周检查**:
   - CI 运行成功率
   - 平均运行时长
   - 差异覆盖率趋势

2. **每月检查**:
   - 依赖包更新（pytest、pytest-cov、diff-cover）
   - GitHub Actions 版本更新（checkout、setup-python 等）

3. **问题追踪**:
   - 记录 CI 失败的原因
   - 分析是否有误报（false positive）
   - 根据反馈调整阈值或配置

---

## 十八、FAQ 预设

**Q1: 为什么本地测试通过，但 CI 失败？**  
A: 可能是环境差异、依赖版本不同、或者本地没有正确配置 diff-cover。

**Q2: diff-cover 显示 "No lines with coverage information"？**  
A: 这表示当前分支相对 cap 分支没有代码变更，这是正常的。

**Q3: 如何临时绕过覆盖率检查？**  
A: 不建议绕过。如果确实需要，可以在 PR 中说明原因，或临时调整阈值。

**Q4: 如何查看详细的覆盖率报告？**  
A: 有两种方式：
   1. 访问 GitHub Pages（推荐）：https://\<username\>.github.io/\<repo\>/
   2. 下载 CI 的 artifact（coverage-report），在浏览器中打开 htmlcov/index.html

**Q5: 如何在本地运行与 CI 相同的检查？**  
A: 参考 development.md 的"本地开发体验"章节。

**Q6: GitHub Pages 多久更新一次？**  
A: 每次推送到 cap 分支时自动更新，通常在 CI 运行完成后 1-2 分钟内生效。

**Q7: 功能分支的覆盖率报告可以在 GitHub Pages 看到吗？**  
A: 不能。GitHub Pages 只部署 cap 分支的报告。功能分支的报告需要下载 Artifact 查看。

---

## 十九、测试总结

本文档定义了 20 个测试用例，覆盖：
- 配置文件验证（2 个）
- 本地集成测试（3 个）
- CI 集成测试（5 个，含 GitHub Pages 部署验证）
- 边界场景测试（5 个）
- 兼容性测试（2 个）
- 性能测试（1 个）
- 安全测试（1 个）
- 回归测试（1 个清单）

通过这些测试用例，可以全面验证 GitHub CI 覆盖率检查功能和 GitHub Pages 自动部署的正确性和可靠性。
