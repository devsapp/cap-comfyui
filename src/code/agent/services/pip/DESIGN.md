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

> **当前采用方案：** 在方案一基础上引入两轮批次安装（见"问题三"），以 `BATCH_SIZE=10` 分批，牺牲少量版本全局最优性，换取对单包失败的容错能力，同时避免逐行安装的极高 pip 启动开销。

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

### 问题三：单包安装失败导致整批中止

**根因：** `pip install -r` 的默认行为是 fail-fast：任意一个包安装失败，立即中止，后续所有包都无法安装。在镜像覆盖不全的环境下，极少数新包的 403 会导致大量本可成功安装的包被连带跳过。

**解法：两轮批次安装**

核心思路：将合并后的全量依赖按固定批次大小分批安装（第一轮），再将所有失败批次的依赖汇总、逐个重装（第二轮）。两轮均直接通过 `returncode` 感知成功与失败，无需解析 stderr，实现简单且行为可预测。

**疑难依赖（problematic_deps）概念**

引入"疑难依赖"统一收口所有无法自动安装的包，来源包括两类：

| 来源 | 说明 |
|------|------|
| 黑名单命中 | 在 `_filter_merged_dependencies` 阶段被主动过滤掉的包（如与 ComfyUI 核心依赖冲突的包） |
| 安装失败 | 第二轮逐个安装后仍失败的包 |

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
准备 requirements 内容（合并后，共 N 个依赖）
  │
  ├─ _filter_merged_dependencies()
  │    ├─ 黑名单命中 ──────────────→ 加入 problematic_deps（标注：blacklist）
  │    ├─ git+ 依赖 ───────────────→ 加入 problematic_deps（标注：git+，需手动安装）
  │    └─ 已安装且无版本约束 → 跳过（不加入 problematic_deps）
  │
  ▼
【第一轮：分批安装】
将依赖列表按 BATCH_SIZE（默认 10）切分为 ceil(N/10) 个批次
  │
  for each batch [dep₁, dep₂, ..., dep₁₀]:
    pip install dep₁ dep₂ ... dep₁₀
    ├─ 成功（returncode == 0）→ 该批完成，继续下一批
    └─ 失败（returncode != 0）→ 整批记入 failed_batches，继续下一批
  │
  ▼
【第二轮：逐个安装失败依赖】
将 failed_batches 中所有依赖展开并去重，得到 failed_deps
  │
  for each dep in failed_deps:
    pip install <dep>
    ├─ 成功（returncode == 0）→ 完成
    └─ 失败（returncode != 0）→ 加入 problematic_deps（标注：install_failed）
  │
  ▼
打印 problematic_deps（requirements.txt 格式，供用户手动安装）
  │
  ▼
返回结果（含 problematic_deps 列表）
```

**批次大小选择（BATCH_SIZE = 10）：**

| 批次大小 | pip 启动次数 | 单批失败波及范围 | 第二轮兜底工作量 |
|---------|------------|----------------|----------------|
| 1（逐个） | N 次 | 仅 1 个包 | 无需第二轮 |
| **10（当前）** | **ceil(N/10) 次** | **最多 10 个包** | **较小** |
| 全量（N） | 1 次 | 全部中止 | 等同逐个安装全量 |

选择 10 是在 pip 启动开销与失败隔离之间取得平衡的经验值：既不像全量安装那样"一粒老鼠屎坏一锅粥"，也不像逐包安装那样重复启动开销过高。

**版本一致性说明：**

两轮批次安装中每批独立运行 pip resolver，批内版本全局最优，但批间存在版本覆盖的可能（与方案二的逐插件安装相同）。这是在稳定性与速度之间的有意权衡：

- 大部分插件的依赖不存在深度版本交叉，批次隔离不影响结果
- 对于确实存在跨批版本约束的依赖，最终安装的版本仍满足各自批次内的约束
- 极端情况下（如 A 批安装了 `torch==2.4`，B 批要求 `torch>=2.5`），后一批会触发升级，pip 会正确处理

**与其他方案对比：**

| 维度 | 整体安装（方案一）| 两轮批次安装（当前方案）| 逐个安装（方案三）|
|------|-----------------|----------------------|----------------|
| pip 启动次数 | 1 次 | ceil(N/10) + 失败数 | N 次 |
| 版本全局最优 | 是 | 批内最优，批间可能覆盖 | 否（顺序相关）|
| 单包失败波及 | 整批中止 | 最多 10 个连带 | 仅当前包 |
| 失败感知方式 | 需解析 stderr | **直接通过 returncode** | 直接通过 returncode |
| 实现复杂度 | 高（stderr 解析 + 重试） | **低** | 低 |
| 疑难依赖可见性 | 需解析 stderr 反查 | **第二轮直接确认** | 分散在各包日志中 |

---

### 问题四：弃用基于 stderr 解析的重试机制

早期设计（见下方存档）曾计划在整体安装失败后，通过解析 pip stderr 提取失败包名、剔除后重试，最多重试 `MAX_RETRIES` 次。该方案在实际落地时遇到以下根本性困难，最终弃用：

**困难一：传递依赖盲区**

pip 报告的失败包有时是**传递依赖**（依赖的依赖），它不在 `merged.txt` 里。正则 `Could not install requirement (\S+)` 提取到的包名在 `current_deps` 中找不到，`newly_removed` 为空，触发"防死循环"提前 break，导致后续本可成功安装的包一并放弃。

典型样本：

```
# 直接依赖：aisuite[all] 在 merged.txt 中，正则可处理
ERROR: Could not install requirement aisuite[all] from https://mirrors.ustc.edu.cn/...

# 传递依赖：caio 不在 merged.txt，是 fastmcp 的子子依赖，正则无法追溯
ERROR: Could not install requirement caio<0.10.0,>=0.9.0 from https://mirrors.ustc.edu.cn/...
(from aiofile>=3.5.0->py-key-value-aio[...]->fastmcp->-r /tmp/file.txt (line 32))
```

虽然可以进一步解析 from chain 反查直接父包，但这引入了更多正则和边界情况，维护成本高。

**困难二：重试中的重装开销**

每轮重试时，已成功安装的包仍需重新被 pip resolver 评估（metadata check），即使命中缓存速度较快，也随重试轮数累积，最坏复杂度为 O(N²)。

**为何两轮批次安装更优：**

- 第一轮批次失败直接通过 `returncode` 感知，无需解析任何文本
- 第二轮逐个安装能精确定位具体失败包，同样无需 stderr
- 失败影响范围天然被 `BATCH_SIZE` 限制，无需防死循环判断
- 代码路径简单，行为对 stderr 格式变化免疫（pip 版本升级不会影响逻辑）

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
  │    ├─ _merge_requirements_file()              逐文件合并，版本冲突解决
  │    ├─ _filter_merged_dependencies()           黑名单 / 已安装 / git+ 过滤
  │    │    └─ 黑名单 / git+ 包 → problematic_deps
  │    ├─ _apply_custom_dependency_strategies()   定制化策略（nunchaku 等）
  │    └─ _generate_requirements_content()        输出最终依赖列表
  │
  ├─ Step 2: _install_merged_dependencies()       两轮批次安装
  │    ├─ 第一轮：按 BATCH_SIZE=10 分批
  │    │    ├─ pip install dep₁ ... dep₁₀  → 成功，继续
  │    │    ├─ pip install dep₁₁ ... dep₂₀ → 失败，记入 failed_batches
  │    │    └─ ...（共 ceil(N/10) 批）
  │    └─ 第二轮：逐个安装所有 failed_batches 中的依赖
  │         ├─ pip install <dep> → 成功
  │         └─ pip install <dep> → 失败 → 加入 problematic_deps
  │
  └─ Step 3: _execute_install_scripts()
       └─ 逐插件执行 install.py
```

### 返回数据结构

```python
{
    "baseline": {"torch": "2.9.0", ...},   # 安装前已有包基线（包名 → 版本）
    "dependencies": {                       # Step 2 结果
        "requirements_txt": "...",          # 实际安装的内容（过滤后）
        "duration": 45.2,
        "success": True,
        "problematic_deps": [               # 无法自动安装的包（黑名单 + 安装失败）
            {"spec": "tyro==0.8.5",         # 原始规范字符串
             "reason": "install_failed"},   # blacklist / git+ / install_failed
            {"spec": "torch",
             "reason": "blacklist"},
        ]
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
