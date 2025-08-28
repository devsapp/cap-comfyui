import unittest
import os
import tempfile
import shutil
import sys
import subprocess
from pathlib import Path

# 添加当前项目路径到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../../')))

from services.pip.pip_installer_optimized import PIPInstallerOptimized


class RealScenarioTest(unittest.TestCase):
    """真实场景测试：创建真实的venv环境，查看完整的安装日志效果"""

    def setUp(self):
        """测试初始化 - 创建真实的venv环境"""
        self.test_dir = tempfile.mkdtemp(prefix="pip_installer_test_")
        self.comfyui_dir = os.path.join(self.test_dir, "comfyui")
        self.custom_nodes_dir = os.path.join(self.comfyui_dir, "custom_nodes")
        self.venv_dir = os.path.join(self.test_dir, "test_venv")
        
        os.makedirs(self.custom_nodes_dir, exist_ok=True)
        
        print(f"\n创建测试环境在: {self.test_dir}")
        print(f"ComfyUI目录: {self.comfyui_dir}")
        print(f"虚拟环境目录: {self.venv_dir}")
        
        # 使用命令创建真实的虚拟环境
        print("\n创建虚拟环境...")
        try:
            subprocess.run([sys.executable, "-m", "venv", self.venv_dir], 
                         check=True, capture_output=True, timeout=60)
            print("✓ 虚拟环境创建成功")
        except subprocess.CalledProcessError as e:
            print(f"✗ 虚拟环境创建失败: {e.stderr.decode()}")
            raise
        except subprocess.TimeoutExpired:
            print("✗ 虚拟环境创建超时")
            raise
        
        # 设置虚拟环境的Python路径
        if sys.platform == "win32":
            self.venv_python = os.path.join(self.venv_dir, "Scripts", "python.exe")
        else:
            self.venv_python = os.path.join(self.venv_dir, "bin", "python")
        
        # 验证虚拟环境可用
        try:
            result = subprocess.run([self.venv_python, "--version"], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                print(f"✓ 虚拟环境Python: {result.stdout.strip()}")
            else:
                raise Exception(f"Python版本检查失败: {result.stderr}")
        except subprocess.TimeoutExpired:
            print("✗ Python版本检查超时")
            raise
        except Exception as e:
            print(f"✗ 虚拟环境验证失败: {e}")
            raise
        
        # 升级pip到最新版本
        print("\n升级pip...")
        try:
            subprocess.run([self.venv_python, "-m", "pip", "install", "--upgrade", "pip"], 
                         check=True, capture_output=True, timeout=120)
            print("✓ pip升级完成")
        except subprocess.CalledProcessError as e:
            print(f"⚠ pip升级失败: {e.stderr.decode()}")
            # 不抛出异常，继续测试
        except subprocess.TimeoutExpired:
            print("⚠ pip升级超时，继续使用现有版本")
        
        # 设置constants使用真实路径
        import constants
        self.original_comfyui_dir = getattr(constants, 'COMFYUI_DIR', None)
        self.original_venv_executable = getattr(constants, 'VENV_EXECUTABLE', None)
        
        constants.COMFYUI_DIR = self.comfyui_dir
        constants.VENV_EXECUTABLE = self.venv_python
        
        self._create_simple_test_nodes()
        
    def tearDown(self):
        """测试清理 - 删除venv环境"""
        # 恢复constants
        import constants
        if self.original_comfyui_dir is not None:
            constants.COMFYUI_DIR = self.original_comfyui_dir
        if self.original_venv_executable is not None:
            constants.VENV_EXECUTABLE = self.original_venv_executable
        
        # 删除测试目录
        print(f"清理测试环境: {self.test_dir}")
        try:
            shutil.rmtree(self.test_dir, ignore_errors=True)
            print("✓ 测试环境清理完成")
        except Exception as e:
            print(f"✗ 测试环境清理失败: {e}")

    def create_test_node_dir(self, node_name):
        """创建测试节点目录"""
        node_dir = os.path.join(self.custom_nodes_dir, node_name)
        os.makedirs(node_dir, exist_ok=True)
        return node_dir

    def create_requirements_file(self, node_dir, content):
        """创建 requirements.txt 文件"""
        req_file = os.path.join(node_dir, "requirements.txt")
        with open(req_file, "w") as f:
            f.write(content)
        return req_file
        
    def _create_simple_test_nodes(self):
        """创建3个简单的测试插件"""
        
        # 插件1: 基础工具插件
        self.node1_dir = self.create_test_node_dir("basic-tools")
        self.create_requirements_file(self.node1_dir, """
# 基础工具依赖 - 使用小的包便于测试
click>=7.0
colorama>=0.4.0
pytz>=2021.1
        """.strip())
        
        # 插件2: 数据处理插件
        self.node2_dir = self.create_test_node_dir("data-processor")
        self.create_requirements_file(self.node2_dir, """
# 数据处理依赖
click>=8.0  # 版本冲突测试
requests>=2.25.0
json5>=0.9.0
pyyaml>=5.4.0
        """.strip())
        
        # 插件3: 图像处理插件
        self.node3_dir = self.create_test_node_dir("image-helper")
        self.create_requirements_file(self.node3_dir, """
# 图像处理依赖
colorama>=0.3.0  # 低于上面的版本
chardet>=4.0.0
urllib3>=1.26.0
click  # 无版本要求
git+https://github.com/python/cpython.git  # git依赖测试（仅用于演示）
        """.strip())
        
        print(f"创建了3个测试插件: basic-tools, data-processor, image-helper")
    
    def test_install_all_direct(self):
        """直接调用install_all方法，观察完整安装日志"""
        
        print("\n==== 直接调用install_all方法测试 ====\n")
        
        # 创建安装器实例
        installer = PIPInstallerOptimized()
        
        # 打印环境信息
        print(f"虚拟环境: {self.venv_python}")
        print(f"自定义节点目录: {self.custom_nodes_dir}")
        
        # 只用特定的几个节点进行测试，避免安装所有节点
        nodes_map = {
            "basic-tools": {}, 
            "data-processor": {},
            "image-helper": {}
        }
        
        # 直接调用install_all方法
        try:
            result = installer.install_all(nodes_map=nodes_map)
            print(f"\n安装结果: {'成功' if result else '失败'}")
        except Exception as e:
            print(f"安装过程出错: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    print("="*60)
    print("PIP安装器优化版 - 直接调用测试")
    print("="*60)
    print("注意: 此测试会创建真实的venv环境并执行实际安装")
    print("测试完成后会自动清理环境")
    
    # 运行直接调用测试
    unittest.main(argv=['first-arg-is-ignored', 'test_install_all_direct'])
