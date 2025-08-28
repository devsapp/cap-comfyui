import unittest
from unittest.mock import Mock, patch, mock_open, MagicMock
import os
import tempfile
import shutil

from services.pip.pip_installer_optimized import PIPInstallerOptimized, DependencyInfo


class TestPIPInstallerOptimized(unittest.TestCase):
    def setUp(self):
        """测试初始化"""
        self.test_dir = tempfile.mkdtemp()
        self.comfyui_dir = os.path.join(self.test_dir, "comfyui")
        self.custom_nodes_dir = os.path.join(self.comfyui_dir, "custom_nodes")
        os.makedirs(self.custom_nodes_dir, exist_ok=True)
        
        # Mock constants
        self.constants_patcher = patch('services.pip.pip_installer_optimized.constants')
        self.mock_constants = self.constants_patcher.start()
        self.mock_constants.COMFYUI_DIR = self.comfyui_dir
        self.mock_constants.VENV_EXECUTABLE = "/test/venv/bin/python"
        
    def tearDown(self):
        """测试清理"""
        self.constants_patcher.stop()
        shutil.rmtree(self.test_dir, ignore_errors=True)

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

    def create_install_script(self, node_dir, content):
        """创建 install.py 脚本"""
        install_file = os.path.join(node_dir, "install.py")
        with open(install_file, "w") as f:
            f.write(content)
        return install_file


class TestPIPInstallerOptimizedInit(TestPIPInstallerOptimized):
    """测试初始化功能"""

    @patch('services.pip.pip_installer_optimized.subprocess.check_output')
    def test_init_without_blacklist(self, mock_subprocess):
        """测试不带黑名单的初始化"""
        mock_subprocess.return_value = "Package Version\\nrequests 2.28.0\\nnumpy 1.21.0"
        
        installer = PIPInstallerOptimized()
        
        self.assertEqual(installer.blacklist, set())
        self.assertIsInstance(installer._origin_packages, dict)
        self.assertEqual(len(installer._history), 0)

    @patch('services.pip.pip_installer_optimized.subprocess.check_output')
    def test_init_with_blacklist(self, mock_subprocess):
        """测试带黑名单的初始化"""
        mock_subprocess.return_value = "Package Version\\nrequests 2.28.0"
        blacklist = ["torch", "tensorflow"]
        
        installer = PIPInstallerOptimized(blacklist=blacklist)
        
        self.assertEqual(installer.blacklist, {"torch", "tensorflow"})


class TestPackageSpecParsing(TestPIPInstallerOptimized):
    """测试包规范解析功能"""

    def setUp(self):
        super().setUp()
        with patch('services.pip.pip_installer_optimized.subprocess.check_output'):
            self.installer = PIPInstallerOptimized()

    def test_parse_regular_package_with_version(self):
        """测试普通包带版本的解析"""
        test_cases = [
            ("torch>=1.8.0", ("torch", ">=1.8.0")),
            ("numpy==1.21.0", ("numpy", "==1.21.0")),
            ("requests>=2.25.0,<3.0.0", ("requests", ">=2.25.0,<3.0.0")),
            ("pillow>=8.0.0,!=8.3.0", ("pillow", ">=8.0.0,!=8.3.0")),
        ]
        
        for package_spec, expected in test_cases:
            with self.subTest(package_spec=package_spec):
                result = self.installer._parse_package_spec(package_spec)
                self.assertEqual(result, expected)

    def test_parse_regular_package_without_version(self):
        """测试普通包不带版本的解析"""
        result = self.installer._parse_package_spec("requests")
        self.assertEqual(result, ("requests", ""))

    def test_parse_git_dependencies(self):
        """测试 git+ 依赖的解析"""
        test_cases = [
            "git+https://github.com/user/repo.git",
            "git+https://github.com/user/repo.git@main",
            "git+https://github.com/user/repo.git#egg=package",
            "hg+https://bitbucket.org/user/repo",
            "svn+https://svn.example.com/repo",
            "bzr+https://bzr.example.com/repo",
        ]
        
        for git_url in test_cases:
            with self.subTest(git_url=git_url):
                result = self.installer._parse_package_spec(git_url)
                self.assertEqual(result, (git_url, ""))

    def test_parse_invalid_package_spec(self):
        """测试无效包规范的解析"""
        result = self.installer._parse_package_spec("invalid@#$%^&*()")
        self.assertEqual(result, ("invalid@#$%^&*()", ""))


class TestVersionConflictResolution(TestPIPInstallerOptimized):
    """测试版本冲突解决功能"""

    def setUp(self):
        super().setUp()
        with patch('services.pip.pip_installer_optimized.subprocess.check_output'):
            self.installer = PIPInstallerOptimized()

    def test_exact_vs_exact_newer_wins(self):
        """测试精确版本 vs 精确版本：选择较新的"""
        result = self.installer._resolve_version_conflict("==1.0.0", "==2.0.0", "torch")
        self.assertEqual(result, "==2.0.0")

    def test_exact_vs_exact_keep_newer(self):
        """测试精确版本 vs 精确版本：保持较新的"""
        result = self.installer._resolve_version_conflict("==2.0.0", "==1.0.0", "torch")
        self.assertEqual(result, "==2.0.0")

    def test_exact_vs_range_keep_exact(self):
        """测试精确版本 vs 范围版本：保持精确版本"""
        result = self.installer._resolve_version_conflict("==1.5.0", ">=1.0.0", "numpy")
        self.assertEqual(result, "==1.5.0")

    def test_range_vs_exact_choose_exact(self):
        """测试范围版本 vs 精确版本：选择精确版本"""
        result = self.installer._resolve_version_conflict(">=1.0.0", "==1.5.0", "numpy")
        self.assertEqual(result, "==1.5.0")

    @patch('services.pip.pip_installer_optimized.PIPInstallerOptimized._try_merge_version_ranges')
    def test_range_vs_range_merge(self, mock_merge):
        """测试范围版本 vs 范围版本：尝试合并"""
        mock_merge.return_value = ">=1.5.0"
        
        result = self.installer._resolve_version_conflict(">=1.0.0", ">=1.5.0", "torch")
        
        mock_merge.assert_called_once_with(">=1.0.0", ">=1.5.0")
        self.assertEqual(result, ">=1.5.0")

    def test_same_version_specs(self):
        """测试相同版本规范"""
        result = self.installer._resolve_version_conflict(">=1.0.0", ">=1.0.0", "torch")
        self.assertEqual(result, ">=1.0.0")

    def test_empty_specs(self):
        """测试空版本规范"""
        result = self.installer._resolve_version_conflict("", ">=1.0.0", "torch")
        self.assertEqual(result, ">=1.0.0")
        
        result = self.installer._resolve_version_conflict(">=1.0.0", "", "torch")
        self.assertEqual(result, ">=1.0.0")


class TestVersionRangeMerging(TestPIPInstallerOptimized):
    """测试版本范围合并功能"""

    def setUp(self):
        super().setUp()
        with patch('services.pip.pip_installer_optimized.subprocess.check_output'):
            self.installer = PIPInstallerOptimized()

    @patch('services.pip.pip_installer_optimized.PIPInstallerOptimized._try_merge_with_packaging')
    def test_merge_with_packaging_success(self, mock_packaging):
        """测试使用 packaging 库成功合并"""
        mock_packaging.return_value = ">=1.5.0,<2.0.0"
        
        result = self.installer._try_merge_version_ranges(">=1.0.0,<2.0.0", ">=1.5.0,<3.0.0")
        
        self.assertEqual(result, ">=1.5.0,<2.0.0")
        mock_packaging.assert_called_once()

    @patch('services.pip.pip_installer_optimized.PIPInstallerOptimized._try_merge_with_packaging')
    @patch('services.pip.pip_installer_optimized.PIPInstallerOptimized._try_merge_simple_ranges')
    def test_merge_fallback_to_simple(self, mock_simple, mock_packaging):
        """测试回退到简单合并逻辑"""
        mock_packaging.return_value = None
        mock_simple.return_value = ">=1.5.0"
        
        result = self.installer._try_merge_version_ranges(">=1.0.0", ">=1.5.0")
        
        self.assertEqual(result, ">=1.5.0")
        mock_packaging.assert_called_once()
        mock_simple.assert_called_once()

    def test_simple_range_merge_success(self):
        """测试简单范围合并成功"""
        result = self.installer._try_merge_simple_ranges(">=1.0.0", ">=1.5.0")
        self.assertEqual(result, ">=1.5.0")
        
        result = self.installer._try_merge_simple_ranges(">=2.0.0", ">=1.5.0")
        self.assertEqual(result, ">=2.0.0")

    def test_simple_range_merge_failure(self):
        """测试简单范围合并失败"""
        result = self.installer._try_merge_simple_ranges(">=1.0.0,<2.0.0", ">=1.5.0")
        self.assertIsNone(result)

    @patch('builtins.__import__')
    def test_merge_with_packaging_import_error(self, mock_import):
        """测试 packaging 库导入失败"""
        mock_import.side_effect = ImportError("No module named 'packaging'")
        
        result = self.installer._try_merge_with_packaging(">=1.0.0", ">=1.5.0")
        
        self.assertIsNone(result)


class TestDependencyFiltering(TestPIPInstallerOptimized):
    """测试依赖过滤功能"""

    def setUp(self):
        super().setUp()
        with patch('services.pip.pip_installer_optimized.subprocess.check_output') as mock_subprocess:
            mock_subprocess.return_value = "Package Version\nrequests 2.28.0\nnumpy 1.21.0"
            self.installer = PIPInstallerOptimized(blacklist=["torch", "tensorflow"])

    def test_filter_git_dependencies(self):
        """测试过滤 git+ 依赖"""
        self.installer._merged_dependencies = {
            "git+https://github.com/user/repo.git": DependencyInfo(
                package_name="git+https://github.com/user/repo.git",
                version_spec="",
                original_line="git+https://github.com/user/repo.git",
                source_nodes=["node1"]
            ),
            "numpy": DependencyInfo(
                package_name="numpy",
                version_spec=">=1.20.0",
                original_line="numpy>=1.20.0",
                source_nodes=["node1"]
            )
        }
        
        with patch('builtins.print'):  # Suppress print output
            filtered = self.installer._filter_dependencies()
        
        self.assertNotIn("git+https://github.com/user/repo.git", filtered)
        # numpy虽然已安装，但有版本要求，不应被过滤（让pip处理版本升级）
        self.assertIn("numpy", filtered)

    def test_filter_blacklisted_packages(self):
        """测试过滤黑名单包"""
        self.installer._merged_dependencies = {
            "torch": DependencyInfo(
                package_name="torch",
                version_spec=">=1.8.0",
                original_line="torch>=1.8.0",
                source_nodes=["node1"]
            ),
            "requests": DependencyInfo(
                package_name="requests",
                version_spec=">=2.25.0",
                original_line="requests>=2.25.0",
                source_nodes=["node1"]
            )
        }
        
        with patch('builtins.print'):
            filtered = self.installer._filter_dependencies()
        
        self.assertNotIn("torch", filtered)  # Blacklisted
        # requests虽然已安装，但有版本要求，不应被过滤（让pip处理版本升级）
        self.assertIn("requests", filtered)

    def test_filter_already_installed_packages_with_version_requirement(self):
        """测试已安装但有版本要求的包不被过滤（交给pip处理升级）"""
        self.installer._merged_dependencies = {
            "numpy": DependencyInfo(  # numpy已安装，但有版本要求
                package_name="numpy",
                version_spec=">=1.25.0",  # 需要升级到 1.25.0+
                original_line="numpy>=1.25.0",
                source_nodes=["node1"]
            ),
            "new-package": DependencyInfo(  # 新包，未安装
                package_name="new-package",
                version_spec=">=1.0.0",
                original_line="new-package>=1.0.0",
                source_nodes=["node1"]
            )
        }
        
        with patch('builtins.print'):
            filtered = self.installer._filter_dependencies()
        
        # numpy虽然已安装，但有版本要求，不应被过滤
        self.assertIn("numpy", filtered)
        # 新包未安装，不应被过滤
        self.assertIn("new-package", filtered)
        
    def test_filter_already_installed_packages_without_version_requirement(self):
        """测试已安装且无版本要求的包被过滤"""
        self.installer._merged_dependencies = {
            "numpy": DependencyInfo(  # numpy已安装，无版本要求
                package_name="numpy",
                version_spec="",  # 无版本要求
                original_line="numpy",
                source_nodes=["node1"]
            ),
            "requests": DependencyInfo(  # requests已安装，无版本要求
                package_name="requests",
                version_spec="",
                original_line="requests",
                source_nodes=["node1"]
            )
        }
        
        with patch('builtins.print'):
            filtered = self.installer._filter_dependencies()
        
        # 无版本要求且已安装的包应被过滤
        self.assertNotIn("numpy", filtered)
        self.assertNotIn("requests", filtered)


class TestRequirementsMerging(TestPIPInstallerOptimized):
    """测试 requirements.txt 合并功能"""

    def setUp(self):
        super().setUp()
        with patch('services.pip.pip_installer_optimized.subprocess.check_output'):
            self.installer = PIPInstallerOptimized()

    @patch('services.pip.pip_installer_optimized.file_ops.robust_readlines')
    def test_merge_requirements_file_new_dependency(self, mock_readlines):
        """测试合并新依赖"""
        mock_readlines.return_value = ["torch>=1.8.0\n", "numpy==1.21.0\n"]
        
        self.installer._merge_requirements_file("/fake/requirements.txt", "test_node")
        
        self.assertEqual(len(self.installer._merged_dependencies), 2)
        self.assertIn("torch", self.installer._merged_dependencies)
        self.assertIn("numpy", self.installer._merged_dependencies)
        
        torch_dep = self.installer._merged_dependencies["torch"]
        self.assertEqual(torch_dep.version_spec, ">=1.8.0")
        self.assertEqual(torch_dep.source_nodes, ["test_node"])

    @patch('services.pip.pip_installer_optimized.file_ops.robust_readlines')
    def test_merge_requirements_file_conflicting_dependency(self, mock_readlines):
        """测试合并冲突依赖"""
        # 先添加一个依赖
        self.installer._merged_dependencies["torch"] = DependencyInfo(
            package_name="torch",
            version_spec=">=1.7.0",
            original_line="torch>=1.7.0",
            source_nodes=["node1"]
        )
        
        mock_readlines.return_value = ["torch>=1.8.0\n"]
        
        with patch.object(self.installer, '_resolve_version_conflict') as mock_resolve:
            mock_resolve.return_value = ">=1.8.0"
            
            self.installer._merge_requirements_file("/fake/requirements.txt", "node2")
        
        mock_resolve.assert_called_once_with(">=1.7.0", ">=1.8.0", "torch")
        torch_dep = self.installer._merged_dependencies["torch"]
        self.assertEqual(torch_dep.version_spec, ">=1.8.0")
        self.assertEqual(set(torch_dep.source_nodes), {"node1", "node2"})

    @patch('services.pip.pip_installer_optimized.file_ops.robust_readlines')
    def test_merge_requirements_with_git_dependencies(self, mock_readlines):
        """测试合并包含 git+ 依赖的 requirements"""
        mock_readlines.return_value = [
            "git+https://github.com/user/repo.git\n",
            "torch>=1.8.0\n"
        ]
        
        self.installer._merge_requirements_file("/fake/requirements.txt", "test_node")
        
        self.assertEqual(len(self.installer._merged_dependencies), 2)
        self.assertIn("git+https://github.com/user/repo.git", self.installer._merged_dependencies)
        self.assertIn("torch", self.installer._merged_dependencies)


class TestInstallationProcess(TestPIPInstallerOptimized):
    """测试安装过程"""

    def setUp(self):
        super().setUp()
        # 创建测试节点
        self.node1_dir = self.create_test_node_dir("node1")
        self.node2_dir = self.create_test_node_dir("node2")
        
        with patch('services.pip.pip_installer_optimized.subprocess.check_output'):
            self.installer = PIPInstallerOptimized()

    @patch('services.pip.pip_installer_optimized.subprocess.check_call')
    def test_do_install_dependency_success(self, mock_subprocess):
        """测试依赖安装成功"""
        mock_subprocess.return_value = 0
        
        with patch.object(self.installer, '_install_script', return_value=True):
            self.installer._do_install_dependency(
                ["node1"], "torch>=1.8.0", ["pip", "install", "torch>=1.8.0"]
            )
        
        self.assertEqual(len(self.installer._history), 1)
        record = self.installer._history[0]
        self.assertEqual(record["package_name"], "torch>=1.8.0")
        self.assertTrue(record["success"])

    def test_do_install_dependency_failure(self):
        """测试依赖安装失败"""
        with patch.object(self.installer, '_install_script', side_effect=Exception("Install failed")):
            self.installer._do_install_dependency(
                ["node1"], "invalid-package", ["pip", "install", "invalid-package"]
            )
        
        self.assertEqual(len(self.installer._history), 1)
        record = self.installer._history[0]
        self.assertEqual(record["package_name"], "invalid-package")
        self.assertFalse(record["success"])
        self.assertEqual(record["error_msg"], "Install failed")

    def test_do_install_script_success(self):
        """测试 install.py 脚本执行成功"""
        with patch.object(self.installer, '_install_script', return_value=True):
            self.installer._do_install_script(
                self.node1_dir, "node1", "install.py", ["python", "install.py"]
            )
        
        self.assertEqual(len(self.installer._history), 1)
        record = self.installer._history[0]
        self.assertEqual(record["node_name"], "node1")
        self.assertEqual(record["package_name"], "install.py")
        self.assertTrue(record["success"])


class TestFullIntegration(TestPIPInstallerOptimized):
    """测试完整安装流程"""

    def setUp(self):
        super().setUp()
        # 创建测试节点和文件
        self.node1_dir = self.create_test_node_dir("node1")
        self.node2_dir = self.create_test_node_dir("node2")
        self.node3_dir = self.create_test_node_dir("node3")
        
        # 创建 requirements.txt 文件
        self.create_requirements_file(self.node1_dir, "torch>=1.8.0\nnumpy>=1.20.0\n")
        self.create_requirements_file(self.node2_dir, "torch>=1.9.0\nrequests>=2.25.0\n")
        self.create_requirements_file(self.node3_dir, "git+https://github.com/user/repo.git\n")
        
        # 创建 install.py 脚本
        self.create_install_script(self.node2_dir, "print('Installing node2')\n")

    @patch('services.pip.pip_installer_optimized.subprocess.check_output')
    @patch('services.pip.pip_installer_optimized.subprocess.check_call')
    @patch('builtins.print')
    def test_install_all_full_process(self, mock_print, mock_check_call, mock_check_output):
        """测试完整安装流程"""
        # Mock pip list 输出
        mock_check_output.return_value = "Package Version\\nrequests 2.28.0"
        mock_check_call.return_value = 0
        
        installer = PIPInstallerOptimized()
        
        # Mock 各种方法
        with patch.object(installer, '_install_script', return_value=True):
            history = installer.install_all()
        
        # 验证安装历史记录
        self.assertIsInstance(history, list)
        # 应该有 torch, numpy 的安装记录，以及 node2 的 install.py 执行记录
        # requests 被跳过（已安装），git+ 依赖被跳过
        
        # 验证合并的依赖
        self.assertIn("torch", installer._merged_dependencies)
        self.assertIn("numpy", installer._merged_dependencies)
        self.assertIn("git+https://github.com/user/repo.git", installer._merged_dependencies)
        
        # 验证版本冲突解决（torch: >=1.8.0 vs >=1.9.0 -> >=1.9.0）
        torch_dep = installer._merged_dependencies["torch"]
        self.assertEqual(torch_dep.version_spec, ">=1.9.0")

    @patch('services.pip.pip_installer_optimized.subprocess.check_output')
    def test_install_all_with_nodes_map(self, mock_subprocess):
        """测试指定节点的安装"""
        mock_subprocess.return_value = "Package Version\\n"
        
        installer = PIPInstallerOptimized()
        nodes_map = {"node1": {}, "node3": {}}
        
        with patch.object(installer, '_install_merged_dependencies'), \
             patch.object(installer, '_execute_install_scripts'), \
             patch('builtins.print'):
            
            history = installer.install_all(nodes_map=nodes_map)
        
        # 验证只处理了指定的节点
        merged_deps = installer._merged_dependencies
        self.assertIn("torch", merged_deps)  # from node1
        self.assertIn("numpy", merged_deps)  # from node1
        self.assertIn("git+https://github.com/user/repo.git", merged_deps)  # from node3
        self.assertNotIn("requests", merged_deps)  # node2 not selected

    @patch('services.pip.pip_installer_optimized.subprocess.check_output')
    @patch('builtins.print')
    def test_install_all_timeout_handling(self, mock_print, mock_subprocess):
        """测试超时处理 - 验证超时时正常返回并打印日志"""
        mock_subprocess.return_value = "Package Version\\n"
        
        installer = PIPInstallerOptimized()
        
        # 需要确保有节点可以安装以触发超时检查
        # 创建一个测试节点目录
        test_node_dir = self.create_test_node_dir("test_timeout_node")
        self.create_requirements_file(test_node_dir, "some-package>=1.0.0\n")
        
        # 模拟时间流逝：
        # 0: start_time
        # 1000: 第一次检查时间（超时）
        # 1100: 结束时间（用于计算 total_duration）
        with patch('time.time', side_effect=[0, 1000, 1100]):
            # 应该正常返回，不抛出异常
            history = installer.install_all(soft_timeout=300)
            
        # 验证返回了历史记录（即使超时也应该返回）
        self.assertIsInstance(history, list)
        
        # 验证打印了超时日志
        timeout_logged = any(
            "Soft timeout" in str(call) for call in mock_print.call_args_list
        )
        self.assertTrue(timeout_logged, "Should log timeout message")


class TestUtilityMethods(TestPIPInstallerOptimized):
    """测试工具方法"""

    def setUp(self):
        super().setUp()
        with patch('services.pip.pip_installer_optimized.subprocess.check_output'):
            self.installer = PIPInstallerOptimized()

    def test_extract_version_from_exact(self):
        """测试从精确版本约束中提取版本号"""
        self.assertEqual(self.installer._extract_version_from_exact("==1.8.0"), "1.8.0")
        self.assertEqual(self.installer._extract_version_from_exact("==2.1.5"), "2.1.5")
        self.assertEqual(self.installer._extract_version_from_exact("invalid"), "invalid")

    def test_is_version_newer(self):
        """测试版本比较"""
        self.assertTrue(self.installer._is_version_newer("2.0.0", "1.0.0"))
        self.assertTrue(self.installer._is_version_newer("1.5.0", "1.4.9"))
        self.assertFalse(self.installer._is_version_newer("1.0.0", "2.0.0"))
        self.assertFalse(self.installer._is_version_newer("1.4.9", "1.5.0"))
        self.assertFalse(self.installer._is_version_newer("1.0.0", "1.0.0"))

    def test_is_version_newer_invalid_format(self):
        """测试无效版本格式的比较"""
        # 当版本格式无效时，应该进行字符串比较
        self.assertTrue(self.installer._is_version_newer("b", "a"))
        self.assertFalse(self.installer._is_version_newer("a", "b"))

    @patch('services.pip.pip_installer_optimized.subprocess.check_output')
    def test_try_get_installed_packages_success(self, mock_subprocess):
        """测试获取已安装包列表成功"""
        mock_subprocess.return_value = """Package    Version
---------- -------
requests   2.28.0
numpy      1.21.0"""
        
        installer = PIPInstallerOptimized()
        packages = installer.get_origin_packages()
        
        expected = {"requests": "2.28.0", "numpy": "1.21.0"}
        self.assertEqual(packages, expected)

    @patch('services.pip.pip_installer_optimized.subprocess.check_output')
    def test_try_get_installed_packages_failure(self, mock_subprocess):
        """测试获取已安装包列表失败"""
        from subprocess import CalledProcessError
        mock_subprocess.side_effect = CalledProcessError(1, "pip list")
        
        with patch('builtins.print'):  # Suppress error output
            installer = PIPInstallerOptimized()
        
        self.assertEqual(installer.get_origin_packages(), {})


if __name__ == "__main__":
    unittest.main()
