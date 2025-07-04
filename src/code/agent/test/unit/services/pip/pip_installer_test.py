import json
import os
import unittest
import venv
import subprocess

import constants
from services.pip.pip_installer import PIPInstaller


class TestPIPManager(unittest.TestCase):
    def setUp(self):
        # 创建测试目录结构
        self.test_base_dir = os.path.join(os.path.dirname(__file__), "test_env")
        self.test_comfyui_dir = os.path.join(self.test_base_dir, "comfyui")
        self.test_venv_dir = os.path.join(self.test_base_dir, "venv")
        self.custom_nodes_dir = os.path.join(self.test_comfyui_dir, "custom_nodes")

        # 创建目录
        os.makedirs(self.test_base_dir, exist_ok=True)
        os.makedirs(self.test_comfyui_dir, exist_ok=True)
        os.makedirs(self.custom_nodes_dir, exist_ok=True)

        # 创建虚拟环境
        print(f"Creating virtual environment in {self.test_venv_dir}")
        builder = venv.EnvBuilder(with_pip=True)
        builder.create(self.test_venv_dir)

        # 设置常量
        constants.COMFYUI_DIR = self.test_comfyui_dir
        constants.VENV_EXECUTABLE = os.path.join(self.test_venv_dir, "bin", "python")

        # # 升级pip以确保安装过程顺畅
        # subprocess.check_call([
        #     constants.VENV_EXECUTABLE,
        #     "-m", "pip",
        #     "install",
        #     "--upgrade",
        #     "pip"
        # ])

    def tearDown(self):
        """Clean up test directories"""
        import shutil
        if os.path.exists(self.test_base_dir):
            print(f"Cleaning up test environment: {self.test_base_dir}")
            shutil.rmtree(self.test_base_dir, ignore_errors=True)

    def create_test_node(self, node_name, requirements=None, install_script=None):
        """Helper method to create test node with requirements and install script"""
        node_dir = os.path.join(self.custom_nodes_dir, node_name)
        os.makedirs(node_dir, exist_ok=True)

        if requirements:
            with open(os.path.join(node_dir, "requirements.txt"), "w") as f:
                f.write(requirements)

        if install_script:
            with open(os.path.join(node_dir, "install.py"), "w") as f:
                f.write(install_script)

        return node_dir

    def test_install_all(self):
        """Test installing multiple nodes with different configurations"""
        # 首先在虚拟环境中预装一些包
        subprocess.check_call([
            constants.VENV_EXECUTABLE,
            "-m", "pip",
            "install",
            "requests==2.31.0"  # 预装requests包
        ])

        # 创建测试节点
        # 节点1：包含已安装的包(requests)和未安装的包(PyYAML)
        requirements1 = """
        requests==2.30.0
        PyYAML==6.0.1
        """
        self.create_test_node("node1", requirements=requirements1)

        # 节点2：带有install.py
        install_script = """
        import subprocess
        import sys
        subprocess.check_call([sys.executable, "-m", "pip", "install", "six==1.16.0"])
        print("Installation completed")
        """
        self.create_test_node("node2", install_script=install_script)

        # 创建新的installer实例
        pip_installer = PIPInstaller()

        # 执行install_all
        history = pip_installer.install_all()

        # 验证安装历史记录
        print(json.dumps(history, indent=2))
        print(json.dumps(pip_installer.get_origin_packages(), indent=2))

        # # 验证requests包被跳过（不应该出现在安装历史中）
        # self.assertFalse(any(
        #     record["package_name"].startswith("requests")
        #     for record in history
        # ), "requests package should have been skipped")
        #
        # # 验证PyYAML被安装（应该出现在安装历史中）
        # self.assertTrue(any(
        #     record["package_name"].startswith("PyYAML")
        #     for record in history
        # ), "PyYAML package should have been installed")
        #
        # # 验证install.py被执行
        # self.assertTrue(any(
        #     record["package_name"] == "install.py"
        #     for record in history
        # ), "install.py should have been executed")
        #
        # # 验证最终所有包都已正确安装
        # try:
        #     output = subprocess.check_output([
        #         constants.VENV_EXECUTABLE,
        #         "-c",
        #         "import requests, yaml, six; print('Success')"
        #     ]).decode().strip()
        #     self.assertEqual(output, "Success")
        # except subprocess.CalledProcessError:
        #     self.fail("Not all packages were properly installed")
        #
        # # 验证每个安装记录都包含必要的信息
        # for record in history:
        #     self.assertIn('node_name', record)
        #     self.assertIn('package_name', record)
        #     self.assertIn('duration', record)
        #     self.assertIn('success', record)
        #     self.assertIn('error_msg', record)

    def test_install_with_requirements(self):
        """Test installing packages from requirements.txt"""
        requirements = """
        requests==2.31.0
        PyYAML==6.0.1
        """
        self.create_test_node("test_node", requirements=requirements)

        self.pip_installer.install("test_node")

        # 验证包是否真实安装成功
        try:
            # 检查是否可以导入已安装的包
            output = subprocess.check_output([
                constants.VENV_EXECUTABLE,
                "-c",
                "import requests, yaml; print('Success')"
            ]).decode().strip()
            self.assertEqual(output, "Success")
        except subprocess.CalledProcessError:
            self.fail("Packages were not properly installed")

    def test_install_with_install_script(self):
        """Test executing install.py script"""
        install_script = """
import subprocess
import sys

# 在install.py中安装一个包
subprocess.check_call([sys.executable, "-m", "pip", "install", "six==1.16.0"])
print("Installation completed")
        """
        self.create_test_node("test_node", install_script=install_script)

        result = self.pip_installer.install("test_node")
        self.assertTrue(result)

        # 验证install.py安装的包是否成功
        try:
            output = subprocess.check_output([
                constants.VENV_EXECUTABLE,
                "-c",
                "import six; print('Success')"
            ]).decode().strip()
            self.assertEqual(output, "Success")
        except subprocess.CalledProcessError:
            self.fail("Package 'six' was not properly installed")

    def test_install_invalid_package(self):
        """Test installing invalid package"""
        requirements = "invalid-package-name-that-does-not-exist==1.0.0"
        self.create_test_node("test_node", requirements=requirements)

        result = self.pip_installer.install("test_node")
        self.assertFalse(result)

    def test_install_duplicate_package(self):
        """Test installing same package multiple times"""
        requirements = """
        six==1.16.0
        six==1.16.0
        """
        self.create_test_node("test_node", requirements=requirements)

        result = self.pip_installer.install("test_node")
        self.assertTrue(result)

        # 验证包是否只安装了一次
        try:
            output = subprocess.check_output([
                constants.VENV_EXECUTABLE,
                "-c",
                "import six; print('Success')"
            ]).decode().strip()
            self.assertEqual(output, "Success")
        except subprocess.CalledProcessError:
            self.fail("Package 'six' was not properly installed")

