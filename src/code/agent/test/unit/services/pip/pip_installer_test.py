import os
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock, mock_open

from services.pip.pip_installer import PIPInstaller, DependencyInfo, InstallRecord, DependencyInstallRecord


class TestPIPInstaller(unittest.TestCase):
    def setUp(self):
        """测试初始化"""
        self.test_dir = tempfile.mkdtemp()
        self.comfyui_dir = os.path.join(self.test_dir, "comfyui")
        self.custom_nodes_dir = os.path.join(self.comfyui_dir, "custom_nodes")
        os.makedirs(self.custom_nodes_dir, exist_ok=True)
        
        # Mock constants
        self.constants_patcher = patch('services.pip.pip_installer.constants')
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


class TestDataStructures(TestPIPInstaller):
    """测试数据结构"""

    def test_install_record_creation(self):
        """测试 InstallRecord 创建"""
        record = InstallRecord(
            node_name="test_node",
            script_name="install.py",
            duration=10.5,
            success=True,
            error_msg=""
        )
        
        self.assertEqual(record.node_name, "test_node")
        self.assertEqual(record.script_name, "install.py")
        self.assertEqual(record.duration, 10.5)
        self.assertTrue(record.success)
        self.assertEqual(record.error_msg, "")
        
        # 测试 to_dict 方法
        record_dict = record.to_dict()
        expected = {
            "node_name": "test_node",
            "script_name": "install.py",
            "duration": 10.5,
            "success": True,
            "error_msg": ""
        }
        self.assertEqual(record_dict, expected)

    def test_dependency_install_record_creation(self):
        """测试 DependencyInstallRecord 创建"""
        requirements_txt = "torch>=1.8.0\nnumpy>=1.20.0"
        record = DependencyInstallRecord(
            requirements_txt=requirements_txt,
            duration=120.0,
            success=False,
            error_msg="Installation timeout"
        )
        
        self.assertEqual(record.requirements_txt, requirements_txt)
        self.assertEqual(record.duration, 120.0)
        self.assertFalse(record.success)
        self.assertEqual(record.error_msg, "Installation timeout")
        
        # 测试 to_dict 方法
        record_dict = record.to_dict()
        expected = {
            "requirements_txt": requirements_txt,
            "duration": 120.0,
            "success": False,
            "error_msg": "Installation timeout"
        }
        self.assertEqual(record_dict, expected)


class TestPIPInstallerInit(TestPIPInstaller):
    """测试初始化功能"""

    @patch('services.pip.pip_installer.subprocess.check_output')
    def test_init_without_blacklist(self, mock_subprocess):
        """测试不带黑名单的初始化"""
        mock_subprocess.return_value = "Package Version\nrequests 2.28.0\nnumpy 1.21.0"
        
        installer = PIPInstaller()
        
        self.assertEqual(installer.blacklist, set())
        self.assertIsInstance(installer._origin_packages, dict)
        # 不再有 _history 成员变量

    @patch('services.pip.pip_installer.subprocess.check_output')
    def test_init_with_blacklist(self, mock_subprocess):
        """测试带黑名单的初始化"""
        mock_subprocess.return_value = "Package Version\nrequests 2.28.0"
        blacklist = ["torch", "tensorflow"]
        
        installer = PIPInstaller(blacklist=blacklist)
        
        self.assertEqual(installer.blacklist, {"torch", "tensorflow"})


class TestPackageSpecParsing(TestPIPInstaller):
    """测试包规范解析功能"""

    def setUp(self):
        super().setUp()
        with patch('services.pip.pip_installer.subprocess.check_output'):
            self.installer = PIPInstaller()

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


class TestVersionConflictResolution(TestPIPInstaller):
    """测试版本冲突解决功能"""

    def setUp(self):
        super().setUp()
        with patch('services.pip.pip_installer.subprocess.check_output'):
            self.installer = PIPInstaller()

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

    @patch('services.pip.pip_installer.PIPInstaller._try_merge_version_ranges')
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


class TestVersionRangeMerging(TestPIPInstaller):
    """测试版本范围合并功能"""

    def setUp(self):
        super().setUp()
        with patch('services.pip.pip_installer.subprocess.check_output'):
            self.installer = PIPInstaller()

    @patch('services.pip.pip_installer.PIPInstaller._try_merge_with_packaging')
    def test_merge_with_packaging_success(self, mock_packaging):
        """测试使用 packaging 库成功合并"""
        mock_packaging.return_value = ">=1.5.0,<2.0.0"
        
        result = self.installer._try_merge_version_ranges(">=1.0.0,<2.0.0", ">=1.5.0,<3.0.0")
        
        self.assertEqual(result, ">=1.5.0,<2.0.0")
        mock_packaging.assert_called_once()

    @patch('services.pip.pip_installer.PIPInstaller._try_merge_with_packaging')
    @patch('services.pip.pip_installer.PIPInstaller._try_merge_simple_ranges')
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


class TestDependencyFiltering(TestPIPInstaller):
    """测试依赖过滤功能"""

    def setUp(self):
        super().setUp()
        with patch('services.pip.pip_installer.subprocess.check_output') as mock_subprocess:
            mock_subprocess.return_value = "Package Version\nrequests 2.28.0\nnumpy 1.21.0"
            self.installer = PIPInstaller(blacklist=["torch", "tensorflow"])

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
            filtered = self.installer._filter_merged_dependencies()  # 更新方法名
        
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
            filtered = self.installer._filter_merged_dependencies()
        
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
            filtered = self.installer._filter_merged_dependencies()
        
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
            filtered = self.installer._filter_merged_dependencies()
        
        # 无版本要求且已安装的包应被过滤
        self.assertNotIn("numpy", filtered)
        self.assertNotIn("requests", filtered)


class TestRequirementsMerging(TestPIPInstaller):
    """测试 requirements.txt 合并功能"""

    def setUp(self):
        super().setUp()
        with patch('services.pip.pip_installer.subprocess.check_output'):
            self.installer = PIPInstaller()

    @patch('services.pip.pip_installer.file_ops.robust_readlines')
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

    @patch('services.pip.pip_installer.file_ops.robust_readlines')
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

    @patch('services.pip.pip_installer.file_ops.robust_readlines')
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


class TestRequirementsGeneration(TestPIPInstaller):
    """测试 requirements.txt 生成功能"""

    def setUp(self):
        super().setUp()
        with patch('services.pip.pip_installer.subprocess.check_output'):
            self.installer = PIPInstaller()

    def test_generate_requirements_content_with_dependencies(self):
        """测试生成含有依赖的 requirements.txt 内容"""
        filtered_deps = {
            "torch": DependencyInfo(
                package_name="torch",
                version_spec=">=1.8.0",
                original_line="torch>=1.8.0",
                source_nodes=["node1", "node2"]
            ),
            "numpy": DependencyInfo(
                package_name="numpy",
                version_spec="==1.21.0",
                original_line="numpy==1.21.0",
                source_nodes=["node1"]
            )
        }
        
        with patch('builtins.print'):  # Suppress print output
            content = self.installer._generate_requirements_content(filtered_deps)
        
        expected_lines = ["numpy==1.21.0", "torch>=1.8.0"]  # 按字母顺序排列
        self.assertEqual(content, "\n".join(expected_lines))

    def test_generate_requirements_content_empty(self):
        """测试生成空的 requirements.txt 内容"""
        with patch('builtins.print'):  # Suppress print output
            content = self.installer._generate_requirements_content({})
        
        self.assertEqual(content, "")


class TestInstallationProcess(TestPIPInstaller):
    """测试安装过程"""

    def setUp(self):
        super().setUp()
        # 创建测试节点
        self.node1_dir = self.create_test_node_dir("node1")
        self.node2_dir = self.create_test_node_dir("node2")
        
        with patch('services.pip.pip_installer.subprocess.check_output'):
            self.installer = PIPInstaller()

    @patch('tempfile.NamedTemporaryFile')
    @patch('subprocess.run')
    @patch('os.unlink')
    def test_install_merged_dependencies_success(self, mock_unlink, mock_subprocess_run, mock_tempfile):
        """测试依赖批量安装成功"""
        # Mock 临时文件
        mock_file = MagicMock()
        mock_file.name = "/tmp/test_requirements.txt"
        mock_tempfile.return_value.__enter__.return_value = mock_file
        
        # Mock subprocess.run 返回成功
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Successfully installed torch numpy"
        mock_result.stderr = ""
        mock_subprocess_run.return_value = mock_result
        
        requirements_content = "torch>=1.8.0\nnumpy>=1.20.0"
        
        with patch('time.time', side_effect=[0, 10]):  # Mock start and end time
            result = self.installer._install_merged_dependencies(requirements_content, timeout=300)
        
        # 验证结果
        self.assertIsInstance(result, DependencyInstallRecord)
        self.assertTrue(result.success)
        self.assertEqual(result.requirements_txt, requirements_content)
        self.assertEqual(result.duration, 10.0)
        self.assertEqual(result.error_msg, "")
        
        # 验证调用
        mock_tempfile.assert_called_once()
        mock_file.write.assert_called_once_with(requirements_content)
        mock_subprocess_run.assert_called_once()
        mock_unlink.assert_called_once_with("/tmp/test_requirements.txt")

    @patch('tempfile.NamedTemporaryFile')
    @patch('subprocess.run')
    @patch('os.unlink')
    def test_install_merged_dependencies_failure(self, mock_unlink, mock_subprocess_run, mock_tempfile):
        """测试依赖批量安装失败"""
        # Mock 临时文件
        mock_file = MagicMock()
        mock_file.name = "/tmp/test_requirements.txt"
        mock_tempfile.return_value.__enter__.return_value = mock_file
        
        # Mock subprocess.run 返回失败
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "ERROR: No matching distribution found for invalid-package"
        mock_subprocess_run.return_value = mock_result
        
        requirements_content = "invalid-package>=1.0.0"
        
        with patch('time.time', side_effect=[0, 5]):  # Mock start and end time
            result = self.installer._install_merged_dependencies(requirements_content, timeout=300)
        
        # 验证结果
        self.assertIsInstance(result, DependencyInstallRecord)
        self.assertFalse(result.success)
        self.assertEqual(result.requirements_txt, requirements_content)
        self.assertEqual(result.duration, 5.0)
        self.assertIn("pip install failed with return code 1", result.error_msg)

    def test_do_install_script_success(self):
        """测试 install.py 脚本执行成功"""
        with patch.object(self.installer, '_install_script', return_value=True), \
             patch('time.time', side_effect=[0, 2.5]):
            
            result = self.installer._do_install_script(
                self.node1_dir, "node1", "install.py", ["python", "install.py"]
            )
        
        # 验证结果是字典形式
        self.assertIsInstance(result, dict)
        self.assertEqual(result["node_name"], "node1")
        self.assertEqual(result["script_name"], "install.py")
        self.assertTrue(result["success"])
        self.assertEqual(result["duration"], 2.5)
        self.assertEqual(result["error_msg"], "")

    def test_do_install_script_failure(self):
        """测试 install.py 脚本执行失败"""
        with patch.object(self.installer, '_install_script', side_effect=Exception("Script failed")), \
             patch('time.time', side_effect=[0, 1.0]):
            
            result = self.installer._do_install_script(
                self.node1_dir, "node1", "install.py", ["python", "install.py"]
            )
        
        # 验证结果是字典形式
        self.assertIsInstance(result, dict)
        self.assertEqual(result["node_name"], "node1")
        self.assertEqual(result["script_name"], "install.py")
        self.assertFalse(result["success"])
        self.assertEqual(result["duration"], 1.0)
        self.assertEqual(result["error_msg"], "Script failed")


class TestFullIntegration(TestPIPInstaller):
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

    @patch('services.pip.pip_installer.subprocess.check_output')
    @patch('builtins.print')
    def test_install_all_full_process(self, mock_print, mock_check_output):
        """测试完整安装流程（不真正执行 pip）"""
        # Mock pip list 输出
        mock_check_output.return_value = "Package Version\nrequests 2.28.0"
        
        installer = PIPInstaller()
        
        # Mock 生成 requirements 内容
        with patch.object(installer, '_install_merged_dependencies') as mock_dep_install, \
             patch.object(installer, '_execute_install_scripts') as mock_scripts:
            
            # 假设依赖安装成功
            dep_record = DependencyInstallRecord(requirements_txt="torch>=1.9.0\nnumpy>=1.20.0", duration=12.3, success=True, error_msg="")
            mock_dep_install.return_value = dep_record
            
            # 假设脚本执行成功
            mock_scripts.return_value = [
                InstallRecord(node_name="node2", script_name="install.py", duration=1.2, success=True, error_msg="").to_dict()
            ]
            
            result_map = installer.install_all()
        
        # 验证返回结构
        self.assertIsInstance(result_map, dict)
        self.assertIn("baseline", result_map)
        self.assertIn("dependencies", result_map)
        self.assertIn("scripts", result_map)
        
        self.assertTrue(result_map["dependencies"]["success"])  # 依赖安装成功
        self.assertEqual(len(result_map["scripts"]), 1)  # 一个脚本被执行
        
        # 验证合并的依赖
        self.assertIn("torch", installer._merged_dependencies)
        self.assertIn("numpy", installer._merged_dependencies)
        self.assertIn("git+https://github.com/user/repo.git", installer._merged_dependencies)
        
        # 验证版本冲突解决（torch: >=1.8.0 vs >=1.9.0 -> >=1.9.0）
        torch_dep = installer._merged_dependencies["torch"]
        self.assertEqual(torch_dep.version_spec, ">=1.9.0")

    @patch('services.pip.pip_installer.subprocess.check_output')
    def test_install_all_with_nodes_map(self, mock_subprocess):
        """测试指定节点的安装"""
        mock_subprocess.return_value = "Package Version\n"
        
        installer = PIPInstaller()
        nodes_map = {"node1": {}, "node3": {}}
        
        with patch.object(installer, '_install_merged_dependencies') as mock_dep_install, \
             patch.object(installer, '_execute_install_scripts') as mock_scripts, \
             patch('builtins.print'):
            
            dep_record = DependencyInstallRecord(requirements_txt="numpy>=1.20.0\ntorch>=1.8.0", duration=1.0, success=True, error_msg="")
            mock_dep_install.return_value = dep_record
            mock_scripts.return_value = []
            
            result_map = installer.install_all(nodes_map=nodes_map)
        
        # 验证只处理了指定的节点
        merged_deps = installer._merged_dependencies
        self.assertIn("torch", merged_deps)  # from node1
        self.assertIn("numpy", merged_deps)  # from node1
        self.assertIn("git+https://github.com/user/repo.git", merged_deps)  # from node3
        self.assertNotIn("requests", merged_deps)  # node2 not selected

    @patch('services.pip.pip_installer.subprocess.check_output')
    @patch('builtins.print')
    def test_install_all_timeout_behavior(self, mock_print, mock_subprocess):
        """测试超时捕获行为（install_all 会捕获 TimeoutError 不再抛出）"""
        mock_subprocess.return_value = "Package Version\n"
        
        installer = PIPInstaller()
        
        # 创建一个测试节点目录，确保 _merge_requirements_from_nodes 有内容
        test_node_dir = self.create_test_node_dir("test_timeout_node")
        self.create_requirements_file(test_node_dir, "some-package>=1.0.0\n")
        
        # 模拟时间推进，触发 _merge_requirements_from_nodes 的 timeout
        # install_all 会捕获 TimeoutError 并打印日志，然后正常返回
        with patch('time.time', side_effect=[0, 1000, 1001, 1002]):
            result_map = installer.install_all(timeout=300)
        
        # 验证返回结果是有效的
        self.assertIsInstance(result_map, dict)
        self.assertIn("baseline", result_map)
        self.assertIn("dependencies", result_map)
        self.assertIn("scripts", result_map)
        
        # 验证打印了超时日志
        printed_timeout = any("Timeout (" in str(call) for call in mock_print.call_args_list)
        self.assertTrue(printed_timeout)  # 应该打印超时信息


class TestUtilityMethods(TestPIPInstaller):
    """测试工具方法"""

    def setUp(self):
        super().setUp()
        with patch('services.pip.pip_installer.subprocess.check_output'):
            self.installer = PIPInstaller()

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
    @patch('services.pip.pip_installer.subprocess.check_output')
    def test_try_get_installed_packages_success(self, mock_subprocess):
        """测试获取已安装包列表成功"""
        mock_subprocess.return_value = """Package    Version
---------- -------
requests   2.28.0
numpy      1.21.0"""
        
        installer = PIPInstaller()
        packages = installer.get_origin_packages()
        
        expected = {"requests": "2.28.0", "numpy": "1.21.0"}
        self.assertEqual(packages, expected)

    @patch('services.pip.pip_installer.subprocess.check_output')
    def test_try_get_installed_packages_failure(self, mock_subprocess):
        """测试获取已安装包列表失败"""
        from subprocess import CalledProcessError
        mock_subprocess.side_effect = CalledProcessError(1, "pip list")
        
        with patch('builtins.print'):  # Suppress error output
            installer = PIPInstaller()
        
        self.assertEqual(installer.get_origin_packages(), {})


class TestNewIntegrationFlow(TestPIPInstaller):
    """测试重构后的集成流程"""

    def setUp(self):
        super().setUp()
        with patch('services.pip.pip_installer.subprocess.check_output'):
            self.installer = PIPInstaller()

    def test_empty_nodes_map(self):
        """测试空节点映射的情况"""
        with patch('services.pip.pip_installer.subprocess.check_output') as mock_subprocess:
            mock_subprocess.return_value = "Package Version\n"
            installer = PIPInstaller()
            
            # 传递空字典，应该不安装任何节点
            result_map = installer.install_all(timeout=60, nodes_map={})
            
            # 验证返回结构
            self.assertIsInstance(result_map, dict)
            self.assertIn("baseline", result_map)
            self.assertIn("dependencies", result_map)
            self.assertIn("scripts", result_map)
            
            # 验证空节点映射的情况
            self.assertEqual(len(result_map["scripts"]), 0)  # 无脚本执行
            self.assertTrue(result_map["dependencies"]["success"])  # 依赖安装成功（但无内容）
            self.assertEqual(result_map["dependencies"]["requirements_txt"], "")  # 无依赖内容

    def test_return_structure_consistency(self):
        """测试返回结构的一致性"""
        with patch('services.pip.pip_installer.subprocess.check_output') as mock_subprocess:
            mock_subprocess.return_value = "Package Version\n"
            
            installer = PIPInstaller()
            
            # 测试不同参数的情况
            test_cases = [
                None,  # 安装所有节点
                {},    # 不安装任何节点
                {"nonexistent": {}},  # 不存在的节点
            ]
            
            for nodes_map in test_cases:
                with self.subTest(nodes_map=nodes_map):
                    result_map = installer.install_all(timeout=10, nodes_map=nodes_map)
                    
                    # 验证返回结构一致性
                    self.assertIsInstance(result_map, dict)
                    self.assertIn("baseline", result_map)
                    self.assertIn("dependencies", result_map)
                    self.assertIn("scripts", result_map)
                    
                    # 验证 dependencies 结构
                    deps = result_map["dependencies"]
                    self.assertIn("requirements_txt", deps)
                    self.assertIn("duration", deps)
                    self.assertIn("success", deps)
                    self.assertIn("error_msg", deps)
                    
                    # 验证 scripts 结构
                    self.assertIsInstance(result_map["scripts"], list)


if __name__ == "__main__":
    unittest.main()
