import unittest
import os
import tempfile
import shutil
import sys
import subprocess
from pathlib import Path

# 添加当前项目路径到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../../')))

from services.pip.pip_installer import PIPInstaller


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
        installer = PIPInstaller()
        
        # 打印环境信息
        print(f"虚拟环境: {self.venv_python}")
        print(f"自定义节点目录: {self.custom_nodes_dir}")
        
        # 打印安装前的包基线
        baseline = installer.get_origin_packages()
        print(f"\n安装前包基线: {len(baseline)} 个包")
        print(f"示例: {list(baseline.keys())[:5]}" + ("..." if len(baseline) > 5 else ""))
        
        # 只用特定的几个节点进行测试，避免安装所有节点
        nodes_map = {
            "basic-tools": {}, 
            "data-processor": {},
            "image-helper": {}
        }
        
        # 直接调用install_all方法（使用较短的超时时间以便测试）
        try:
            result_map = installer.install_all(timeout=300, nodes_map=nodes_map)  # 5分钟超时
            
            # 打印新的结果结构
            print("\n\n==== 安装结果分析 ====\n")
            
            # 1. 基线信息
            print(f"1. 包基线: {len(result_map['baseline'])} 个包")
            
            # 2. 依赖安装结果
            dep_result = result_map.get('dependencies')
            if dep_result:
                dep_success = dep_result.get('success', False)
                dep_duration = dep_result.get('duration', 0)
                dep_requirements = dep_result.get('requirements_txt', '')
                dep_error = dep_result.get('error_msg', '')
                
                print(f"2. 依赖安装: {'✓ 成功' if dep_success else '✗ 失败'} (耗时: {dep_duration}s)")
                
                if dep_requirements:
                    dep_lines = dep_requirements.strip().split('\n')
                    print(f"   安装的依赖包 ({len(dep_lines)} 个):")
                    for line in dep_lines[:10]:  # 只显示前10个
                        print(f"   - {line}")
                    if len(dep_lines) > 10:
                        print(f"   ... 及其他 {len(dep_lines) - 10} 个包")
                else:
                    print("   无依赖包需要安装")
                    
                if dep_error:
                    print(f"   错误信息: {dep_error}")
            else:
                print("2. 依赖安装: 未执行")
            
            # 3. install.py 脚本安装结果
            script_results = result_map.get('scripts', [])
            print(f"\n3. install.py 脚本安装: {len(script_results)} 个脚本")
            
            success_count = len([r for r in script_results if r.get('success', False)])
            print(f"   成功/总数: {success_count}/{len(script_results)}")
            
            for script_result in script_results:
                node_name = script_result.get('node_name', 'Unknown')
                script_name = script_result.get('script_name', 'install.py')
                success = script_result.get('success', False)
                duration = script_result.get('duration', 0)
                error_msg = script_result.get('error_msg', '')
                
                status = '✓ 成功' if success else '✗ 失败'
                print(f"   - {node_name}/{script_name}: {status} ({duration}s)")
                if error_msg:
                    print(f"     错误: {error_msg[:100]}" + ("..." if len(error_msg) > 100 else ""))
            
            # 4. 总体结果评估
            overall_success = (
                dep_result and dep_result.get('success', False) and 
                success_count == len(script_results)
            )
            print(f"\n4. 总体结果: {'✓ 完全成功' if overall_success else '⚠ 部分成功或失败'}")
            
            return result_map
            
        except Exception as e:
            print(f"安装过程出错: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def test_install_with_blacklist(self):
        """测试带黑名单的安装"""
        print("\n==== 黑名单过滤测试 ====\n")
        
        # 创建带黑名单的安装器
        blacklist = ["colorama", "click"]  # 将一些常用包加入黑名单
        installer = PIPInstaller(blacklist=blacklist)
        
        print(f"黑名单: {blacklist}")
        
        # 使用部分节点进行测试
        nodes_map = {
            "basic-tools": {},  # 这个插件依赖于 click 和 colorama
            "data-processor": {}  # 这个插件依赖于 click
        }
        
        try:
            result_map = installer.install_all(timeout=200, nodes_map=nodes_map)
            
            # 分析黑名单过滤效果
            dep_result = result_map.get('dependencies')
            if dep_result and dep_result.get('requirements_txt'):
                requirements_lines = dep_result['requirements_txt'].strip().split('\n')
                print(f"\n实际安装的依赖 ({len(requirements_lines)} 个):")
                for line in requirements_lines:
                    print(f"  - {line}")
                
                # 检查黑名单是否生效
                blacklisted_found = []
                for blacklisted_pkg in blacklist:
                    for line in requirements_lines:
                        if line.lower().startswith(blacklisted_pkg.lower()):
                            blacklisted_found.append(line)
                
                if blacklisted_found:
                    print(f"\n⚠ 发现黑名单包未被过滤: {blacklisted_found}")
                else:
                    print(f"\n✓ 黑名单过滤正常，无黑名单包被安装")
            else:
                print("\n无依赖包需要安装")
                
            return result_map
            
        except Exception as e:
            print(f"黑名单测试出错: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def test_empty_nodes_map(self):
        """测试空节点映射的情况"""
        print("\n==== 空节点映射测试 ====\n")
        
        installer = PIPInstaller()
        
        try:
            # 传递空字典，应该不安装任何节点
            result_map = installer.install_all(timeout=60, nodes_map={})
            
            print("\n空节点映射结果:")
            print(f"  基线包数量: {len(result_map['baseline'])}")
            
            dep_result = result_map.get('dependencies')
            if dep_result:
                print(f"  依赖安装: {'成功' if dep_result.get('success') else '失败'} (耗时: {dep_result.get('duration', 0)}s)")
                print(f"  requirements.txt: '{dep_result.get('requirements_txt', '')}'") 
            
            script_results = result_map.get('scripts', [])
            print(f"  install.py 脚本: {len(script_results)} 个")
            
            expected_empty = (
                len(script_results) == 0 and 
                dep_result and dep_result.get('success') and 
                not dep_result.get('requirements_txt', '').strip()
            )
            
            print(f"\n结果检查: {'✓ 符合预期（无安装任何内容）' if expected_empty else '⚠ 与预期不符'}")
            
            return result_map
            
        except Exception as e:
            print(f"空节点映射测试出错: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def test_timeout_scenario(self):
        """测试超时停止场景 - 模拟长时间安装触发超时机制"""
        print("\n==== 超时停止测试 ====\n")
        
        # 创建一个特殊的测试节点，包含大型包或慢速安装的包
        timeout_node_dir = self.create_test_node_dir("timeout-test-node")
        
        # 创建一个会导致较长安装时间的 requirements.txt
        # 这里使用一些需要编译的包或者大型包
        timeout_requirements = """
# 这些包可能需要较长时间安装（用于触发超时）
numpy>=1.20.0    # 编译需要时间
scipy>=1.7.0     # 大型包，依赖较多
pandas>=1.3.0    # 大型数据分析包
matplotlib>=3.4.0  # 图形包，依赖较多
scikit-learn>=1.0.0  # 机器学习包，非常大
tensorflow>=2.6.0    # 最大的机器学习框架之一
torch>=1.9.0         # PyTorch，另一个大型框架
        """.strip()
        
        self.create_requirements_file(timeout_node_dir, timeout_requirements)
        print(f"创建了超时测试节点: timeout-test-node")
        print("包含的大型包: numpy, scipy, pandas, matplotlib, scikit-learn, tensorflow, torch")
        
        installer = PIPInstaller()
        
        # 使用非常短的超时时间来快速触发超时
        short_timeout = 30  # 30秒超时，对于安装 TensorFlow 等大包远远不够
        
        nodes_map = {
            "timeout-test-node": {}
        }
        
        print(f"\n设置超时时间: {short_timeout} 秒")
        print("注意: 由于需要安装大型包，超时几乎是必然的")
        print("开始安装测试...")
        
        import time
        start_test_time = time.time()
        
        try:
            result_map = installer.install_all(timeout=short_timeout, nodes_map=nodes_map)
            
            test_duration = time.time() - start_test_time
            print(f"\n测试完成，总耗时: {test_duration:.1f} 秒")
            
            # 分析超时结果
            print("\n==== 超时结果分析 ====\n")
            
            dep_result = result_map.get('dependencies')
            if dep_result:
                dep_success = dep_result.get('success', False)
                dep_duration = dep_result.get('duration', 0)
                dep_error = dep_result.get('error_msg', '')
                
                print(f"1. 依赖安装结果: {'✓ 成功' if dep_success else '✗ 失败'} (耗时: {dep_duration}s)")
                
                if not dep_success and dep_error:
                    print(f"   错误信息: {dep_error}")
                    
                    # 检查是否是超时错误
                    timeout_indicators = [
                        "timed out", 
                        "timeout", 
                        "TimeoutExpired", 
                        "Hard timeout",
                        "Timeout ("
                    ]
                    
                    is_timeout_error = any(indicator in dep_error for indicator in timeout_indicators)
                    
                    if is_timeout_error:
                        print(f"   ✓ 确认超时错误：超时机制正常工作")
                        
                        # 检查是否在预期时间内停止
                        if dep_duration <= short_timeout + 10:  # 允许10秒误差
                            print(f"   ✓ 超时控制正常：在 {short_timeout}s(+10s误差) 内停止")
                        else:
                            print(f"   ⚠ 超时控制异常：实际耗时 {dep_duration}s 超出预期")
                    else:
                        print(f"   ⚠ 非超时错误，可能是其他问题")
                else:
                    print(f"   ⚠ 意外成功：在 {short_timeout}s 内完成了大型包安装")
            
            # 检查 install.py 脚本是否被执行
            script_results = result_map.get('scripts', [])
            print(f"\n2. install.py 脚本结果: {len(script_results)} 个脚本")
            
            if not script_results:
                print("   ✓ 正常：由于依赖安装超时，未执行 install.py 脚本")
            else:
                for script_result in script_results:
                    node_name = script_result.get('node_name', 'Unknown')
                    success = script_result.get('success', False)
                    print(f"   - {node_name}: {'✓ 成功' if success else '✗ 失败'}")
            
            # 总结
            print(f"\n3. 超时测试总结:")
            if dep_result and not dep_result.get('success') and 'timeout' in dep_result.get('error_msg', '').lower():
                print("   ✓ 超时机制正常工作")
                print("   ✓ 安装进程在超时后被正确停止")
                print("   ✓ 返回了完整的错误信息")
            else:
                print("   ⚠ 超时测试结果与预期不符")
            
            return result_map
            
        except Exception as e:
            test_duration = time.time() - start_test_time
            print(f"\n超时测试抛出异常 (耗时: {test_duration:.1f}s): {e}")
            
            # 检查是否是预期的超时异常
            if "TimeoutError" in str(type(e)) or "timeout" in str(e).lower():
                print("   ✓ 确认为超时异常，超时机制工作正常")
            else:
                print("   ⚠ 非超时异常，可能是其他问题")
                
            import traceback
            traceback.print_exc()
            return None
    
    def test_lightweight_timeout(self):
        """轻量级超时测试 - 使用模拟慢速安装的小包"""
        print("\n==== 轻量级超时测试 ====\n")
        
        # 创建一个包含一些小包但使用极短超时的测试
        lightweight_node_dir = self.create_test_node_dir("lightweight-timeout-node")
        
        lightweight_requirements = """
# 轻量级包，但使用极短超时来模拟超时场景
requests>=2.25.0
click>=8.0
colorama>=0.4.0
pytz>=2021.1
json5>=0.9.0
        """.strip()
        
        self.create_requirements_file(lightweight_node_dir, lightweight_requirements)
        print(f"创建了轻量级超时测试节点")
        
        installer = PIPInstaller()
        
        # 使用极短的超时时间（2秒）
        very_short_timeout = 2
        
        nodes_map = {
            "lightweight-timeout-node": {}
        }
        
        print(f"\n设置极短超时时间: {very_short_timeout} 秒")
        print("注意: 即使是小包，5秒也很难完成安装")
        
        import time
        start_test_time = time.time()
        
        try:
            result_map = installer.install_all(timeout=very_short_timeout, nodes_map=nodes_map)
            
            test_duration = time.time() - start_test_time
            print(f"\n轻量级测试完成，耗时: {test_duration:.1f} 秒")
            
            # 分析结果
            dep_result = result_map.get('dependencies')
            if dep_result:
                dep_success = dep_result.get('success', False)
                dep_error = dep_result.get('error_msg', '')
                
                print(f"依赖安装: {'✓ 成功' if dep_success else '✗ 失败'}")
                
                if not dep_success and 'timeout' in dep_error.lower():
                    print(f"✓ 轻量级超时测试成功：触发超时机制")
                elif dep_success:
                    print(f"⚠ 意外完成：在 {very_short_timeout}s 内完成安装 (可能网络非常快或包已缓存)")
            
            return result_map
            
        except Exception as e:
            test_duration = time.time() - start_test_time
            print(f"\n轻量级超时测试异常 (耗时: {test_duration:.1f}s): {e}")
            return None
    
    def test_nunchaku_custom_strategy(self):
        """测试 ComfyUI-nunchaku 定制化依赖策略"""
        print("\n==== ComfyUI-nunchaku 定制化策略测试 ====\n")
        
        # 创建 ComfyUI-nunchaku 测试节点
        nunchaku_node_dir = self.create_test_node_dir("ComfyUI-nunchaku")
        
        # 为 nunchaku 节点创建一个基本的 requirements.txt
        nunchaku_requirements = """
# ComfyUI-nunchaku 基础依赖
requests>=2.25.0
click>=8.0
        """.strip()
        
        self.create_requirements_file(nunchaku_node_dir, nunchaku_requirements)
        print(f"创建了 ComfyUI-nunchaku 测试节点")
        
        installer = PIPInstaller()
        
        # 测试情景1: nunchaku 版本为 v1.0.0，应该添加定制 wheel
        print("\n--- 测试情景1: nunchaku v1.0.0 ---")
        
        nodes_map_v1 = {
            "ComfyUI-nunchaku": {
                "name": "ComfyUI-nunchaku",
                "source": {
                    "webUrl": "https://github.com/nunchaku-tech/ComfyUI-nunchaku",
                    "type": "github",
                    "cloneUrl": "https://github.com/nunchaku-tech/ComfyUI-nunchaku.git"
                },
                "version": {
                    "type": "tag",
                    "value": "v1.0.0"
                }
            }
        }
        
        try:
            result_map_v1 = installer.install_all(timeout=10, nodes_map=nodes_map_v1)
            
            # 分析结果 - 检查是否添加了 nunchaku wheel
            dep_result_v1 = result_map_v1.get('dependencies')
            if dep_result_v1 and dep_result_v1.get('requirements_txt'):
                requirements_lines = dep_result_v1['requirements_txt'].strip().split('\n')
                print(f"\n实际安装的依赖 ({len(requirements_lines)} 个):")
                
                nunchaku_wheel_found = False
                expected_wheel_url = "https://modelscope.cn/models/nunchaku-tech/nunchaku/resolve/master/nunchaku-1.0.0+torch2.6-cp310-cp310-linux_x86_64.whl"
                
                for line in requirements_lines:
                    print(f"  - {line}")
                    if expected_wheel_url in line:
                        nunchaku_wheel_found = True
                
                if nunchaku_wheel_found:
                    print(f"\n✓ 成功: 检测到 nunchaku v1.0.0，已添加定制 wheel URL")
                    print(f"  Wheel URL: {expected_wheel_url}")
                else:
                    print(f"\n⚠ 失败: 未找到预期的 nunchaku wheel URL")
                    print(f"  预期: {expected_wheel_url}")
            else:
                print("\n⚠ 无依赖包需要安装")
            
        except Exception as e:
            print(f"nunchaku v1.0.0 测试出错: {e}")
            import traceback
            traceback.print_exc()
        
        # 测试情景2: nunchaku 版本为 v0.2.0，不应该添加定制 wheel
        print("\n--- 测试情景2: nunchaku v0.2.0 ---")
        
        nodes_map_v0 = {
            "ComfyUI-nunchaku": {
                "name": "ComfyUI-nunchaku",
                "source": {
                    "webUrl": "https://github.com/nunchaku-tech/ComfyUI-nunchaku",
                    "type": "github",
                    "cloneUrl": "https://github.com/nunchaku-tech/ComfyUI-nunchaku.git"
                },
                "version": {
                    "type": "tag",
                    "value": "v0.2.0"
                }
            }
        }
        
        try:
            # 创建新的安装器实例以避免状态干扰
            installer_v0 = PIPInstaller()
            result_map_v0 = installer_v0.install_all(timeout=10, nodes_map=nodes_map_v0)
            
            # 分析结果 - 检查是否没有添加 nunchaku wheel
            dep_result_v0 = result_map_v0.get('dependencies')
            if dep_result_v0 and dep_result_v0.get('requirements_txt'):
                requirements_lines = dep_result_v0['requirements_txt'].strip().split('\n')
                print(f"\n实际安装的依赖 ({len(requirements_lines)} 个):")
                
                nunchaku_wheel_found = False
                expected_wheel_url = "https://modelscope.cn/models/nunchaku-tech/nunchaku/resolve/master/nunchaku-1.0.0+torch2.6-cp310-cp310-linux_x86_64.whl"
                
                for line in requirements_lines:
                    print(f"  - {line}")
                    if expected_wheel_url in line:
                        nunchaku_wheel_found = True
                
                if not nunchaku_wheel_found:
                    print(f"\n✓ 成功: nunchaku v0.2.0 未添加定制 wheel，符合预期")
                else:
                    print(f"\n⚠ 失败: nunchaku v0.2.0 不应该添加定制 wheel")
            else:
                print(f"\n✓ 正常: nunchaku v0.2.0 无需安装额外依赖")
            
        except Exception as e:
            print(f"nunchaku v0.2.0 测试出错: {e}")
            import traceback
            traceback.print_exc()
        
        # 测试情景3: 没有 ComfyUI-nunchaku 节点
        print("\n--- 测试情景3: 无 nunchaku 节点 ---")
        
        nodes_map_no_nunchaku = {
            "basic-tools": {},
            "data-processor": {}
        }
        
        try:
            installer_no_nunchaku = PIPInstaller()
            result_map_no_nunchaku = installer_no_nunchaku.install_all(timeout=10, nodes_map=nodes_map_no_nunchaku)
            
            # 分析结果 - 确认没有 nunchaku 相关处理
            dep_result_no_nunchaku = result_map_no_nunchaku.get('dependencies')
            if dep_result_no_nunchaku and dep_result_no_nunchaku.get('requirements_txt'):
                requirements_lines = dep_result_no_nunchaku['requirements_txt'].strip().split('\n')
                
                nunchaku_wheel_found = any(
                    "nunchaku" in line.lower() and "modelscope.cn" in line
                    for line in requirements_lines
                )
                
                if not nunchaku_wheel_found:
                    print(f"\n✓ 成功: 无 nunchaku 节点时未触发定制策略")
                else:
                    print(f"\n⚠ 异常: 无 nunchaku 节点但检测到 nunchaku wheel")
            else:
                print(f"\n✓ 正常: 无 nunchaku 节点时无需安装任何依赖")
            
        except Exception as e:
            print(f"无 nunchaku 节点测试出错: {e}")
            import traceback
            traceback.print_exc()
        
        # 测试情景4: 无效的 nodes_map 结构
        print("\n--- 测试情景4: 无效的 nodes_map 结构 ---")
        
        # 测试缺少 version 字段的情况
        nodes_map_invalid = {
            "ComfyUI-nunchaku": {
                "name": "ComfyUI-nunchaku",
                "source": {
                    "webUrl": "https://github.com/nunchaku-tech/ComfyUI-nunchaku",
                    "type": "github"
                }
                # 没有 version 字段
            }
        }
        
        try:
            installer_invalid = PIPInstaller()
            result_map_invalid = installer_invalid.install_all(timeout=10, nodes_map=nodes_map_invalid)
            
            # 分析结果 - 应该能够处理无效结构而不崩溃
            dep_result_invalid = result_map_invalid.get('dependencies')
            if dep_result_invalid:
                print(f"\n✓ 成功: 处理无效 nodes_map 结构而不崩溃")
                
                # 检查是否没有添加 nunchaku wheel
                if dep_result_invalid.get('requirements_txt'):
                    requirements_lines = dep_result_invalid['requirements_txt'].strip().split('\n')
                    nunchaku_wheel_found = any(
                        "nunchaku" in line.lower() and "modelscope.cn" in line
                        for line in requirements_lines
                    )
                    
                    if not nunchaku_wheel_found:
                        print(f"  ✓ 正确: 无效版本信息时未添加 nunchaku wheel")
                    else:
                        print(f"  ⚠ 异常: 无效版本信息但仍添加了 nunchaku wheel")
                else:
                    print(f"  ✓ 无依赖需要安装")
            
        except Exception as e:
            print(f"无效 nodes_map 测试出错: {e}")
            import traceback
            traceback.print_exc()
        
        print("\n==== nunchaku 定制化策略测试完成 ====\n")
        
        return {
            "v1.0.0": result_map_v1 if 'result_map_v1' in locals() else None,
            "v0.2.0": result_map_v0 if 'result_map_v0' in locals() else None,
            "no_nunchaku": result_map_no_nunchaku if 'result_map_no_nunchaku' in locals() else None,
            "invalid": result_map_invalid if 'result_map_invalid' in locals() else None
        }


if __name__ == "__main__":
    import sys
    
    print("="*60)
    print("PIP安装器优化版 - 真实场景测试")
    print("="*60)
    print("注意: 此测试会创建真实的venv环境并执行实际安装")
    print("测试完成后会自动清理环境")
    print()
    
    # 可用的测试方法
    available_tests = {
        '1': 'test_install_all_direct',
        '2': 'test_install_with_blacklist', 
        '3': 'test_empty_nodes_map',
        '4': 'test_timeout_scenario',
        '5': 'test_lightweight_timeout',
        '6': 'test_nunchaku_custom_strategy',
        'all': 'RealScenarioTest'  # 运行所有测试
    }
    
    print("可用的测试:")
    print("  1. 直接安装测试 (test_install_all_direct)")
    print("  2. 黑名单过滤测试 (test_install_with_blacklist)")
    print("  3. 空节点映射测试 (test_empty_nodes_map)")
    print("  4. 超时停止测试 (test_timeout_scenario) - 使用大型包")
    print("  5. 轻量级超时测试 (test_lightweight_timeout) - 使用极短超时")
    print("  6. ComfyUI-nunchaku 定制策略测试 (test_nunchaku_custom_strategy)")
    print("  all. 运行所有测试")
    print()
    
    # 检查命令行参数
    if len(sys.argv) > 1:
        test_choice = sys.argv[1]
    else:
        test_choice = input("请选择要运行的测试 (1/2/3/4/5/6/all, 默认为 1): ").strip() or '1'
    
    if test_choice in available_tests:
        test_name = available_tests[test_choice]
        print(f"\n开始运行测试: {test_name}")
        print("-" * 40)
        
        if test_choice == 'all':
            # 运行所有测试
            unittest.main(argv=['first-arg-is-ignored'], exit=False, verbosity=2)
        else:
            # 运行特定测试
            unittest.main(argv=['first-arg-is-ignored', test_name], exit=False, verbosity=2)
    else:
        print(f"无效的选择: {test_choice}")
        print("请选择 1, 2, 3, 4, 5, 6 或 all")
