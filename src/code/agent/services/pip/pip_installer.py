import os
import re
import subprocess
import time
from typing import Dict, List, Tuple, Optional

import constants
from utils import file_ops
from services.pip.models import InstallRecord, DependencyInstallRecord, DependencyInfo
from services.pip.version_resolver import resolve_version_conflict
from services.pip.dependency_strategies import apply_custom_dependency_strategies

# 第一轮分批安装每批的包数
_BATCH_SIZE = 10

# 逐个安装（fallback 轮）使用的 pip 源：aliyun 主源 + PyPI 官方兜底
# 通过环境变量覆盖 pip.conf，避免 tsinghua/ustc 源问题干扰兜底安装
_FALLBACK_INDEX_URL = "https://mirrors.aliyun.com/pypi/simple/"
_FALLBACK_EXTRA_INDEX_URL = "https://pypi.org/simple/"


class PIPInstaller:
    """优化版本的 PIP 安装器，支持依赖合并、过滤和两轮批次安装"""

    def __init__(self, blacklist: Optional[List[str]] = None):
        """
        Args:
            blacklist: 黑名单包列表，这些包将被跳过安装并记录为疑难依赖
        """
        self._origin_packages = self._try_get_installed_packages()
        self.blacklist = set(blacklist) if blacklist else set()
        # 收集所有无法自动安装的疑难依赖（黑名单 / git+ / 安装失败），key 为规范化包名
        self._problematic_deps: Dict[str, DependencyInfo] = {}

    def get_origin_packages(self):
        return self._origin_packages

    def install_all(self, timeout=constants.DEFAULT_INSTALL_TIMEOUT, nodes_map=None):
        """
        完整安装流程，分三个步骤顺序执行：

          Step 1 — 扫描插件目录，合并所有 requirements.txt，应用黑名单 / 已安装过滤
                   和定制化策略（nunchaku 等），输出最终依赖字典。
          Step 2 — 两轮批次安装：
                   第一轮按 _BATCH_SIZE=10 分批 pip install，失败批整批记入 failed_batches；
                   第二轮将 failed_batches 展开后逐个 pip install，仍失败的包加入 problematic_deps。
                   两轮均通过 returncode 判断成功与否，不解析 stderr。
          Step 3 — 逐插件执行 install.py（部分插件需要自己的安装脚本）。

        Args:
            timeout:   全局超时秒数，默认 constants.DEFAULT_INSTALL_TIMEOUT（10 分钟）。
                       Step 2 的每轮 pip 子进程和 Step 3 均受此约束。
            nodes_map: 节点配置映射。None = 安装所有可用节点；{} = 不安装任何节点；
                       非空 dict = 只安装其中指定的有效节点。

        Returns:
            Dict: {
                "baseline":     Dict[str, str],           # 安装前的环境快照（包名 → 版本）
                "dependencies": dict,                     # Step 2 安装结果（含 problematic_deps）
                "scripts":      [dict, ...],              # Step 3 各插件脚本结果
            }
        """
        nodes_path = os.path.join(constants.COMFYUI_DIR, "custom_nodes")
        all_available_nodes = self._get_possible_nodes(nodes_path)

        nodes_to_install = self._determine_nodes_to_install(all_available_nodes, nodes_map)

        self._problematic_deps: Dict[str, DependencyInfo] = {}

        result_map = {
            "baseline": self._origin_packages,
            "dependencies": DependencyInstallRecord().to_dict(),
            "scripts": [],
        }

        if not nodes_to_install:
            print("\n[Installer] No nodes to install. Skipping.")
            return result_map

        print(f"\n[Installer] Starting installation for {len(nodes_to_install)} nodes...")
        start_time = time.time()

        try:
            # Step 1: 合并所有 requirements.txt → 过滤 → 定制化策略
            merged_deps = self._merge_requirements_from_nodes(nodes_to_install, nodes_map, timeout, start_time)

            # Step 2: 依赖安装
            dependency_record = self._install_merged_dependencies(merged_deps, timeout, start_time)
            result_map["dependencies"] = dependency_record.to_dict()

            # Step 3: 逐插件执行 install.py
            script_records = self._execute_install_scripts(nodes_to_install, timeout, start_time)
            result_map["scripts"] = script_records

        except TimeoutError as e:
            print(f"\n[Installer] {e}")

        self._print_problematic_deps()

        total_duration = time.time() - start_time
        print(f"\n[Installer] Installation completed. Total time: {total_duration:.1f}s")

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
            nodes_to_install = sorted(all_available_nodes)
            print(f"\n[Installer] Preparing to install all {len(nodes_to_install)} available nodes.")
        else:
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

        merged_deps = self._filter_merged_dependencies(merged_dependencies)
        merged_deps = apply_custom_dependency_strategies(merged_deps, nodes_to_install, nodes_map)

        return merged_deps

    def _merge_requirements_file(self, requirements_path: str, node_name: str, merged_dependencies: Dict[str, DependencyInfo]):
        """合并单个 requirements.txt 文件到 merged_dependencies 字典"""
        lines = file_ops.robust_readlines(requirements_path)

        for line in lines:
            package_spec = self._extract_package_name(line)
            if not package_spec:
                continue

            base_name, version_spec = self._parse_package_spec(package_spec)

            if base_name in merged_dependencies:
                existing_dep = merged_dependencies[base_name]
                resolved_version = resolve_version_conflict(
                    existing_dep.version_spec, version_spec, base_name
                )
                existing_dep.version_spec = resolved_version
                existing_dep.source_nodes.append(node_name)
            else:
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

            # 已安装且无版本要求则跳过；有版本要求则交给 pip 处理升降级
            if base_name in self._origin_packages and not dep_info.version_spec:
                skipped_already_installed.append(base_name)
                continue

            filtered[base_name] = dep_info

        if skipped_already_installed:
            print(f"[Installer] ## Skipped {len(skipped_already_installed)} already installed packages: {', '.join(skipped_already_installed)}")

        if skipped_blacklisted:
            print(f"[Installer] ## Skipped {len(skipped_blacklisted)} blacklisted packages: {', '.join(skipped_blacklisted)}")

        if skipped_git_dependencies:
            print(f"[Installer] ## Skipped {len(skipped_git_dependencies)} git+ dependencies (need install manually):")
            for git_dep in skipped_git_dependencies:
                print(f"[Installer] ##   - {git_dep}")

        return filtered

    def _generate_requirements_content(self, deps: List[DependencyInfo]) -> str:
        """生成最终的 requirements.txt 内容并打印日志，调用方需传入已排序的列表"""
        if not deps:
            print("[Installer] ## No dependencies to install after filtering.")
            return ""

        print(f"[Installer] ## Generated requirements list with {len(deps)} dependencies:")
        print("[Installer] ## " + "=" * 60)

        requirements_lines = []
        for dep in deps:
            package_line = f"{dep.package_name}{dep.version_spec}" if dep.version_spec else dep.package_name
            requirements_lines.append(package_line)

            if len(dep.source_nodes) == 1:
                comment = f"  # required by {dep.source_nodes[0]}"
            else:
                if len(dep.source_nodes) <= 3:
                    nodes_str = ", ".join(dep.source_nodes)
                else:
                    nodes_str = ", ".join(dep.source_nodes[:3]) + f" and {len(dep.source_nodes) - 3} more"
                comment = f"  # required by {nodes_str}"

            print(f"{package_line}{comment}")

        print("[Installer] ## " + "=" * 60)
        print(f"[Installer] ## Total: {len(deps)} packages to install")
        print("")

        return "\n".join(requirements_lines)

    def _install_merged_dependencies(self, merged_deps: Dict[str, DependencyInfo], timeout: float, start_time: float) -> DependencyInstallRecord:
        """
        步骤2: 两轮批次安装。

        第一轮按 _BATCH_SIZE 分批执行 pip install，整批失败的批次记入 failed_batches。
        第二轮将 failed_batches 中的依赖展开去重后逐个安装，
        仍失败的包加入 self._problematic_deps。
        """
        print(f"\n[Installer] ## Step 2: Installing dependencies (two-round batch, batch_size={_BATCH_SIZE}, timeout={timeout}s)...")

        sorted_deps = sorted(merged_deps.values(), key=lambda d: d.package_name)
        initial_content = self._generate_requirements_content(sorted_deps)
        install_record = DependencyInstallRecord(requirements_txt=initial_content)

        if not sorted_deps:
            print("[Installer] ## No dependencies to install.")
            return install_record

        start_install_time = time.time()

        try:
            # 第一轮：分批安装
            print(f"\n[Installer] ## Round 1: {len(sorted_deps)} deps → {-(-len(sorted_deps) // _BATCH_SIZE)} batches of {_BATCH_SIZE}")
            failed_deps = self._install_in_batches(sorted_deps, timeout, start_time)

            # 第二轮：逐个安装失败批次的依赖
            if failed_deps:
                print(f"\n[Installer] ## Round 2: {len(failed_deps)} deps to retry individually...")
                self._install_individually(failed_deps, timeout, start_time)
            else:
                print("[Installer] ## Round 1 succeeded for all batches. Round 2 skipped.")

            install_record.success = True

        except Exception as e:
            install_record.success = False
            install_record.error_msg = f"Unexpected error during installation: {str(e)}"
            print(f"[Installer] ## Error: {install_record.error_msg}")

        finally:
            install_record.duration = round(time.time() - start_install_time, 1)
            install_record.problematic_deps = list(self._problematic_deps.values())

        return install_record

    def _install_in_batches(
        self,
        deps: List[DependencyInfo],
        timeout: float,
        start_time: float,
    ) -> List[DependencyInfo]:
        """
        第一轮：按 _BATCH_SIZE 分批安装，返回所有失败的依赖（平铺列表）。

        批次失败（returncode != 0 或超时）时，整批加入 failed_deps 供第二轮兜底。
        超时前未执行的批次同样加入，确保每个包都有第二轮的机会。
        """
        batches = [deps[i:i + _BATCH_SIZE] for i in range(0, len(deps), _BATCH_SIZE)]
        total_batches = len(batches)
        failed_deps: List[DependencyInfo] = []
        failed_batch_count = 0

        for i, batch in enumerate(batches):
            elapsed = time.time() - start_time
            remaining = timeout - elapsed
            if remaining <= 0:
                # 超时：当前及后续批次全部移入 failed_deps
                for b in batches[i:]:
                    failed_deps.extend(b)
                failed_batch_count += total_batches - i
                print(f"[Installer] ## Round 1: timeout at batch {i + 1}/{total_batches}, "
                      f"{total_batches - i} batch(es) deferred to Round 2")
                break

            specs = [
                f"{dep.package_name}{dep.version_spec}" if dep.version_spec else dep.package_name
                for dep in batch
            ]
            cmd = self._construct_pip_cmd(["install"] + specs)
            print(f"[Installer] ## Round 1 [{i + 1}/{total_batches}]: pip install {' '.join(specs)}")

            try:
                result = subprocess.run(cmd, timeout=remaining, env=self._get_pip_install_env())
                if result.returncode == 0:
                    print(f"[Installer] ## Round 1 [{i + 1}/{total_batches}]: succeeded")
                else:
                    print(f"[Installer] ## Round 1 [{i + 1}/{total_batches}]: failed (returncode={result.returncode}) → Round 2")
                    failed_deps.extend(batch)
                    failed_batch_count += 1
            except subprocess.TimeoutExpired:
                print(f"[Installer] ## Round 1 [{i + 1}/{total_batches}]: timed out → Round 2")
                failed_deps.extend(batch)
                failed_batch_count += 1

        print(f"[Installer] ## Round 1 done: {total_batches - failed_batch_count}/{total_batches} batches succeeded, "
              f"{len(failed_deps)} dep(s) to retry")
        return failed_deps

    def _install_individually(
        self,
        deps: List[DependencyInfo],
        timeout: float,
        start_time: float,
    ):
        """
        第二轮：逐个安装，失败或超时的包加入 self._problematic_deps。

        使用精简源配置（aliyun 主源 + PyPI 官方兜底），通过环境变量覆盖 pip.conf，
        避免 tsinghua/ustc 镜像覆盖不全时干扰兜底安装。
        """
        env = self._get_pip_install_env()
        env["PIP_INDEX_URL"] = _FALLBACK_INDEX_URL
        env["PIP_EXTRA_INDEX_URL"] = _FALLBACK_EXTRA_INDEX_URL

        total = len(deps)
        for idx, dep in enumerate(deps):
            elapsed = time.time() - start_time
            remaining = timeout - elapsed
            if remaining <= 0:
                for d in deps[idx:]:
                    self._problematic_deps[d.package_name] = d
                print(f"[Installer] ## Round 2: timeout reached, {total - idx} package(s) skipped → problematic")
                return

            spec = f"{dep.package_name}{dep.version_spec}" if dep.version_spec else dep.package_name
            cmd = self._construct_pip_cmd(["install", spec])
            print(f"[Installer] ## Round 2 [{idx + 1}/{total}]: pip install {spec}")

            try:
                result = subprocess.run(cmd, timeout=remaining, env=env)
                if result.returncode == 0:
                    print(f"[Installer] ## Round 2 [{idx + 1}/{total}]: {spec} succeeded")
                else:
                    print(f"[Installer] ## Round 2 [{idx + 1}/{total}]: {spec} failed → problematic")
                    self._problematic_deps[dep.package_name] = dep
            except subprocess.TimeoutExpired:
                print(f"[Installer] ## Round 2 [{idx + 1}/{total}]: {spec} timed out → problematic")
                self._problematic_deps[dep.package_name] = dep

    def _execute_install_scripts(self, nodes_to_install: List[str], timeout: float, start_time: float) -> List[Dict]:
        """步骤3: 执行各插件的 install.py 脚本，返回安装记录列表"""
        if time.time() - start_time >= timeout:
            print(f"\n[Installer] ## Step 3 skipped: Already timed out ({timeout}s)")
            return []

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
        for dep in self._problematic_deps.values():
            package_line = f"{dep.package_name}{dep.version_spec}" if dep.version_spec else dep.package_name
            if len(dep.source_nodes) == 1:
                comment = f"  # required by {dep.source_nodes[0]}"
            else:
                if len(dep.source_nodes) <= 3:
                    nodes_str = ", ".join(dep.source_nodes)
                else:
                    nodes_str = ", ".join(dep.source_nodes[:3]) + f" and {len(dep.source_nodes) - 3} more"
                comment = f"  # required by {nodes_str}"
            print(f"{package_line}{comment}")
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
                    if package_name == 'Package' or package_name.startswith('-'):
                        continue

                    version = parts[1]
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
        """执行插件的 install.py 时需要指定必须的环境变量"""
        new_env = os.environ.copy()

        if 'COMFYUI_PATH' not in new_env:
            new_env['COMFYUI_PATH'] = constants.COMFYUI_DIR

        if 'COMFYUI_FOLDERS_BASE_PATH' not in new_env:
            new_env['COMFYUI_FOLDERS_BASE_PATH'] = constants.COMFYUI_DIR

        return new_env

    def _get_pip_install_env(self):
        """执行 pip install 时需要的环境变量，特别是清除代理设置"""
        new_env = self._get_script_env()

        proxy_vars = ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']
        for proxy_var in proxy_vars:
            new_env.pop(proxy_var, None)

        return new_env

    def _get_possible_nodes(self, custom_node_path):
        nodes = os.listdir(custom_node_path)
        valid_nodes = []

        for node in nodes:
            node_path = os.path.join(custom_node_path, node)

            if (os.path.isdir(node_path) and
                    not node.endswith(".disabled") and
                    node != "__pycache__"):
                valid_nodes.append(node)

        return valid_nodes

    @staticmethod
    def _extract_package_name(line: str) -> str:
        """
        从 requirements.txt 的一行中提取有效的包规范。

        Examples:
            'requests==2.28.0'            -> 'requests==2.28.0'
            'numpy>=1.20.0 # some comment' -> 'numpy>=1.20.0'
            '# just a comment'            -> ''
            '  '                          -> ''
        """
        package_name = line.strip()

        if not package_name or package_name.startswith('#'):
            return ''

        clean_package_name = package_name.split('#')[0].strip()
        return clean_package_name

    @staticmethod
    def _construct_pip_cmd(cmd):
        return [constants.VENV_EXECUTABLE, '-m', 'pip'] + cmd
