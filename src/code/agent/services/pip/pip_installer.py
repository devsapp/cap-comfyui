import os
import re
import subprocess
import time
from typing import Dict, List, Tuple, Optional

import constants
from utils import file_ops
from models import InstallRecord, DependencyInstallRecord, DependencyInfo
from version_resolver import resolve_version_conflict
from dependency_strategies import apply_custom_dependency_strategies

# pip install -r 失败后，最多重试的轮数
_MAX_INSTALL_RETRIES = 5


class PIPInstaller:
    """优化版本的 PIP 安装器，支持依赖合并、过滤和批量安装"""
    
    def __init__(self, blacklist: Optional[List[str]] = None):
        """
        初始化优化版安装器
        
        Args:
            blacklist: 黑名单包列表，这些包将被跳过安装
        """
        self._origin_packages = self._try_get_installed_packages()
        self.blacklist = set(blacklist) if blacklist else set()
        # 收集所有无法自动安装的疑难依赖（黑名单 / git+ / 安装失败），key 为规范化包名
        self._problematic_deps: Dict[str, DependencyInfo] = {}
        
    def get_origin_packages(self):
        return self._origin_packages

    def install_all(self, timeout=constants.DEFAULT_INSTALL_TIMEOUT, nodes_map=None):
        """
        完整安装流程，分四个步骤顺序执行：

          Step 1 — 扫描插件目录，合并所有 requirements.txt，应用黑名单 / 已安装过滤
                   和定制化策略（nunchaku 等），输出最终依赖字典。
          Step 2 — pip install -r 整体安装依赖字典中的所有包（带超时控制）。
                   安装失败时解析 stderr 识别问题包，将其剔除后有限次重试，
                   保证其余包仍可安装成功。
          Step 3 — 逐插件执行 install.py（部分插件需要自己的安装脚本）。
          Step 4 — 汇总并打印所有疑难依赖（黑名单 / git+ / 安装失败），
                   方便用户手动补装。

        Args:
            timeout:   全局超时秒数，默认 constants.DEFAULT_INSTALL_TIMEOUT（10 分钟）。
                       Step 2 的每轮 pip 子进程和 Step 3 均受此约束。
            nodes_map: 节点配置映射。None = 安装所有可用节点；{} = 不安装任何节点；
                       非空 dict = 只安装其中指定的有效节点。

        Returns:
            Dict: {
                "baseline":        Dict[str, str],                        # 安装前的环境快照（包名 → 版本）
                "dependencies":    DependencyInstallRecord.to_dict(),      # Step 2 安装结果
                "scripts":         [InstallRecord.to_dict(), ...],         # Step 3 各插件脚本结果
                "problematic_deps": [str, ...],                            # Step 4 疑难依赖列表
            }
        """
        nodes_path = os.path.join(constants.COMFYUI_DIR, "custom_nodes")
        all_available_nodes = self._get_possible_nodes(nodes_path)

        # --- 确定要安装的节点列表 ---
        nodes_to_install = self._determine_nodes_to_install(all_available_nodes, nodes_map)

        # 每次 install_all 调用前重置疑难依赖列表
        self._problematic_deps = {}

        # 初始化结果映射
        result_map = {
            "baseline": self._origin_packages,  # 安装前的包基线
            "dependencies": None,             # 依赖安装结果
            "scripts": [],                    # install.py 脚本安装结果列表
            "problematic_deps": []            # 疑难依赖列表
        }

        if not nodes_to_install:
            print("\n[Installer] No nodes to install. Skipping.")
            # 返回空的依赖安装记录
            empty_dep_record = DependencyInstallRecord(requirements_txt="")
            empty_dep_record.success = True
            empty_dep_record.duration = 0
            result_map["dependencies"] = empty_dep_record.to_dict()
            return result_map

        print(f"\n[Installer] Starting installation for {len(nodes_to_install)} nodes...")
        start_time = time.time()

        try:
            # Step 1: 合并所有 requirements.txt → 过滤 → 定制化策略 → 依赖字典
            merged_deps = self._merge_requirements_from_nodes(nodes_to_install, nodes_map, timeout, start_time)

            # Step 2: pip install -r（整体安装 + 失败包剔除重试）
            dependency_record = self._install_merged_dependencies(merged_deps, timeout, start_time)
            result_map["dependencies"] = dependency_record.to_dict()

            # Step 3: 逐插件执行 install.py
            script_records = self._execute_install_scripts(nodes_to_install, timeout, start_time)
            result_map["scripts"] = script_records

        except TimeoutError as e:
            print(f"\n[Installer] {e}")
            # 即使超时，也返回已经完成的部分

        # Step 4: 汇总并打印疑难依赖（黑名单 / git+ / 安装失败）
        self._print_problematic_deps()
        result_map["problematic_deps"] = [
            f"{name}{dep.version_spec}" if dep.version_spec else name
            for name, dep in self._problematic_deps.items()
        ]

        total_duration = time.time() - start_time
        print(f"\n[Installer] Installation completed. Total time: {total_duration:.1f}s")

        # 统计信息
        dep_success = result_map["dependencies"]["success"] if result_map["dependencies"] else True
        script_success_count = len([r for r in result_map["scripts"] if r["success"]])
        script_total_count = len(result_map["scripts"])

        print(f"[Installer] Dependencies: {'Success' if dep_success else 'Failed'}")
        print(f"[Installer] Scripts: {script_success_count}/{script_total_count} successful")

        return result_map

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

    def _merge_requirements_from_nodes(self, nodes_to_install: List[str], nodes_map, timeout: float, start_time: float) -> Dict[str, DependencyInfo]:
        """步骤1: 遍历并合并所有节点的 requirements.txt，应用过滤逻辑（如黑名单），返回过滤后的依赖字典"""
        print(f"\n[Installer] ## Step 1: Merging requirements.txt from {len(nodes_to_install)} nodes...")
        
        merged_dependencies: Dict[str, DependencyInfo] = {}
        for node_name in nodes_to_install:
            if time.time() - start_time >= timeout:
                raise TimeoutError(f"Timeout ({timeout}s) reached during requirements merging")
                
            node_path = os.path.join(constants.COMFYUI_DIR, "custom_nodes", node_name)
            requirements_path = os.path.join(node_path, "requirements.txt")
            
            if os.path.exists(requirements_path):
                self._merge_requirements_file(requirements_path, node_name, merged_dependencies)
        
        print(f"[Installer] ## Merged {len(merged_dependencies)} unique dependencies from requirements.txt files")
        
        # 应用过滤逻辑
        merged_deps = self._filter_merged_dependencies(merged_dependencies)

        # 应用定制化依赖策略钩子
        merged_deps = apply_custom_dependency_strategies(merged_deps, nodes_to_install, nodes_map)

        return merged_deps

    def _merge_requirements_file(self, requirements_path: str, node_name: str, merged_dependencies: Dict[str, DependencyInfo]):
        """合并单个 requirements.txt 文件到 merged_dependencies 字典"""
        lines = file_ops.robust_readlines(requirements_path)
        
        for line in lines:
            package_spec = self._extract_package_name(line)
            if not package_spec:
                continue
                
            # 解析包名和版本规范
            base_name, version_spec = self._parse_package_spec(package_spec)
            
            if base_name in merged_dependencies:
                # 处理版本冲突
                existing_dep = merged_dependencies[base_name]
                resolved_version = resolve_version_conflict(
                    existing_dep.version_spec, version_spec, base_name
                )
                existing_dep.version_spec = resolved_version
                existing_dep.source_nodes.append(node_name)
            else:
                # 新依赖
                merged_dependencies[base_name] = DependencyInfo(
                    package_name=base_name,
                    version_spec=version_spec,
                    original_line=package_spec,
                    source_nodes=[node_name]
                )

    def _filter_merged_dependencies(self, merged_dependencies: Dict[str, DependencyInfo]) -> Dict[str, DependencyInfo]:
        """过滤合并后的依赖列表，应用黑名单、已安装包和 git+ 依赖过滤"""
        filtered = {}
        
        skipped_already_installed = []
        skipped_blacklisted = []
        skipped_git_dependencies = []
        
        for base_name, dep_info in merged_dependencies.items():
            # 过滤掉所有 git+ 形式的依赖
            if base_name.startswith(('git+', 'hg+', 'svn+', 'bzr+')):
                skipped_git_dependencies.append(base_name)
                self._problematic_deps[base_name] = dep_info
                continue
                
            # 检查黑名单
            if base_name.lower() in {pkg.lower() for pkg in self.blacklist}:
                skipped_blacklisted.append(base_name)
                self._problematic_deps[base_name] = dep_info
                continue
                
            # 检查是否已安装
            # 只跳过无版本要求且已安装的包
            # 如果有版本要求，则交给pip处理版本升级/降级
            if base_name in self._origin_packages and not dep_info.version_spec:
                # 包已安装且无特定版本要求，跳过安装
                skipped_already_installed.append(f"{base_name}")
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


    def _generate_requirements_content(self, filtered_deps: Dict[str, DependencyInfo]) -> str:
        """生成最终的 requirements.txt 内容"""
        if not filtered_deps:
            print("[Installer] ## No dependencies to install after filtering.")
            return ""
        
        print(f"[Installer] ## Generated requirements.txt with {len(filtered_deps)} dependencies:")
        print("[Installer] ## " + "=" * 60)
        
        # 按包名排序
        sorted_deps = sorted(filtered_deps.items())
        requirements_lines = []
        
        for base_name, dep_info in sorted_deps:
            # 构建 requirements.txt 格式的行
            package_line = f"{base_name}{dep_info.version_spec}" if dep_info.version_spec else base_name
            requirements_lines.append(package_line)
            
            # 添加来源节点注释（只用于日志显示）
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
        
        return "\n".join(requirements_lines)

    def _install_merged_dependencies(self, merged_deps: Dict[str, DependencyInfo], timeout: float, start_time: float) -> DependencyInstallRecord:
        """
        步骤2: 使用 pip install -r 批量安装合并后的依赖。

        失败时解析 stderr 提取问题包，从 merged_deps 字典中剔除后重试，
        最多重试 _MAX_INSTALL_RETRIES 次。每次重试前检查剩余超时。
        """
        print(f"\n[Installer] ## Step 2: Installing dependencies with pip install -r (timeout: {timeout}s)...")

        # 生成初始 requirements 内容（同时打印日志）
        initial_content = self._generate_requirements_content(merged_deps)
        install_record = DependencyInstallRecord(requirements_txt=initial_content)

        if not merged_deps:
            print("[Installer] ## No dependencies to install.")
            install_record.success = True
            install_record.duration = 0
            return install_record
        
        import tempfile
        start_install_time = time.time()
        current_deps = dict(merged_deps)  # 浅拷贝，重试时直接操作此字典
        current_content = initial_content
        retry_count = 0

        try:
            while True:
                # 计算本轮剩余超时
                elapsed = time.time() - start_time
                remaining_timeout = timeout - elapsed
                if remaining_timeout <= 0:
                    install_record.success = False
                    install_record.error_msg = f"No time remaining before pip install (total timeout: {timeout}s)"
                    print(f"[Installer] ## Error: {install_record.error_msg}")
                    break

                # 写入临时 requirements 文件
                with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                    f.write(current_content)
                    temp_path = f.name

                try:
                    install_cmd = self._construct_pip_cmd(["install", "-r", temp_path])
                    attempt_label = "initial attempt" if retry_count == 0 else f"retry {retry_count}/{_MAX_INSTALL_RETRIES}"
                    print(f"[Installer] ## Executing ({attempt_label}): {' '.join(install_cmd)}")

                    try:
                        # stdout 实时输出到控制台；stderr 捕获用于解析失败包
                        result = subprocess.run(
                            install_cmd,
                            stderr=subprocess.PIPE,
                            text=True,
                            timeout=remaining_timeout,
                            env=self._get_pip_install_env()
                        )
                    except subprocess.TimeoutExpired:
                        install_record.success = False
                        install_record.error_msg = f"pip install timed out after {remaining_timeout:.0f}s"
                        print(f"[Installer] ## Error: {install_record.error_msg}")
                        break

                    if result.returncode == 0:
                        install_record.success = True
                        install_record.requirements_txt = current_content
                        print("[Installer] ## Dependencies installed successfully.")
                        break

                    # 将捕获的 stderr 打印出来，保证用户可见
                    if result.stderr:
                        print(result.stderr, end='')

                    # 解析 stderr，提取失败的包规范
                    # pip 错误格式：Could not install requirement <pkg_spec> because ...
                    failed_specs = re.findall(r'Could not install requirement (\S+)', result.stderr)

                    if not failed_specs:
                        install_record.success = False
                        install_record.error_msg = (
                            f"pip install failed (returncode={result.returncode}), "
                            "but no specific failed package could be identified from stderr"
                        )
                        print(f"[Installer] ## Error: {install_record.error_msg}")
                        break

                    # 从 current_deps 字典中剔除失败包，加入 problematic_deps
                    newly_removed = []
                    for spec in failed_specs:
                        pkg_name, _ = self._parse_package_spec(spec)
                        if pkg_name in current_deps:
                            dep = current_deps.pop(pkg_name)
                            self._problematic_deps[pkg_name] = dep
                            display_spec = f"{pkg_name}{dep.version_spec}" if dep.version_spec else pkg_name
                            print(f"[Installer] ## Problematic package identified: {display_spec} (will retry without it)")
                            newly_removed.append(display_spec)

                    if not newly_removed:
                        # 所有失败包已在上轮被剔除，无法继续进展，防止死循环
                        install_record.success = False
                        install_record.error_msg = (
                            "pip install keeps failing on the same package(s); "
                            "no further progress possible"
                        )
                        print(f"[Installer] ## Error: {install_record.error_msg}")
                        break

                    retry_count += 1
                    if retry_count > _MAX_INSTALL_RETRIES:
                        install_record.success = False
                        install_record.error_msg = f"pip install still failing after {_MAX_INSTALL_RETRIES} retries"
                        print(f"[Installer] ## Error: Max retries ({_MAX_INSTALL_RETRIES}) reached. Giving up.")
                        break

                    # 从字典直接重建 requirements 内容，不触发 _generate_requirements_content 的日志
                    current_content = '\n'.join(
                        f"{name}{dep.version_spec}" if dep.version_spec else name
                        for name, dep in sorted(current_deps.items())
                    )
                    print(f"[Installer] ## Retrying without {len(newly_removed)} problematic package(s)...")

                finally:
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass

        except Exception as e:
            install_record.success = False
            install_record.error_msg = f"Unexpected error during installation: {str(e)}"
            print(f"[Installer] ## Error: {install_record.error_msg}")

        finally:
            install_record.duration = round(time.time() - start_install_time, 1)

        return install_record

    def _execute_install_scripts(self, nodes_to_install: List[str], timeout: float, start_time: float) -> List[Dict]:
        """步骤3: 执行各插件的 install.py 脚本，返回安装记录列表"""
        # 在开始 Step 3 之前检查是否已经超时
        if time.time() - start_time >= timeout:
            print(f"\n[Installer] ## Step 3 skipped: Already timed out ({timeout}s)")
            return []  # 直接返回空列表，不执行 install.py 脚本
        
        print(f"\n[Installer] ## Step 3: Executing install.py scripts...")
        
        script_records = []
        install_scripts_found = 0
        
        for node_name in nodes_to_install:
            if time.time() - start_time >= timeout:
                raise TimeoutError(f"Timeout ({timeout}s) reached during install.py execution")
                
            node_path = os.path.join(constants.COMFYUI_DIR, "custom_nodes", node_name)
            install_script_path = os.path.join(node_path, "install.py")
            
            if os.path.exists(install_script_path):
                install_scripts_found += 1
                print(f"[Installer] ## Executing install.py for node: {node_name}")
                install_cmd = [constants.VENV_EXECUTABLE, "install.py"]
                record = self._do_install_script(node_path, node_name, "install.py", install_cmd)
                script_records.append(record)
        
        print(f"[Installer] ## Executed {install_scripts_found} install.py scripts")
        return script_records

    def _print_problematic_deps(self):
        """打印所有疑难依赖，供用户手动安装。"""
        if not self._problematic_deps:
            return

        print("\n[Installer] ## ========== Problematic Dependencies ==========")
        print("[Installer] ## The following packages could not be installed automatically.")
        print("[Installer] ## You can copy and install them manually:")
        print("[Installer] ##")
        for pkg_name, dep_info in self._problematic_deps.items():
            print(f"{pkg_name}{dep_info.version_spec}" if dep_info.version_spec else pkg_name)
        print("[Installer] ## ===============================================")

    def _parse_package_spec(self, package_spec: str) -> Tuple[str, str]:
        """
        解析包规范，提取包名和版本约束。
        返回的包名已按 PEP 503 规范化（小写、连字符统一）。
        
        Args:
            package_spec: 如 "torch>=1.0.0", "requests==2.28.0", "numpy",
                          "accelerate >= 1.2.1", "git+https://github.com/user/repo.git"
            
        Returns:
            Tuple[规范化后的包名, 版本规范]
        """
        package_spec = package_spec.strip()
        
        # 处理 git+ 依赖：直接使用完整 URL 作为包名，版本规范为空
        if package_spec.startswith(('git+', 'hg+', 'svn+', 'bzr+')):
            return package_spec, ""
        
        # 支持包名与版本操作符之间有空格，如 "accelerate >= 1.2.1"
        version_pattern = r'^([a-zA-Z0-9._-]+)\s*((?:[><=!]+).*)?$'
        match = re.match(version_pattern, package_spec)
        
        if match:
            raw_name = match.group(1)
            version_spec = match.group(2).strip() if match.group(2) else ""
            # PEP 503：包名规范化——小写，连字符/下划线/点统一为连字符
            normalized_name = re.sub(r'[-_.]+', '-', raw_name).lower()
            return normalized_name, version_spec
        else:
            # 如果无法解析，返回原始规范
            return package_spec, ""

    def _do_install_script(self, node_path: str, node_name: str, script_name: str, install_cmd: List[str]) -> Dict:
        """执行 install.py 脚本并记录结果，返回安装记录字典"""
        start_time = time.time()
        record = InstallRecord(
            node_name=node_name,
            script_name=script_name,
        )

        try:
            record.success = self._install_script(node_path, install_cmd)
        except Exception as e:
            record.error_msg = str(e)
            record.success = False
        finally:
            record.duration = round(time.time() - start_time, 1)
            
        return record.to_dict()

    # === 以下方法与原版保持一致 ===
    
    def _try_get_installed_packages(self):
        """
        获取已安装的包信息，包名按 PEP 503 规范化（小写、连字符统一），
        与 _parse_package_spec 返回的包名格式保持一致，确保已安装判断准确。

        Returns:
            Dict[str, str]: 规范化包名到版本的映射，例如 {'pillow': '10.0.0', 'scikit-learn': '1.3.0'}
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
                    # PEP 503：规范化包名，与 _parse_package_spec 保持一致
                    normalized_name = re.sub(r'[-_.]+', '-', package_name).lower()
                    installed_packages[normalized_name] = version

        except subprocess.CalledProcessError:
            print("[Installer] ## Failed to retrieve the information of installed pip packages.")

        return installed_packages

    def _install_script(self, node_path: str, install_cmd: List[str]):
        print(f"\n[Installer] ## Execute => '{' '.join(install_cmd)}' in '{node_path if node_path else 'current env'}'")
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
    
    def _get_pip_install_env(self):
        """
        执行pip install -r时需要的环境变量，特别是清除代理设置
        """
        new_env = self._get_script_env()  # 先获取基本环境
        
        # 清除代理环境变量，避免pip安装时受代理影响
        proxy_vars = ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']
        for proxy_var in proxy_vars:
            new_env.pop(proxy_var, None)
        
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

    @staticmethod
    def _construct_pip_cmd(cmd):
        return [constants.VENV_EXECUTABLE, '-m', 'pip'] + cmd
