import os
import subprocess
import time
import re
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass, asdict

import constants
from utils import file_ops


@dataclass
class InstallRecord:
    node_name: str
    package_name: str
    duration: float = 0  # 耗时(秒)
    success: bool = True
    error_msg: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class DependencyInfo:
    """依赖包信息"""
    package_name: str  # 基础包名（不含版本）
    version_spec: str  # 版本规范（如 ==1.0.0, >=1.5.0）
    original_line: str  # 原始行内容
    source_nodes: List[str]  # 来源插件列表


class PIPInstallerOptimized:
    """优化版本的 PIP 安装器，支持依赖合并、过滤和批量安装"""
    
    def __init__(self, blacklist: Optional[List[str]] = None):
        """
        初始化优化版安装器
        
        Args:
            blacklist: 黑名单包列表，这些包将被跳过安装
        """
        self.processed_install = set()
        self._history = []
        self._origin_packages = self._try_get_installed_packages()
        self.blacklist = set(blacklist) if blacklist else set()
        
        # 用于合并依赖的数据结构
        self._merged_dependencies: Dict[str, DependencyInfo] = {}
        
    def get_origin_packages(self):
        return self._origin_packages

    def install_all(self, soft_timeout=300, nodes_map=None):
        """
        安装流程：先合并所有插件requirements.txt，再批量安装，最后逐个插件执行 install.py
        
        Args:
            soft_timeout: 软超时时间（秒），逐个pip install requirements.txt中的依赖时，若超时，则会在安装完当前依赖后退出
            nodes_map: 节点映射，控制安装行为
        """
        nodes_path = os.path.join(constants.COMFYUI_DIR, "custom_nodes")
        all_available_nodes = self._get_possible_nodes(nodes_path)

        # --- 确定要安装的节点列表 ---
        nodes_to_install = self._determine_nodes_to_install(all_available_nodes, nodes_map)
        
        if not nodes_to_install:
            print("\n[Installer] No nodes to install. Skipping.")
            return self._history

        print(f"\n[Installer] Starting installation for {len(nodes_to_install)} nodes...")
        start_time = time.time()

        try:
            # 步骤1: 合并所有 requirements.txt
            self._merge_requirements_from_nodes(nodes_to_install, soft_timeout, start_time)
            
            # 步骤2: 过滤并批量安装依赖包
            self._install_merged_dependencies(soft_timeout, start_time)
            
            # 步骤3: 执行各插件的 install.py 脚本
            self._execute_install_scripts(nodes_to_install, soft_timeout, start_time)
            
        except TimeoutError as e:
            print(f"\n[Installer] {e}")
        
        total_duration = time.time() - start_time
        print(f"\n[Installer] Installation completed. Total time: {total_duration:.1f}s")
        print(f"[Installer] Total operations: {len(self._history)}")
        
        return self._history

    def _determine_nodes_to_install(self, all_available_nodes: List[str], nodes_map) -> List[str]:
        """
        确定要安装的节点列表
        安装行为由 nodes_map 控制:
        - None: 安装环境中所有可用的节点。
        - 空字典: 不安装任何节点。
        - 非空字典: 只安装字典中指定的有效节点。
        """
        if nodes_map is None:
            # 场景1: 安装所有节点
            nodes_to_install = sorted(all_available_nodes)
            print(f"\n[Installer] Preparing to install all {len(nodes_to_install)} available nodes.")
        else:
            # 场景2: 安装指定节点
            requested_nodes = set(nodes_map.keys())
            available_nodes_set = set(all_available_nodes)

            nodes_to_install = sorted(list(requested_nodes & available_nodes_set))
            invalid_nodes = sorted(list(requested_nodes - available_nodes_set))

            if invalid_nodes:
                print(f"\n[Installer] Warning: Skipping {len(invalid_nodes)} invalid nodes: {', '.join(invalid_nodes)}")

            if nodes_to_install:
                print(f"\n[Installer] Found {len(nodes_to_install)} valid nodes to install: {', '.join(nodes_to_install)}")

        return nodes_to_install

    def _merge_requirements_from_nodes(self, nodes_to_install: List[str], soft_timeout: float, start_time: float):
        """步骤1: 遍历并合并所有节点的 requirements.txt"""
        print(f"\n[Installer] ## Step 1: Merging requirements.txt from {len(nodes_to_install)} nodes...")
        
        self._merged_dependencies = {}
        
        for node_name in nodes_to_install:
            if time.time() - start_time >= soft_timeout:
                raise TimeoutError(f"Soft timeout ({soft_timeout}s) reached during requirements merging")
                
            node_path = os.path.join(constants.COMFYUI_DIR, "custom_nodes", node_name)
            requirements_path = os.path.join(node_path, "requirements.txt")
            
            if os.path.exists(requirements_path):
                self._merge_requirements_file(requirements_path, node_name)
        
        print(f"[Installer] ## Merged {len(self._merged_dependencies)} unique dependencies from requirements.txt files")

    def _merge_requirements_file(self, requirements_path: str, node_name: str):
        """合并单个 requirements.txt 文件"""
        lines = file_ops.robust_readlines(requirements_path)
        
        for line in lines:
            package_spec = self._extract_package_name(line)
            if not package_spec:
                continue
                
            # 解析包名和版本规范
            base_name, version_spec = self._parse_package_spec(package_spec)
            
            if base_name in self._merged_dependencies:
                # 处理版本冲突
                existing_dep = self._merged_dependencies[base_name]
                resolved_version = self._resolve_version_conflict(
                    existing_dep.version_spec, version_spec, base_name
                )
                existing_dep.version_spec = resolved_version
                existing_dep.source_nodes.append(node_name)
            else:
                # 新依赖
                self._merged_dependencies[base_name] = DependencyInfo(
                    package_name=base_name,
                    version_spec=version_spec,
                    original_line=package_spec,
                    source_nodes=[node_name]
                )

    def _install_merged_dependencies(self, soft_timeout: float, start_time: float):
        """步骤2: 过滤并批量安装合并后的依赖"""
        print(f"\n[Installer] ## Step 2: Filtering and installing merged dependencies...")
        
        # 过滤依赖
        filtered_deps = self._filter_dependencies()
        
        if not filtered_deps:
            print("[Installer] ## No dependencies to install after filtering.")
            return
        
        # 打印过滤后的依赖信息，以 requirements.txt 样式
        self._print_filtered_dependencies_as_requirements(filtered_deps)
            
        print(f"[Installer] ## Installing {len(filtered_deps)} filtered dependencies...")
        
        for i, (base_name, dep_info) in enumerate(filtered_deps.items(), 1):
            if time.time() - start_time >= soft_timeout:
                raise TimeoutError(f"Soft timeout ({soft_timeout}s) reached during dependency installation")
            
            package_to_install = f"{base_name}{dep_info.version_spec}" if dep_info.version_spec else base_name
            print(f"[Installer] ## Installing dependency {i}/{len(filtered_deps)}: {package_to_install}")
            
            # 执行安装
            install_cmd = self._construct_pip_cmd(["install", package_to_install])
            self._do_install_dependency(dep_info.source_nodes, package_to_install, install_cmd)

    def _execute_install_scripts(self, nodes_to_install: List[str], soft_timeout: float, start_time: float):
        """步骤3: 执行各插件的 install.py 脚本"""
        print(f"\n[Installer] ## Step 3: Executing install.py scripts...")
        
        install_scripts_found = 0
        for node_name in nodes_to_install:
            if time.time() - start_time >= soft_timeout:
                raise TimeoutError(f"Soft timeout ({soft_timeout}s) reached during install.py execution")
                
            node_path = os.path.join(constants.COMFYUI_DIR, "custom_nodes", node_name)
            install_script_path = os.path.join(node_path, "install.py")
            
            if os.path.exists(install_script_path):
                install_scripts_found += 1
                print(f"[Installer] ## Executing install.py for node: {node_name}")
                install_cmd = [constants.VENV_EXECUTABLE, "install.py"]
                self._do_install_script(node_path, node_name, "install.py", install_cmd)
        
        print(f"[Installer] ## Executed {install_scripts_found} install.py scripts")

    def _filter_dependencies(self) -> Dict[str, DependencyInfo]:
        """过滤合并后的依赖列表"""
        filtered = {}
        
        skipped_already_installed = []
        skipped_blacklisted = []
        skipped_git_dependencies = []
        
        for base_name, dep_info in self._merged_dependencies.items():
            # 过滤掉所有 git+ 形式的依赖
            if base_name.startswith(('git+', 'hg+', 'svn+', 'bzr+')):
                skipped_git_dependencies.append(base_name)
                continue
                
            # 检查黑名单
            if base_name.lower() in {pkg.lower() for pkg in self.blacklist}:
                skipped_blacklisted.append(base_name)
                continue
                
            # 检查是否已安装
            # 只跳过无版本要求且已安装的包
            # 如果有版本要求，则交给pip处理版本升级/降级
            if base_name in self._origin_packages and not dep_info.version_spec:
                # 包已安装且无特定版本要求，跳过安装
                skipped_already_installed.append(f"{base_name} ")
                continue
                
            filtered[base_name] = dep_info
        
        # 打印过滤结果
        if skipped_already_installed:
            print(f"[Installer] ## Skipped {len(skipped_already_installed)} already installed packages: {', '.join(skipped_already_installed)}")
            
        if skipped_blacklisted:
            print(f"[Installer] ## Skipped {len(skipped_blacklisted)} blacklisted packages: {', '.join(skipped_blacklisted)}")
            
        if skipped_git_dependencies:
            print(f"[Installer] ## Skipped {len(skipped_git_dependencies)} git+ dependencies (need install manually):")
            for git_dep in skipped_git_dependencies:
                print(f"[Installer] ##   - {git_dep}")
        
        return filtered

    def _print_filtered_dependencies_as_requirements(self, filtered_deps: Dict[str, DependencyInfo]):
        """以 requirements.txt 格式打印过滤后的依赖信息"""
        print("[Installer] ## Filtered dependencies (requirements.txt format):")
        print("[Installer] ## " + "=" * 60)
        
        if not filtered_deps:
            print("[Installer] ## # No dependencies to install")
            print("[Installer] ## " + "=" * 60)
            return
        
        # 按包名排序
        sorted_deps = sorted(filtered_deps.items())
        
        for base_name, dep_info in sorted_deps:
            # 构建 requirements.txt 格式的行
            package_line = f"{base_name}{dep_info.version_spec}" if dep_info.version_spec else base_name
            
            # 添加来源节点注释
            if len(dep_info.source_nodes) == 1:
                comment = f"  # required by {dep_info.source_nodes[0]}"
            else:
                # 如果来源节点太多，只显示前几个
                if len(dep_info.source_nodes) <= 3:
                    nodes_str = ", ".join(dep_info.source_nodes)
                else:
                    nodes_str = ", ".join(dep_info.source_nodes[:3]) + f" and {len(dep_info.source_nodes) - 3} more"
                comment = f"  # required by {nodes_str}"
            
            print(f"[Installer] ## {package_line}{comment}")
        
        print("[Installer] ## " + "=" * 60)
        print(f"[Installer] ## Total: {len(filtered_deps)} packages to install")
        print("")

    def _parse_package_spec(self, package_spec: str) -> Tuple[str, str]:
        """
        解析包规范，提取包名和版本约束
        
        Args:
            package_spec: 如 "torch>=1.0.0", "requests==2.28.0", "numpy", "git+https://github.com/user/repo.git"
            
        Returns:
            Tuple[基础包名, 版本规范]
        """
        package_spec = package_spec.strip()
        
        # 处理 git+ 依赖：直接使用完整 URL 作为包名，版本规范为空
        if package_spec.startswith(('git+', 'hg+', 'svn+', 'bzr+')):
            return package_spec, ""
        
        # 处理普通包依赖
        version_pattern = r'^([a-zA-Z0-9._-]+)((?:[><=!]+).*)?$'
        match = re.match(version_pattern, package_spec)
        
        if match:
            base_name = match.group(1)
            version_spec = match.group(2) if match.group(2) else ""
            return base_name, version_spec
        else:
            # 如果无法解析，返回原始规范
            return package_spec, ""

    def _resolve_version_conflict(self, existing_spec: str, new_spec: str, package_name: str) -> str:
        """
        解决版本冲突，使用智能策略处理各种冲突情况
        
        Args:
            existing_spec: 现有版本规范
            new_spec: 新版本规范
            package_name: 包名（用于日志）
            
        Returns:
            解决后的版本规范
        """
        # 边界情况处理
        if not existing_spec:
            return new_spec
        if not new_spec:
            return existing_spec
        if existing_spec == new_spec:
            return existing_spec
            
        # 解析两个版本规范
        existing_parsed = self._parse_version_constraint(existing_spec)
        new_parsed = self._parse_version_constraint(new_spec)
        
        # 应用冲突解决策略
        resolved_spec = self._apply_conflict_resolution_strategy(
            existing_parsed, new_parsed, existing_spec, new_spec, package_name
        )
        
        # 简化为一行冲突日志
        print(f"[Installer] ## Version conflict for {package_name}: '{existing_spec}' vs '{new_spec}' -> '{resolved_spec}'")
        return resolved_spec

    def _do_install_dependency(self, source_nodes: List[str], package_name: str, install_cmd: List[str]):
        """执行依赖安装并记录结果"""
        start_time = time.time()
        record = InstallRecord(
            node_name=f"[{','.join(source_nodes[:3])}{'...' if len(source_nodes) > 3 else ''}]",  # 限制显示的节点数量
            package_name=package_name,
        )

        try:
            record.success = self._install_script("", install_cmd)  # 依赖安装不需要特定目录
        except Exception as e:
            record.error_msg = str(e)
            record.success = False
        finally:
            record.duration = round(time.time() - start_time, 1)
            self._history.append(record.to_dict())

    def _do_install_script(self, node_path: str, node_name: str, script_name: str, install_cmd: List[str]):
        """执行 install.py 脚本并记录结果"""
        start_time = time.time()
        record = InstallRecord(
            node_name=node_name,
            package_name=script_name,
        )

        try:
            record.success = self._install_script(node_path, install_cmd)
        except Exception as e:
            record.error_msg = str(e)
            record.success = False
        finally:
            record.duration = round(time.time() - start_time, 1)
            self._history.append(record.to_dict())

    # === 以下方法与原版保持一致 ===
    
    def _try_get_installed_packages(self):
        """
        获取已安装的包信息并添加到processed_install集合中

        Returns:
            Dict[str, str]: 包名到版本的映射，例如 {'package1': '1.0.0', 'package2': '2.1.0'}
        """
        installed_packages = {}
        try:
            result = subprocess.check_output(self._construct_pip_cmd(["list"]), universal_newlines=True)

            for line in result.split('\n'):
                striped_line = line.strip()
                if striped_line:
                    parts = line.split()
                    package_name = parts[0]
                    if package_name == 'Package' or package_name.startswith('-'):  # skip first line of pip list output
                        continue

                    version = parts[1]
                    self.processed_install.add(package_name)
                    installed_packages[package_name] = version

        except subprocess.CalledProcessError:
            print("[Installer] ## Failed to retrieve the information of installed pip packages.")

        return installed_packages

    def _install_script(self, node_path: str, install_cmd: List[str]):
        print(f"\n[Installer] ## Execute => '{' '.join(install_cmd)}' in '{node_path if node_path else 'current env'}'")
        # FIXME: pip install --timeout 可能会导致依赖安装不完整，因此每个包安装时暂未引入超时时间
        code = subprocess.check_call(install_cmd, cwd=node_path if node_path else None, env=self._get_script_env())

        if code != 0:
            print(f"[Installer] ## Failed to execute => '{' '.join(install_cmd)}' in '{node_path if node_path else 'current env'}'")
            return False

        return True

    def _get_script_env(self):
        """
        执行插件的install.py时需要指定必须的环境变量
        """
        new_env = os.environ.copy()

        if 'COMFYUI_PATH' not in new_env:
            new_env['COMFYUI_PATH'] = constants.COMFYUI_DIR

        if 'COMFYUI_FOLDERS_BASE_PATH' not in new_env:
            new_env['COMFYUI_FOLDERS_BASE_PATH'] = constants.COMFYUI_DIR

        return new_env

    def _get_possible_nodes(self, custom_node_path):
        # 获取custom_nodes目录下所有可能的插件目录名
        nodes = os.listdir(custom_node_path)
        valid_nodes = []

        for node in nodes:
            node_path = os.path.join(custom_node_path, node)

            # 过滤条件：
            # 1. 必须是文件夹
            # 2. 不能以.disabled结尾
            # 3. 不能是__pycache__
            if (os.path.isdir(node_path) and
                    not node.endswith(".disabled") and
                    node != "__pycache__"):
                valid_nodes.append(node)

        return valid_nodes

    @staticmethod
    def _extract_package_name(line: str) -> str:
        """
        从requirement.txt的一行中提取有效的包名

        Args:
            line: requirements.txt中的一行内容，可能包含注释、空格等

        Returns:
            str: 清理后的包名。如果行无效（空行或纯注释）则返回空字符串

        Examples:
            'requests==2.28.0' -> 'requests==2.28.0'
            'numpy>=1.20.0 # some comment' -> 'numpy>=1.20.0'
            '# just a comment' -> ''
            '  ' -> ''
        """
        # 首先去除首尾空白
        package_name = line.strip()

        # 如果是空行或者注释行，返回空字符串
        if not package_name or package_name.startswith('#'):
            return ''

        # 移除行内注释部分
        clean_package_name = package_name.split('#')[0].strip()
        return clean_package_name

    def _parse_version_constraint(self, version_spec: str) -> Dict:
        """
        解析版本约束，提取操作符和版本号
        
        Args:
            version_spec: 版本规范，如 '>=1.0.0', '==2.1.0', '>=1.0,<2.0'
            
        Returns:
            Dict: {
                'operators': [('>=', '1.0.0'), ('==', '2.1.0')],
                'is_exact': bool,  # 是否精确版本
                'has_exclusion': bool,  # 是否有排除版本
            }
        """
        if not version_spec.strip():
            return {
                'operators': [],
                'is_exact': False,
                'has_exclusion': False,
            }
        
        # 解析多个约束（用逗号分隔）
        constraints = [c.strip() for c in version_spec.split(',')]
        operators = []
        is_exact = False
        has_exclusion = False
        
        for constraint in constraints:
            # 匹配操作符和版本号
            match = re.match(r'^([><=!]+)(.+)$', constraint)
            if match:
                op = match.group(1)
                version = match.group(2).strip()
                operators.append((op, version))
                
                if op == '==':
                    is_exact = True
                elif op.startswith('!'):
                    has_exclusion = True
        
        return {
            'operators': operators,
            'is_exact': is_exact,
            'has_exclusion': has_exclusion,
        }
    
    def _apply_conflict_resolution_strategy(self, existing_parsed: Dict, new_parsed: Dict, 
                                          existing_spec: str, new_spec: str, package_name: str) -> str:
        """
        应用冲突解决策略
        
        解决优先级：
        1. 精确版本 vs 精确版本: 选择较新的版本
           例如: torch==1.13.0 vs torch==2.0.1 -> torch==2.0.1
        2. 精确版本 vs 范围版本: 优先选择精确版本
           例如: numpy==1.21.0 vs numpy>=1.20.0 -> numpy==1.21.0
        3. 范围版本 vs 范围版本: 尝试合并或选择更严格的下界
           例如: torch>=1.8.0 vs torch>=1.10.0 -> torch>=1.10.0
        4. 默认策略: 保持第一个遇到的版本约束
        """
        
        # 策略 1: 精确版本 vs 精确版本
        if existing_parsed['is_exact'] and new_parsed['is_exact']:
            # 比较两个版本号，选择较新的
            existing_version = self._extract_version_from_exact(existing_spec)
            new_version = self._extract_version_from_exact(new_spec)
            
            if self._is_version_newer(new_version, existing_version):
                return new_spec
            else:
                return existing_spec
        
        # 策略 2: 精确版本 vs 范围版本
        if existing_parsed['is_exact'] and not new_parsed['is_exact']:
            return existing_spec
        elif new_parsed['is_exact'] and not existing_parsed['is_exact']:
            return new_spec

        # 策略 3: 范围版本 vs 范围版本 - 尝试合并
        if not existing_parsed['is_exact'] and not new_parsed['is_exact']:
            # 尝试合并版本范围
            merged = self._try_merge_version_ranges(existing_spec, new_spec)
            if merged:
                return merged
        
        # 默认策略: 保持现有的
        return existing_spec
    
    def _extract_version_from_exact(self, version_spec: str) -> str:
        """从精确版本约束中提取版本号"""
        match = re.search(r'==([\d\.]+)', version_spec)
        return match.group(1) if match else version_spec
    
    def _is_version_newer(self, version_a: str, version_b: str) -> bool:
        """
        简单版本比较，判断 version_a 是否比 version_b 更新
        注意：这是一个简化的实现，不处理所有复杂情况
        """
        try:
            parts_a = [int(x) for x in version_a.split('.')]
            parts_b = [int(x) for x in version_b.split('.')]
            
            # 补齐到相同长度
            max_len = max(len(parts_a), len(parts_b))
            parts_a.extend([0] * (max_len - len(parts_a)))
            parts_b.extend([0] * (max_len - len(parts_b)))
            
            return parts_a > parts_b
        except ValueError:
            # 如果解析失败，简单字符串比较
            return version_a > version_b
    
    def _try_merge_version_ranges(self, range_a: str, range_b: str) -> Optional[str]:
        """
        使用 packaging 库尝试合并两个版本范围
        返回合并后的范围，或者 None 如果无法合并
        
        # 现在支持的情况：
        # 情况1: 不同下界版本
        # range_a = ">=1.8.0", range_b = ">=1.10.0" -> ">=1.10.0"
        
        # 情况2: 复杂范围约束
        # range_a = ">=1.8.0,<2.0.0", range_b = ">=1.10.0,<3.0.0" -> ">=1.10.0,<2.0.0"
        
        # 情况3: 不兼容的范围
        # range_a = ">=2.0.0", range_b = "<1.0.0" -> None (无交集)
        """
        # 先尝试使用 packaging 库进行高级合并
        merged = self._try_merge_with_packaging(range_a, range_b)
        if merged is not None:
            return merged
        
        # 如果 packaging 失败，回退到简单逻辑
        return self._try_merge_simple_ranges(range_a, range_b)
    
    def _try_merge_with_packaging(self, range_a: str, range_b: str) -> Optional[str]:
        """
        使用 packaging.specifiers 进行版本范围合并
        """
        try:
            from packaging.specifiers import SpecifierSet, InvalidSpecifier
            
            # 创建版本规范集合
            spec_a = SpecifierSet(range_a)
            spec_b = SpecifierSet(range_b)
            
            # 计算交集
            intersection = spec_a & spec_b
            
            if intersection:
                # 有交集，返回合并结果
                merged_str = str(intersection)
                
                # 尝试简化结果（例如：>=1.8.0,>=1.9.0 -> >=1.9.0）
                simplified = self._simplify_version_spec(merged_str)
                if simplified != merged_str:
                    return simplified
                else:
                    return merged_str
            else:
                # 无交集，无法合并
                return None
                
        except ImportError:
            return None
        except InvalidSpecifier as e:
            return None
        except Exception as e:
            return None
    
    def _try_merge_simple_ranges(self, range_a: str, range_b: str) -> Optional[str]:
        """
        简单的版本范围合并回退逻辑
        只处理纯下界约束的合并
        """
        # 处理纯下界约束的合并
        if '>=' in range_a and '<' not in range_a and '>=' in range_b and '<' not in range_b:
            # 两个都是纯下界约束
            version_a = re.search(r'>=([\d\.]+)', range_a)
            version_b = re.search(r'>=([\d\.]+)', range_b)
            
            if version_a and version_b:
                if self._is_version_newer(version_a.group(1), version_b.group(1)):
                    return range_a  # 选择更高的下界
                else:
                    return range_b
        
        # 更复杂的情况无法处理
        return None
    
    def _simplify_version_spec(self, version_spec: str) -> str:
        """
        简化版本规范，例如：>=1.8.0,>=1.9.0 -> >=1.9.0
        """
        # 只处理包含多个>=约束的情况
        if '>=' not in version_spec or ',' not in version_spec:
            return version_spec
        
        # 提取所有>=约束
        constraints = [c.strip() for c in version_spec.split(',')]
        ge_constraints = []
        other_constraints = []
        
        for constraint in constraints:
            if constraint.startswith('>='): 
                match = re.match(r'>=([\d\.]+)', constraint)
                if match:
                    ge_constraints.append((constraint, match.group(1)))
                else:
                    other_constraints.append(constraint)
            else:
                other_constraints.append(constraint)
        
        # 如果有多个>=约束，选择最高的版本
        if len(ge_constraints) > 1:
            # 找到最高的版本约束
            highest_constraint = max(ge_constraints, key=lambda x: self._version_to_tuple(x[1]))
            simplified_constraints = [highest_constraint[0]] + other_constraints
            return ','.join(simplified_constraints)
        
        return version_spec
    
    def _version_to_tuple(self, version: str) -> tuple:
        """将版本字符串转换为可比较的元组"""
        try:
            return tuple(int(x) for x in version.split('.'))
        except ValueError:
            # 如果解析失败，返回原字符串作为单元素元组
            return (version,)
    
    @staticmethod
    def _construct_pip_cmd(cmd):
        return [constants.VENV_EXECUTABLE, '-m', 'pip'] + cmd
