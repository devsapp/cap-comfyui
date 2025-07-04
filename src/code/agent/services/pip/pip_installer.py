import os
import subprocess
import time

import constants
from utils import file_ops
from dataclasses import dataclass, asdict


@dataclass
class InstallRecord:
    node_name: str
    package_name: str
    duration: float = 0  # 耗时(秒)
    success: bool = True
    error_msg: str = ""

    def to_dict(self):
        return asdict(self)


class PIPInstaller:
    def __init__(self):
        self.processed_install = set()
        self._history = []
        self._origin_packages = self._try_get_installed_packages()

    def get_origin_packages(self):
        return self._origin_packages

    def install_all(self, soft_timeout=300, nodes_map=None):
        """
        安装 ComfyUI 自定义节点。
        安装行为由 nodes_map 控制:
        - None (默认): 安装环境中所有可用的节点。
        - 空字典: 不安装任何节点。
        - 非空字典: 只安装字典中指定的有效节点。
        """
        nodes_path = os.path.join(constants.COMFYUI_DIR, "custom_nodes")
        all_available_nodes = self._get_possible_nodes(nodes_path)

        # --- 确定要安装的节点列表 ---
        if nodes_map is None:
            # 场景1: 安装所有节点
            nodes_to_install = sorted(all_available_nodes)
            print(f"\n[FunctionAI-Installer] Preparing to install all {len(nodes_to_install)} available nodes.")
        else:
            # 场景2: 安装指定节点
            requested_nodes = set(nodes_map.keys())
            available_nodes_set = set(all_available_nodes)

            nodes_to_install = sorted(list(requested_nodes & available_nodes_set))
            invalid_nodes = sorted(list(requested_nodes - available_nodes_set))

            if invalid_nodes:
                print(f"\n[FunctionAI-Installer] Warning: Skipping {len(invalid_nodes)} invalid nodes: {', '.join(invalid_nodes)}")

            if nodes_to_install:
                print(f"\n[FunctionAI-Installer] Found {len(nodes_to_install)} valid nodes to install: {', '.join(nodes_to_install)}")

        # --- 统一处理安装流程 ---
        if not nodes_to_install:
            print("\n[FunctionAI-Installer] No nodes to install. Skipping.")
            return self._history

        nodes_num = len(nodes_to_install)
        print(f"\n[FunctionAI-Installer] Starting batch installation for {nodes_num} nodes...")

        start_time = time.time()
        completed_nodes = 0
        for i, node_name in enumerate(nodes_to_install, 1):
            current_duration = time.time() - start_time
            if current_duration >= soft_timeout:
                print(f"\n[FunctionAI-Installer] ## Soft timeout ({soft_timeout}s) reached after {current_duration:.1f}s")
                break

            print(f"\n[FunctionAI-Installer] ## Installing node {i}/{nodes_num}: {node_name}")
            self.install(node_name)
            completed_nodes = i

        total_duration = time.time() - start_time
        print(f"[FunctionAI-Installer] Nodes installed: {completed_nodes}/{nodes_num}, Total time: {total_duration:.1f}s")
        return self._history

    def install(self, node_name):
        node_path = os.path.join(constants.COMFYUI_DIR, "custom_nodes", node_name)
        if not os.path.isdir(node_path):
            return True

        requirements_path = os.path.join(node_path, "requirements.txt")
        install_script_path = os.path.join(node_path, "install.py")

        if os.path.exists(requirements_path):
            print(f"[FunctionAI-Installer] ## Installing pip packages in {requirements_path} ...")
            lines = file_ops.robust_readlines(requirements_path)
            for line in lines:
                package_name = self._extract_package_name(line)
                if not package_name or package_name in self.processed_install:
                    continue
                # TODO: 支持依赖的黑名单，安装时过滤指定依赖

                self.processed_install.add(package_name)
                install_cmd = self._construct_pip_cmd(["install", package_name])
                self._do_install(node_path, node_name, package_name, install_cmd)

        if os.path.exists(install_script_path):
            print(f"[FunctionAI-Installer] ## Installing {install_script_path} ...")
            self.processed_install.add(install_script_path)
            install_cmd = [constants.VENV_EXECUTABLE, "install.py"]
            self._do_install(node_path, node_name, "install.py", install_cmd)

    def _do_install(self, node_path, node_name, package_name, install_cmd):
        """执行安装并记录结果，每次执行仅涉及一个package或一个install.py"""
        start_time = time.time()
        record = InstallRecord(
            node_name=node_name,
            package_name=package_name,
        )

        try:
            record.success = self._install_script(node_path, install_cmd)
        except Exception as e:
            record.error_msg = str(e)
            record.success = False
        finally:
            record.duration = round(time.time() - start_time, 1)
            self._history.append(record.to_dict())

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
            print("[FunctionAI-Installer] ## Failed to retrieve the information of installed pip packages.")

        return installed_packages

    def _install_script(self, node_path, install_cmd):
        print(f"\n[FunctionAI-Installer] ## Execute => '{' '.join(install_cmd)}' in '{node_path}'")
        # FIXME: pip install --timeout 可能会导致依赖安装不完整，因此每个包安装时暂未引入超时时间
        code = subprocess.check_call(install_cmd, cwd=node_path, env=self._get_script_env())

        if code != 0:
            print(f"[FunctionAI-Installer] ## Failed to execute => '{' '.join(install_cmd)}' in '{node_path}'")
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

    @staticmethod
    def _construct_pip_cmd(cmd):
        return [constants.VENV_EXECUTABLE, '-m', 'pip'] + cmd
