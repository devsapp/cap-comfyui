# PIP Installer 依赖安装优化设计文档

## 背景

CAP-ComfyUI 在启动时需要为用户配置的自定义节点（custom nodes）安装 Python 依赖。每个插件目录下可能存在：

- `requirements.txt`：声明该插件的 Python 包依赖
- `install.py`：插件自定义的安装脚本

依赖安装的核心挑战是：**在有限时间内（默认 600s），尽可能多地安装成功，同时避免重复安装和版本冲突**。

---

## 核心问题：如何又快又准地安装依赖

### 方案一：合并所有 requirements.txt，整体 pip install -r（当前方案）

**流程：**
```
扫描所有插件目录
  → 合并所有 requirements.txt（去重 + 版本冲突解决）
  → 过滤（黑名单、已安装包、git+ 依赖）
  → pip install -r merged.txt（一次性安装）
  → 逐插件执行 install.py
```

**优势：**
- 依赖树**只解析一次**，全局求最优版本，不会出现"后装的包覆盖前装的包"的问题
- pip 的 resolver 能感知全局约束，版本冲突处理最准确
- 每个包**只下载安装一次**，不存在重复安装
- 总耗时最短（pip 启动开销只有一次）

**劣势：**
- **任意一个包安装失败，整批中止**，后续所有包都没有安装机会
- 国内镜像覆盖不全（如 `openai-agents`、`tyro==0.8.5` 等新包 403 报错）时，会导致大量本可成功的包也未被安装

**适用场景：** 网络环境稳定、镜像覆盖完整的场景。

---

### 方案二：逐个插件执行 pip install -r requirements.txt

**流程：**
```
遍历每个插件
  → pip install -r nodeA/requirements.txt
  → pip install -r nodeB/requirements.txt
  → ...
```

**优势：**
- 单个插件安装失败**不影响其他插件**，容错性最好
- 实现最简单，行为与 ComfyUI-Manager 等社区工具一致

**劣势：**
- **依赖反复解析**：每次 pip 都要重新解析已安装环境，启动开销 × 插件数量
- **版本不稳定**：同一个包（如 `torch`）被多个插件声明不同版本要求时，安装结果取决于插件的安装顺序，后安装的插件可能降级或升级前一个插件依赖的包版本
- **重复安装**：多个插件共享的依赖（如 `transformers`、`diffusers`）会被反复检查和安装
- 20+ 插件场景下总耗时显著增加

**适用场景：** 对安装成功率要求高于安装速度，且插件依赖互相独立的场景。

---

### 方案三：合并所有 requirements.txt，逐行 pip install

**流程：**
```
合并所有 requirements.txt
  → 逐行 pip install <pkg>
  → 单包失败时跳过，继续安装下一个
```

**优势：**
- 单包失败可以直接跳过，不影响其他包

**劣势：**
- **依赖反复解析问题最严重**：每次 `pip install <pkg>` 都会触发完整的依赖解析和环境 metadata 检查
- **版本不稳定**：与方案二相同，最终版本受安装顺序影响
- **时间复杂度最差**：N 个包的场景下，总 pip 解析工作量为 O(N²)
- pip 的 resolver 设计用于批量输入，逐包调用会绕过全局最优解析

**适用场景：** 不推荐在生产环境使用。

---

### 三方案横向对比

| 维度 | 方案一（合并整体安装）| 方案二（逐插件安装） | 方案三（合并逐行安装）|
|------|---------------------|-------------------|---------------------|
| 依赖解析次数 | **1 次** | 插件数量次 | 包数量次 |
| 版本一致性 | **最好**（全局最优） | 差（顺序相关） | 差（顺序相关） |
| 单包失败影响 | **整批中止** | 仅当前插件 | **仅当前包** |
| 重复安装 | **无** | 有 | 最严重 |
| 总耗时 | **最短** | 较长 | 最长 |
| 实现复杂度 | 中（需合并逻辑） | 低 | 低 |

---

## 当前方案（方案一）的补充优化

### 问题一：部分包因镜像覆盖不全导致 403 中止

**根因：** 国内镜像（aliyun、tsinghua、ustc）存在同步延迟，新版本包（如 `openai-agents 0.10.3`、`tyro==0.8.5`）可能在索引（`/simple/` 页面）中可见，但实际 wheel 文件未同步，下载时返回 403。pip 遍历所有 extra-index-url 均失败后中止整批安装。

**解法：精简源配置为 aliyun 主源 + PyPI 官方兜底**

修改 `pip.conf` 或在安装命令中注入：

```ini
[global]
index-url = https://mirrors.aliyun.com/pypi/simple/
extra-index-url = https://pypi.org/simple/
```

去掉 tsinghua 和 ustc，只保留 aliyun 和 PyPI 两个源，行为更可预测：aliyun 有的包走 aliyun，没有的自动走 PyPI。

**效果：**
- 常见包：走国内 aliyun 镜像，速度快
- 镜像未同步的新包：自动降级到 PyPI 官方源，速度略慢但可成功
- 整批安装仍只跑一次，无额外重装开销

---

### 问题二：pip 多源配置不能保证"有一个源可用就能成功"

**根因：** pip 的多源机制设计目标是**加速**（并发查询取最快响应），而不是**最大化成功率**（穷举所有可能）。其实际行为如下：

1. **并发查询**所有源的索引（`/simple/<pkg>/`），哪个响应快就以哪个为准
2. 以"响应最快的源"作为该包的权威下载源
3. 下载失败后，只在**具有相同 wheel hash** 的其他源之间 fallback
4. **不会**重新让其他源参与版本选择，即使其他源可以正常下载

**典型失败场景：**

```
aliyun   有 tyro==0.8.5，可正常下载  ← 未被尝试
ustc     有 tyro==0.8.5 的索引，wheel 文件 403  ← 被选中（响应最快）
tsinghua 有 tyro==0.8.5 的索引，wheel 文件 403  ← fallback 失败
PyPI     有 tyro==0.8.5，可正常下载  ← 未被尝试

结果：pip 报错，尽管 aliyun 和 PyPI 均可用
```

**根本限制：** 这是 pip 的架构设计，无法通过配置完全规避。多源不等于高可用，源越多反而可能因为"选错源"而降低成功率。

**缓解措施：**
- 精简源数量（如问题一的方案），减少"选错源"概率
- 对已知 403 的包加入黑名单跳过，或在环境准备阶段提前预装
- 接受极少数新包无法自动安装的现状，通过运维手段（镜像预热、手动补装）处理

---

### 问题三：单包安装失败导致整批中止（已规划）

**根因：** `pip install -r` 的默认行为是 fail-fast：任意一个包安装失败，立即中止，后续所有包都无法安装。在镜像覆盖不全的环境下，极少数新包的 403 会导致大量本可成功安装的包被连带跳过。

**解法：在方案一基础上增加"解析 stderr → 剔除失败包 → 有限次重试"机制**

核心思路是保留方案一的整体 `pip install -r`（充分利用 resolver，避免重装），但在失败时自动剔除问题包并重试，而不是彻底放弃本轮安装。

**疑难依赖（problematic_deps）概念**

引入"疑难依赖"统一收口所有无法自动安装的包，来源包括两类：

| 来源 | 说明 |
|------|------|
| 黑名单命中 | 在 `_filter_merged_dependencies` 阶段被主动过滤掉的包（如与 ComfyUI 核心依赖冲突的包） |
| 安装失败 | pip install 重试耗尽后仍未能安装成功的包 |

所有疑难依赖在安装流程结束后，以 `requirements.txt` 格式统一打印到日志，供用户复制后手动安装：

```
[Installer] ## ========== Problematic Dependencies ==========
[Installer] ## The following packages could not be installed automatically.
[Installer] ## You can copy and install them manually:
[Installer] ##
[Installer] ##   tyro==0.8.5
[Installer] ##   openai-agents>=0.2.2
[Installer] ##   torch                   # blacklisted
[Installer] ## ===============================================
```

**流程设计：**

```
准备 requirements 内容（合并后）
  │
  ├─ _filter_merged_dependencies()
  │    ├─ 黑名单命中的包 ──────────────→ 加入 problematic_deps（标注来源：blacklist）
  │    ├─ git+ 依赖跳过 ──────────────→ 加入 problematic_deps（标注来源：git+，需手动安装）
  │    └─ 已安装且无版本约束 → 跳过（正常，不加入 problematic_deps）
  │
  ▼
┌─────────────────────────────────────────────┐
│  pip install -r <tmpfile>                   │
│  ├─ 成功（returncode == 0）→ 结束，全部装完   │
│  └─ 失败（returncode != 0）                 │
│       ├─ 解析 stderr，提取失败包名           │
│       ├─ 从 requirements 内容中剔除失败包    │
│       ├─ 失败包加入 problematic_deps         │
│       │    （标注来源：install_failed）      │
│       └─ 检查退出条件 ──────────────────────┤
│            ├─ 已重试 >= MAX_RETRIES 次 → 退出│
│            ├─ 剩余时间 < 阈值 → 退出         │
│            └─ 未提取到新的失败包 → 退出       │
│                 （防止同一包反复失败死循环）  │
└─────────────────────────────────────────────┘
  │
  ▼
打印 problematic_deps（requirements.txt 格式，供用户手动安装）
  │
  ▼
返回结果（含 problematic_deps 列表）
```

**关键参数：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `MAX_RETRIES` | 5 | 最大重试轮数上限，防止无限循环 |
| 超时检查 | 每轮重试前检查 | 若已用时超过 `install_all` 的总超时，不再重试 |

**stderr 解析正则：**

```python
# pip 错误输出格式固定：
# ERROR: Could not install requirement <pkg_spec> from ...
failed = re.findall(r'Could not install requirement ([^\s]+)', stderr)
```

**复杂度分析：**

理论上最坏情况为 O(N²)，但实际远好于此，原因是：
- 已成功安装的包命中 pip 的本地缓存（metadata check 极快，不重新下载）
- 每轮重试的 requirements 内容比上一轮更少（剔除了失败包）
- 触发重试的场景仅限于极少数镜像覆盖不全的包（通常 ≤ 5 个），而非普遍现象
- 实际表现接近 O(N + K²)，其中 K 为失败包数量（K << N）

**与纯逐行安装的对比：**

| 维度 | 逐行安装 | 有限次重试（本方案） |
|------|---------|-------------------|
| 依赖解析 | 每包独立解析，版本顺序相关 | 每轮仍为整体解析，版本全局最优 |
| 重装风险 | 高（每次 pip 重评估已装包） | 低（已装包命中缓存，不重装） |
| 失败容错 | 高（单包失败跳过） | 高（失败包被剔除后继续） |
| 疑难依赖可见性 | 无（失败散落在各插件日志中） | **统一汇总，格式化输出供手动安装** |
| 实现复杂度 | 低 | 中（需解析 stderr） |

---

### 问题四：stderr 解析的传递依赖盲区

**根因：** `_install_merged_dependencies` 用正则 `Could not install requirement (\S+)` 从 stderr 中提取失败包名，再从 `current_deps`（即 merged.txt 的直接依赖字典）中查找并剔除。但 pip 报告的失败包有时是**传递依赖**（依赖的依赖），它不在 merged.txt 里，因此在 `current_deps` 中找不到，`newly_removed` 为空，被误判为"同一个包反复失败→死循环"，提前 break，导致后续本可成功安装的包也被放弃。

**两类真实 stderr 样本：**

```
# 样本1：直接依赖失败（aisuite[all] 本身就在 merged.txt 里，正常可处理）
ERROR: Could not install requirement aisuite[all] from https://mirrors.ustc.edu.cn/...
(from -r /tmp/tmpl05gkzud.txt (line 6)) because of HTTP error 403

# 样本2：传递依赖失败（caio 不在 merged.txt，是 fastmcp 的子子依赖）
ERROR: Could not install requirement caio<0.10.0,>=0.9.0 from https://mirrors.ustc.edu.cn/...
(from aiofile>=3.5.0->py-key-value-aio[filetree,keyring,memory]<0.5.0,>=0.4.4->fastmcp->-r /tmp/tmpc7uczj4b.txt (line 32))
because of HTTP error 403
```

pip 在 `from` 链中完整记录了依赖路径，格式为：

```
(from 直接父->祖父->...->MERGED_TXT_DIRECT_DEP->-r /tmp/requirements.txt (line N))
```

**解法：从 from chain 反查直接父包**

当 `newly_removed` 为空（所有失败包均为传递依赖）时，解析 stderr 中每条错误行的 from 链，提取 `->-r` 之前的最后一个包名，即 merged.txt 里的直接依赖，将其剔除后继续重试：

```python
# 从 pip from chain 提取直接父包
# 格式：(from A->B->DIRECT->-r file (line N))
# DIRECT 为 ->-r 之前的最后一项，即 merged.txt 的直接依赖
for m in re.finditer(r'\(from\s+(.+?)\(line\s+\d+\)\)', stderr):
    chain = m.group(1).strip()      # "A->B->DIRECT->-r /tmp/file.txt "
    parts = chain.split('->')       # 按 -> 分割（-> 不是合法版本操作符，分割安全）
    for i, part in enumerate(parts):
        if part.strip().startswith('-r ') and i > 0:
            direct_spec = parts[i - 1].strip()  # "DIRECT"（可能含版本约束或 extras）
            pkg_name, _ = _parse_package_spec(direct_spec)
            if pkg_name in current_deps:
                # 剔除这个直接依赖，加入 problematic_deps，然后重试
                ...
```

**为什么 `->` 分割是安全的：**

pip 依赖链中 `->` 作为分隔符，永远是 `-` 和 `>` 的连续组合。版本操作符 `>=`、`<=`、`>`、`<` 中的 `>` 前面没有 `-`，不会与 `->` 混淆。包名本身可含 `-`（如 `py-key-value-aio`）但不含 `>`，因此 `.split('->')` 能正确切分每段包规范。

**更新后的防死循环判断：**

| 情况 | 处理 |
|------|------|
| `failed_specs` 中有包在 `current_deps` → 直接依赖失败 | 原有逻辑：剔除并重试 |
| `failed_specs` 全为传递依赖 + from chain 可追溯到直接父包 | 新增逻辑：剔除直接父包并重试 |
| `failed_specs` 全为传递依赖 + from chain 无法追溯（格式异常）或直接父包已在上轮剔除 | 退出（真正的死循环） |

---

### 问题：包名合并时的规范化 Bug

合并多个插件的 requirements.txt 时，以下情况会导致**同一个包被重复记录为不同条目**：

| Bug 类型 | 示例 | 根因 |
|---------|------|------|
| 大小写不一致 | `Requests` vs `requests>=2.25.0` | 字典 key 区分大小写 |
| 连字符/下划线混用 | `scikit-image` vs `scikit_image` | pip 遵循 PEP 503 视为等价，代码未规范化 |
| 版本号前有空格 | `accelerate>=1.10` vs `accelerate >= 1.2.1` | 正则不支持操作符前的空格，解析失败 |

**修复方案（已实施）：** 在 `_parse_package_spec` 中对包名统一做 PEP 503 规范化：

```python
# 修复1：正则支持操作符前空格
version_pattern = r'^([a-zA-Z0-9._-]+)\s*((?:[><=!]+).*)?$'

# 修复2：包名规范化（小写 + 连字符统一）
normalized_name = re.sub(r'[-_.]+', '-', raw_name).lower()
```

同步修复 `_try_get_installed_packages`，使已安装包的 key 与规范化后的包名格式一致，确保"已安装且无版本约束则跳过"的过滤逻辑正确工作。

---

## 开源工具评估

### pip-compile（pip-tools）

**能力：** 接受多个 requirements.txt 输入，用 SAT-solver 全局解析，输出精确锁定版本的合并文件（注明每个包来自哪个插件）。

**不适用原因：**
- 设计目标是**从零构建可复现环境**，而非在已有环境上增量安装
- 已安装且无版本约束的包（如环境中已有 `torch==2.9.0`）会被解析为 PyPI 最新版（如 `torch==2.10.0`），触发不必要的大包重装
- 无内置的黑名单过滤、已安装包跳过等定制化能力

### uv

**能力：** pip 的 Rust 实现替代品，速度快 10-100x，`uv pip compile` 支持多文件合并。

**不适用原因：**
- **不读取 `pip.conf`**（设计决策），需单独维护 `uv.toml` 配置，国内源需重新配置
- 同样存在已安装包重装问题（与 pip-compile 同理）
- 仅 CLI 接口，无 Python API，调用方式为 subprocess，与现有方案差异小
- 引入后需维护两套源配置（pip.conf + uv.toml），增加运维成本

**结论：** 上述工具均无法替代当前的定制化合并逻辑（已安装包过滤、黑名单、版本冲突自定义策略、nunchaku 等特殊节点处理）。

---

## ComfyUI 核心依赖保护

### 问题

插件的 requirements.txt 可能声明与 ComfyUI 核心依赖冲突的版本（如降级 `torch`、`transformers` 等），导致 ComfyUI 自身运行异常。

### 解法：安装完成后重新固定核心依赖

在所有插件依赖安装完成后，**最后再安装一遍 ComfyUI 核心依赖**，确保核心版本不被插件覆盖：

```
Step 1: 合并插件 requirements.txt → 安装插件依赖（允许版本升降）
Step 2: 逐插件执行 install.py
Step 3: pip install -r comfyui/requirements.txt  ← 最后固定核心依赖
```

**原理：** pip 在 Step 3 中发现核心依赖版本已被插件修改时，会将其还原到 ComfyUI 要求的版本。该步骤耗时短（核心依赖数量少），且保证了 ComfyUI 主进程的依赖环境始终处于已知可用状态。

---

## 当前实现架构

```
PIPInstaller.install_all()
  ├─ Step 0: _determine_nodes_to_install()
  │    └─ 根据 nodes_map 确定要安装的节点列表
  │
  ├─ Step 1: _merge_requirements_from_nodes()
  │    ├─ _merge_requirements_file()         逐文件合并，版本冲突解决
  │    ├─ _filter_merged_dependencies()      黑名单 / 已安装 / git+ 过滤
  │    ├─ _apply_custom_dependency_strategies()  定制化策略（nunchaku 等）
  │    └─ _generate_requirements_content()   输出最终 requirements.txt 内容
  │
  ├─ Step 2: _install_merged_dependencies()
  │    └─ pip install -r <tmpfile>（整体安装，带超时）
  │
  └─ Step 3: _execute_install_scripts()
       └─ 逐插件执行 install.py
```

### 返回数据结构

```python
{
    "baseline": {"torch": "2.9.0", ...},   # 安装前已有包基线（包名 → 版本）
    "dependencies": {                       # Step 2 结果
        "requirements_txt": "...",          # 实际安装的内容
        "duration": 45.2,
        "success": True,
        "error_msg": ""
    },
    "scripts": [                            # Step 3 结果列表
        {
            "node_name": "ComfyUI-Impact-Pack",
            "script_name": "install.py",
            "duration": 1.2,
            "success": True,
            "error_msg": ""
        },
        ...
    ]
}
```
