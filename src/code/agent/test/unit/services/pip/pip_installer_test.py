"""
PIPInstaller 单元测试
=====================
覆盖 services/pip/pip_installer.py 中 PIPInstaller 类的各个方法。

版本裁决逻辑已移至 version_resolver.py，由独立测试文件覆盖。
"""
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock, call

from services.pip.pip_installer import PIPInstaller
from models import DependencyInfo, DependencyInstallRecord, InstallRecord


# ─────────────────────────────────────────────────────────────────────────────
# 测试基类：搭建带真实目录结构的临时 comfyui 环境
# ─────────────────────────────────────────────────────────────────────────────
class _Base(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.comfyui_dir = os.path.join(self.tmp, "comfyui")
        self.custom_nodes_dir = os.path.join(self.comfyui_dir, "custom_nodes")
        os.makedirs(self.custom_nodes_dir)

        self._patch_constants = patch("services.pip.pip_installer.constants")
        self.mock_constants = self._patch_constants.start()
        self.mock_constants.COMFYUI_DIR = self.comfyui_dir
        self.mock_constants.VENV_EXECUTABLE = "/fake/venv/bin/python"
        self.mock_constants.PIP_FALLBACK_INDEX_URL = "https://mirrors.aliyun.com/pypi/simple/"

    def tearDown(self):
        self._patch_constants.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ── 工厂方法 ──────────────────────────────────────────────────────────────
    def _installer(self, blacklist=None, installed_packages="Package Version\n"):
        with patch("services.pip.pip_installer.subprocess.check_output",
                   return_value=installed_packages):
            return PIPInstaller(blacklist=blacklist)

    def _make_node(self, name, requirements=None, install_py=None):
        node_dir = os.path.join(self.custom_nodes_dir, name)
        os.makedirs(node_dir, exist_ok=True)
        if requirements is not None:
            with open(os.path.join(node_dir, "requirements.txt"), "w") as f:
                f.write(requirements)
        if install_py is not None:
            with open(os.path.join(node_dir, "install.py"), "w") as f:
                f.write(install_py)
        return node_dir

    def _dep(self, name, spec="", node="node-a"):
        return DependencyInfo(package_name=name, version_spec=spec,
                              original_line=f"{name}{spec}", source_nodes=[node])


# ─────────────────────────────────────────────────────────────────────────────
# 1. 数据结构
# ─────────────────────────────────────────────────────────────────────────────
class TestDataStructures(unittest.TestCase):

    def test_install_record_defaults_and_to_dict(self):
        rec = InstallRecord(node_name="n1", script_name="install.py",
                            duration=3.5, success=True, error_msg="")
        d = rec.to_dict()
        self.assertEqual(d["node_name"], "n1")
        self.assertEqual(d["duration"], 3.5)
        self.assertTrue(d["success"])

    def test_dependency_install_record_to_dict(self):
        rec = DependencyInstallRecord(requirements_txt="torch>=1.8\nnumpy",
                                     duration=12.0, success=False,
                                     error_msg="oops")
        d = rec.to_dict()
        self.assertFalse(d["success"])
        self.assertEqual(d["error_msg"], "oops")
        self.assertIn("torch", d["requirements_txt"])

    def test_dependency_info_fields(self):
        dep = DependencyInfo(package_name="requests", version_spec=">=2.25",
                             original_line="requests>=2.25", source_nodes=["n1", "n2"])
        self.assertEqual(dep.package_name, "requests")
        self.assertEqual(dep.source_nodes, ["n1", "n2"])


# ─────────────────────────────────────────────────────────────────────────────
# 2. 初始化
# ─────────────────────────────────────────────────────────────────────────────
class TestPIPInstallerInit(_Base):

    def test_init_no_blacklist(self):
        installer = self._installer()
        self.assertEqual(installer.blacklist, set())
        self.assertIsInstance(installer._origin_packages, dict)

    def test_init_with_blacklist(self):
        installer = self._installer(blacklist=["torch", "tensorflow"])
        self.assertEqual(installer.blacklist, {"torch", "tensorflow"})

    def test_origin_packages_parsed(self):
        pip_list_output = "Package   Version\n---------- -------\nrequests  2.28.0\nnumpy     1.21.0\n"
        installer = self._installer(installed_packages=pip_list_output)
        pkgs = installer.get_origin_packages()
        self.assertEqual(pkgs["requests"], "2.28.0")
        self.assertEqual(pkgs["numpy"], "1.21.0")

    def test_origin_packages_pep503_normalized(self):
        pip_list_output = "Package   Version\nScikit_Learn  1.3.0\nPillow        9.0.0\n"
        installer = self._installer(installed_packages=pip_list_output)
        pkgs = installer.get_origin_packages()
        self.assertIn("scikit-learn", pkgs)
        self.assertIn("pillow", pkgs)

    def test_init_pip_list_failure_returns_empty(self):
        with patch("services.pip.pip_installer.subprocess.check_output",
                   side_effect=subprocess.CalledProcessError(1, "pip list")), \
             patch("builtins.print"):
            installer = PIPInstaller()
        self.assertEqual(installer.get_origin_packages(), {})


# ─────────────────────────────────────────────────────────────────────────────
# 3. _extract_package_name（静态方法）
# ─────────────────────────────────────────────────────────────────────────────
class TestExtractPackageName(unittest.TestCase):

    def _call(self, line):
        return PIPInstaller._extract_package_name(line)

    def test_plain_package(self):
        self.assertEqual(self._call("requests==2.28.0"), "requests==2.28.0")

    def test_strips_comment(self):
        self.assertEqual(self._call("numpy>=1.20.0 # some comment"), "numpy>=1.20.0")

    def test_pure_comment_returns_empty(self):
        self.assertEqual(self._call("# just a comment"), "")

    def test_empty_line_returns_empty(self):
        self.assertEqual(self._call("   "), "")

    def test_leading_trailing_spaces(self):
        self.assertEqual(self._call("  torch>=1.8.0  "), "torch>=1.8.0")

    def test_git_url(self):
        self.assertEqual(
            self._call("git+https://github.com/user/repo.git"),
            "git+https://github.com/user/repo.git",
        )


# ─────────────────────────────────────────────────────────────────────────────
# 4. _parse_package_spec
# ─────────────────────────────────────────────────────────────────────────────
class TestParsePackageSpec(_Base):

    def setUp(self):
        super().setUp()
        self.inst = self._installer()

    def _p(self, spec):
        return self.inst._parse_package_spec(spec)

    def test_no_version(self):
        self.assertEqual(self._p("requests"), ("requests", ""))

    def test_ge_version(self):
        self.assertEqual(self._p("torch>=1.8.0"), ("torch", ">=1.8.0"))

    def test_exact_version(self):
        self.assertEqual(self._p("numpy==1.21.0"), ("numpy", "==1.21.0"))

    def test_compound_version(self):
        self.assertEqual(self._p("requests>=2.25.0,<3.0.0"), ("requests", ">=2.25.0,<3.0.0"))

    def test_space_between_name_and_op(self):
        name, spec = self._p("accelerate >= 1.2.1")
        self.assertEqual(name, "accelerate")
        self.assertEqual(spec, ">= 1.2.1")

    def test_pep503_lowercase(self):
        name, _ = self._p("Requests>=2.0")
        self.assertEqual(name, "requests")

    def test_pep503_underscore_to_hyphen(self):
        name, _ = self._p("scikit_image>=0.18")
        self.assertEqual(name, "scikit-image")

    def test_pep503_dot_to_hyphen(self):
        name, _ = self._p("my.package>=1.0")
        self.assertEqual(name, "my-package")

    def test_git_url_returned_as_is(self):
        url = "git+https://github.com/user/repo.git"
        self.assertEqual(self._p(url), (url, ""))

    def test_hg_url(self):
        url = "hg+https://bitbucket.org/user/repo"
        self.assertEqual(self._p(url), (url, ""))


# ─────────────────────────────────────────────────────────────────────────────
# 5. _get_possible_nodes
# ─────────────────────────────────────────────────────────────────────────────
class TestGetPossibleNodes(_Base):

    def test_returns_only_directories(self):
        self._make_node("node-a")
        self._make_node("node-b")
        open(os.path.join(self.custom_nodes_dir, "some_file.txt"), "w").close()
        nodes = self._installer()._get_possible_nodes(self.custom_nodes_dir)
        self.assertIn("node-a", nodes)
        self.assertIn("node-b", nodes)
        self.assertNotIn("some_file.txt", nodes)

    def test_excludes_disabled(self):
        self._make_node("good-node")
        self._make_node("bad-node.disabled")
        nodes = self._installer()._get_possible_nodes(self.custom_nodes_dir)
        self.assertIn("good-node", nodes)
        self.assertNotIn("bad-node.disabled", nodes)

    def test_excludes_pycache(self):
        self._make_node("__pycache__")
        nodes = self._installer()._get_possible_nodes(self.custom_nodes_dir)
        self.assertNotIn("__pycache__", nodes)


# ─────────────────────────────────────────────────────────────────────────────
# 6. _build_node_paths_map
# ─────────────────────────────────────────────────────────────────────────────
class TestBuildNodePathsMap(_Base):

    def setUp(self):
        super().setUp()
        self.inst = self._installer()
        self.custom_nodes_dir2 = os.path.join(self.tmp, "extra_nodes")
        os.makedirs(self.custom_nodes_dir2)

    def _make_node_in(self, base_dir, name):
        node_dir = os.path.join(base_dir, name)
        os.makedirs(node_dir, exist_ok=True)
        return node_dir

    def test_basic_mapping(self):
        """基本场景：正确返回 {小写名 -> 完整路径} 的映射"""
        self._make_node("node-a")
        result = self.inst._build_node_paths_map([self.custom_nodes_dir])
        self.assertIn("node-a", result)
        self.assertEqual(result["node-a"], os.path.join(self.custom_nodes_dir, "node-a"))

    def test_key_is_lowercased(self):
        """目录名含大写时，映射的 key 应转为小写"""
        self._make_node("ComfyUI-Manager")
        result = self.inst._build_node_paths_map([self.custom_nodes_dir])
        self.assertIn("comfyui-manager", result)
        self.assertNotIn("ComfyUI-Manager", result)

    def test_path_preserves_original_case(self):
        """映射的 value（完整路径）保留文件系统原始大小写"""
        self._make_node("ComfyUI-Manager")
        result = self.inst._build_node_paths_map([self.custom_nodes_dir])
        self.assertIn("ComfyUI-Manager", result["comfyui-manager"])

    def test_duplicate_across_dirs_first_wins(self):
        """多目录中存在同名插件（忽略大小写）时，以列表中先出现的目录为准"""
        self._make_node_in(self.custom_nodes_dir, "MyNode")
        self._make_node_in(self.custom_nodes_dir2, "mynode")
        with patch("builtins.print"):
            result = self.inst._build_node_paths_map(
                [self.custom_nodes_dir, self.custom_nodes_dir2]
            )
        self.assertEqual(len([k for k in result if k == "mynode"]), 1)
        self.assertIn(self.custom_nodes_dir, result["mynode"])

    def test_duplicate_across_dirs_prints_warning(self):
        """重名时应打印警告"""
        self._make_node_in(self.custom_nodes_dir, "MyNode")
        self._make_node_in(self.custom_nodes_dir2, "mynode")
        with patch("builtins.print") as mock_print:
            self.inst._build_node_paths_map(
                [self.custom_nodes_dir, self.custom_nodes_dir2]
            )
        printed = " ".join(str(c) for c in mock_print.call_args_list)
        self.assertIn("Duplicate", printed)

    def test_nonexistent_dir_skipped_with_warning(self):
        """不存在的目录跳过，并打印警告；其余目录仍正常扫描"""
        self._make_node("node-a")
        fake_dir = os.path.join(self.tmp, "nonexistent")
        with patch("builtins.print") as mock_print:
            result = self.inst._build_node_paths_map([fake_dir, self.custom_nodes_dir])
        self.assertIn("node-a", result)
        printed = " ".join(str(c) for c in mock_print.call_args_list)
        self.assertIn("does not exist", printed)

    def test_multiple_dirs_merged(self):
        """多个目录中的插件合并到同一映射"""
        self._make_node("node-a")
        self._make_node_in(self.custom_nodes_dir2, "node-b")
        result = self.inst._build_node_paths_map(
            [self.custom_nodes_dir, self.custom_nodes_dir2]
        )
        self.assertIn("node-a", result)
        self.assertIn("node-b", result)

    def test_empty_dirs_list_returns_empty_map(self):
        """空目录列表返回空映射"""
        result = self.inst._build_node_paths_map([])
        self.assertEqual(result, {})


# ─────────────────────────────────────────────────────────────────────────────
# 7. _determine_nodes_to_install
# ─────────────────────────────────────────────────────────────────────────────
class TestDetermineNodesToInstall(_Base):

    def setUp(self):
        super().setUp()
        self.inst = self._installer()

    def test_none_installs_all(self):
        nodes = self.inst._determine_nodes_to_install(["a", "b", "c"], nodes_map=None)
        self.assertEqual(sorted(nodes), ["a", "b", "c"])

    def test_empty_dict_installs_nothing(self):
        nodes = self.inst._determine_nodes_to_install(["a", "b"], nodes_map={})
        self.assertEqual(nodes, [])

    def test_partial_nodes_map(self):
        with patch("builtins.print"):
            nodes = self.inst._determine_nodes_to_install(["a", "b", "c"],
                                                          nodes_map={"a": {}, "c": {}})
        self.assertIn("a", nodes)
        self.assertIn("c", nodes)
        self.assertNotIn("b", nodes)

    def test_invalid_nodes_in_map_are_skipped(self):
        with patch("builtins.print"):
            nodes = self.inst._determine_nodes_to_install(["a"],
                                                          nodes_map={"a": {}, "nonexistent": {}})
        self.assertIn("a", nodes)
        self.assertNotIn("nonexistent", nodes)

    def test_nodes_map_keys_case_insensitive(self):
        """nodes_map 中含大写的 key 应能匹配到小写的 available node"""
        with patch("builtins.print"):
            nodes = self.inst._determine_nodes_to_install(
                ["comfyui-manager", "node-b"],
                nodes_map={"ComfyUI-Manager": {}, "NODE-B": {}}
            )
        self.assertIn("comfyui-manager", nodes)
        self.assertIn("node-b", nodes)


# ─────────────────────────────────────────────────────────────────────────────
# 7. _merge_requirements_file
# ─────────────────────────────────────────────────────────────────────────────
class TestMergeRequirementsFile(_Base):

    def setUp(self):
        super().setUp()
        self.inst = self._installer()

    def _merge(self, content, node="node-a"):
        req_path = os.path.join(self.tmp, "requirements.txt")
        with open(req_path, "w") as f:
            f.write(content)
        merged: dict = {}
        with patch("services.pip.pip_installer.file_ops.robust_readlines",
                   return_value=content.splitlines(keepends=True)):
            self.inst._merge_requirements_file(req_path, node, merged)
        return merged

    def test_new_simple_dep(self):
        merged = self._merge("torch>=1.8.0\nnumpy==1.21.0\n")
        self.assertIn("torch", merged)
        self.assertIn("numpy", merged)
        self.assertEqual(merged["torch"].version_spec, ">=1.8.0")

    def test_comment_lines_ignored(self):
        merged = self._merge("# comment\nrequests>=2.25.0\n")
        self.assertNotIn("# comment", merged)
        self.assertIn("requests", merged)

    def test_empty_lines_ignored(self):
        merged = self._merge("\n\nrequests\n\n")
        self.assertIn("requests", merged)
        self.assertEqual(len(merged), 1)

    def test_git_dep_stored_as_is(self):
        url = "git+https://github.com/user/repo.git"
        merged = self._merge(url + "\n")
        self.assertIn(url, merged)

    def test_conflict_calls_version_resolver(self):
        req_path = os.path.join(self.tmp, "r.txt")
        merged = {
            "torch": DependencyInfo(package_name="torch", version_spec=">=1.7.0",
                                    original_line="torch>=1.7.0", source_nodes=["node-x"])
        }
        with patch("services.pip.pip_installer.file_ops.robust_readlines",
                   return_value=["torch>=1.9.0\n"]), \
             patch("services.pip.pip_installer.resolve_version_conflict",
                   return_value=">=1.9.0") as mock_resolve:
            self.inst._merge_requirements_file(req_path, "node-y", merged)
        mock_resolve.assert_called_once_with(">=1.7.0", ">=1.9.0", "torch")
        self.assertEqual(merged["torch"].version_spec, ">=1.9.0")
        self.assertIn("node-y", merged["torch"].source_nodes)

    def test_source_nodes_accumulated(self):
        req_path = os.path.join(self.tmp, "r.txt")
        merged = {}
        for node in ["n1", "n2", "n3"]:
            with patch("services.pip.pip_installer.file_ops.robust_readlines",
                       return_value=["requests\n"]):
                self.inst._merge_requirements_file(req_path, node, merged)
        self.assertEqual(set(merged["requests"].source_nodes), {"n1", "n2", "n3"})


# ─────────────────────────────────────────────────────────────────────────────
# 8. _filter_merged_dependencies
# ─────────────────────────────────────────────────────────────────────────────
class TestFilterMergedDependencies(_Base):

    def setUp(self):
        super().setUp()
        installed = "Package   Version\nnumpy  1.21.0\nrequests  2.28.0\n"
        self.inst = self._installer(blacklist=["torch"], installed_packages=installed)

    def _filter(self, deps):
        with patch("builtins.print"):
            return self.inst._filter_merged_dependencies(deps)

    def test_git_dep_filtered_into_problematic(self):
        url = "git+https://github.com/user/repo.git"
        deps = {url: self._dep(url)}
        filtered = self._filter(deps)
        self.assertNotIn(url, filtered)
        self.assertIn(url, self.inst._problematic_deps)

    def test_blacklisted_dep_filtered(self):
        deps = {"torch": self._dep("torch", ">=1.8.0")}
        filtered = self._filter(deps)
        self.assertNotIn("torch", filtered)
        self.assertIn("torch", self.inst._problematic_deps)

    def test_already_installed_no_spec_skipped(self):
        deps = {"numpy": self._dep("numpy")}          # no version spec
        filtered = self._filter(deps)
        self.assertNotIn("numpy", filtered)
        # 正常跳过，不进 problematic_deps
        self.assertNotIn("numpy", self.inst._problematic_deps)

    def test_already_installed_with_spec_kept(self):
        deps = {"numpy": self._dep("numpy", ">=1.25.0")}  # has spec
        filtered = self._filter(deps)
        self.assertIn("numpy", filtered)

    def test_new_uninstalled_dep_kept(self):
        deps = {"new-pkg": self._dep("new-pkg", ">=1.0.0")}
        filtered = self._filter(deps)
        self.assertIn("new-pkg", filtered)

    def test_blacklist_case_insensitive(self):
        inst = self._installer(blacklist=["TORCH"])
        deps = {"torch": self._dep("torch")}
        with patch("builtins.print"):
            filtered = inst._filter_merged_dependencies(deps)
        self.assertNotIn("torch", filtered)


# ─────────────────────────────────────────────────────────────────────────────
# 9. _generate_requirements_content
# ─────────────────────────────────────────────────────────────────────────────
class TestGenerateRequirementsContent(_Base):
    """_generate_requirements_content 接受已排序的 List[DependencyInfo]，
    由调用方负责排序。"""

    def setUp(self):
        super().setUp()
        self.inst = self._installer()

    def test_empty_deps_returns_empty(self):
        with patch("builtins.print"):
            content = self.inst._generate_requirements_content([])
        self.assertEqual(content, "")

    def test_preserves_caller_order(self):
        """方法按传入顺序输出，不自行排序（排序由调用方保证）"""
        deps = sorted([
            self._dep("torch", ">=1.8.0"),
            self._dep("numpy", "==1.21.0"),
            self._dep("accelerate"),
        ], key=lambda d: d.package_name)
        with patch("builtins.print"):
            content = self.inst._generate_requirements_content(deps)
        lines = content.splitlines()
        self.assertEqual(lines, ["accelerate", "numpy==1.21.0", "torch>=1.8.0"])

    def test_package_with_no_version_spec(self):
        with patch("builtins.print"):
            content = self.inst._generate_requirements_content([self._dep("requests")])
        self.assertEqual(content, "requests")

    def test_package_with_version_spec(self):
        with patch("builtins.print"):
            content = self.inst._generate_requirements_content(
                [self._dep("requests", ">=2.25.0")]
            )
        self.assertEqual(content, "requests>=2.25.0")


# ─────────────────────────────────────────────────────────────────────────────
# 10. _get_script_env / _get_pip_install_env
# ─────────────────────────────────────────────────────────────────────────────
class TestEnvironmentHandling(_Base):

    def setUp(self):
        super().setUp()
        self.inst = self._installer()
        self._base_env = {
            "PATH": "/usr/bin",
            "HOME": "/home/user",
            "http_proxy": "http://proxy:8080",
            "https_proxy": "https://proxy:8080",
            "HTTP_PROXY": "http://proxy:8080",
            "HTTPS_PROXY": "https://proxy:8080",
        }

    def test_script_env_keeps_proxy_vars(self):
        with patch("os.environ.copy", return_value=self._base_env.copy()):
            env = self.inst._get_script_env()
        for var in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"]:
            self.assertIn(var, env)

    def test_script_env_sets_comfyui_vars(self):
        with patch("os.environ.copy", return_value={}):
            env = self.inst._get_script_env()
        self.assertEqual(env["COMFYUI_PATH"], self.comfyui_dir)
        self.assertEqual(env["COMFYUI_FOLDERS_BASE_PATH"], self.comfyui_dir)

    def test_pip_install_env_removes_all_proxy_vars(self):
        with patch("os.environ.copy", return_value=self._base_env.copy()):
            env = self.inst._get_pip_install_env()
        for var in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"]:
            self.assertNotIn(var, env)

    def test_pip_install_env_keeps_non_proxy_vars(self):
        with patch("os.environ.copy", return_value=self._base_env.copy()):
            env = self.inst._get_pip_install_env()
        self.assertIn("PATH", env)
        self.assertIn("HOME", env)

    def test_pip_install_env_no_proxy_initially(self):
        with patch("os.environ.copy", return_value={"PATH": "/usr/bin"}):
            env = self.inst._get_pip_install_env()
        self.assertIn("PATH", env)

    def test_pip_install_env_partial_proxy(self):
        env_with_partial = {"PATH": "/usr/bin", "http_proxy": "http://proxy:8080"}
        with patch("os.environ.copy", return_value=env_with_partial.copy()):
            env = self.inst._get_pip_install_env()
        self.assertNotIn("http_proxy", env)
        self.assertIn("PATH", env)

    def test_fallback_pip_env_sets_index_url(self):
        """fallback env 应设置 PIP_INDEX_URL 为 constants.PIP_FALLBACK_INDEX_URL"""
        with patch("os.environ.copy", return_value={"PATH": "/usr/bin"}):
            env = self.inst._get_fallback_pip_env()
        self.assertEqual(env["PIP_INDEX_URL"], "https://mirrors.aliyun.com/pypi/simple/")

    def test_fallback_pip_env_removes_extra_index_url(self):
        """fallback env 应移除 PIP_EXTRA_INDEX_URL，避免其他源干扰"""
        base = {"PATH": "/usr/bin", "PIP_EXTRA_INDEX_URL": "https://other.mirror/simple/"}
        with patch("os.environ.copy", return_value=base.copy()):
            env = self.inst._get_fallback_pip_env()
        self.assertNotIn("PIP_EXTRA_INDEX_URL", env)

    def test_fallback_pip_env_removes_proxy(self):
        """fallback env 继承 _get_pip_install_env 的代理清除逻辑"""
        with patch("os.environ.copy", return_value=self._base_env.copy()):
            env = self.inst._get_fallback_pip_env()
        for var in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"]:
            self.assertNotIn(var, env)

    def test_fallback_pip_env_keeps_non_proxy_vars(self):
        """fallback env 保留非代理环境变量"""
        with patch("os.environ.copy", return_value=self._base_env.copy()):
            env = self.inst._get_fallback_pip_env()
        self.assertIn("PATH", env)
        self.assertIn("HOME", env)


# ─────────────────────────────────────────────────────────────────────────────
# 11. _do_install_script
# ─────────────────────────────────────────────────────────────────────────────
class TestDoInstallScript(_Base):

    def setUp(self):
        super().setUp()
        self.inst = self._installer()
        self.node_dir = self._make_node("n1")

    def test_success_returns_dict(self):
        with patch.object(self.inst, "_install_script", return_value=True), \
             patch("time.time", side_effect=[0.0, 2.5]):
            result = self.inst._do_install_script(
                self.node_dir, "n1", "install.py", ["python", "install.py"]
            )
        self.assertTrue(result["success"])
        self.assertEqual(result["node_name"], "n1")
        self.assertEqual(result["duration"], 2.5)
        self.assertEqual(result["error_msg"], "")

    def test_exception_returns_failure(self):
        with patch.object(self.inst, "_install_script",
                          side_effect=Exception("script boom")), \
             patch("time.time", side_effect=[0.0, 1.0]):
            result = self.inst._do_install_script(
                self.node_dir, "n1", "install.py", ["python", "install.py"]
            )
        self.assertFalse(result["success"])
        self.assertEqual(result["error_msg"], "script boom")


# ─────────────────────────────────────────────────────────────────────────────
# 13. install_all — 结构一致性 & 边界情况
# ─────────────────────────────────────────────────────────────────────────────
class TestInstallAll(_Base):

    def _run_install_all(self, nodes_map, installed_packages="Package Version\n"):
        with patch("services.pip.pip_installer.subprocess.check_output",
                   return_value=installed_packages):
            installer = PIPInstaller()
        with patch.object(installer, "_install_merged_dependencies") as mock_dep, \
             patch.object(installer, "_execute_install_scripts", return_value=[]), \
             patch.object(installer, "_reinstall_comfyui_requirements"), \
             patch("builtins.print"):
            mock_dep.return_value = DependencyInstallRecord(
                requirements_txt="", duration=0.0, success=True, error_msg=""
            )
            result = installer.install_all(timeout=60, nodes_map=nodes_map)
        return result, installer

    def test_result_has_required_keys(self):
        result, _ = self._run_install_all(nodes_map={})
        for key in ("baseline", "dependencies", "scripts"):
            self.assertIn(key, result)
        # problematic_deps 已移入 dependencies 内部
        self.assertNotIn("problematic_deps", result)

    def test_empty_nodes_map_no_dep_install_called(self):
        with patch("services.pip.pip_installer.subprocess.check_output",
                   return_value="Package Version\n"):
            installer = PIPInstaller()
        with patch.object(installer, "_install_merged_dependencies") as mock_dep, \
             patch("builtins.print"):
            result = installer.install_all(timeout=60, nodes_map={})
        mock_dep.assert_not_called()
        self.assertTrue(result["dependencies"]["success"])
        self.assertEqual(result["dependencies"]["requirements_txt"], "")
        self.assertEqual(result["scripts"], [])

    def test_none_nodes_map_installs_all_nodes(self):
        self._make_node("nodeA", requirements="requests\n")
        self._make_node("nodeB", requirements="numpy\n")
        result, installer = self._run_install_all(nodes_map=None)
        self.assertIsInstance(result["scripts"], list)

    def test_dependencies_structure(self):
        result, _ = self._run_install_all(nodes_map={})
        deps = result["dependencies"]
        for key in ("requirements_txt", "duration", "success", "error_msg", "problematic_deps"):
            self.assertIn(key, deps)

    def test_problematic_deps_inside_dependencies(self):
        """problematic_deps 位于 dependencies 内部，不在顶层"""
        result, _ = self._run_install_all(nodes_map={})
        self.assertIsInstance(result["dependencies"]["problematic_deps"], list)

    def test_timeout_during_merge_returns_partial_result(self):
        self._make_node("slow-node", requirements="requests\n")
        with patch("services.pip.pip_installer.subprocess.check_output",
                   return_value="Package Version\n"):
            installer = PIPInstaller()
        # 提供足够多的时间值：第1次返回 0（start_time），后续均返回 9999（已超时）
        with patch("time.time", side_effect=[0] + [9999] * 20), \
             patch("builtins.print"):
            result = installer.install_all(timeout=1, nodes_map=None)
        self.assertIsInstance(result, dict)
        self.assertIn("baseline", result)

    def test_blacklisted_packages_appear_in_problematic_deps(self):
        """黑名单包应出现在 dependencies.problematic_deps 中"""
        self._make_node("n", requirements="torch>=1.8.0\nrequests\n")
        with patch("services.pip.pip_installer.subprocess.check_output",
                   return_value="Package Version\n"):
            installer = PIPInstaller(blacklist=["torch"])
        # 不 mock _install_merged_dependencies，让过滤阶段真实运行，
        # mock subprocess.run 让 pip 安装成功
        with patch("subprocess.run",
                   return_value=subprocess.CompletedProcess(args=[], returncode=0)), \
             patch.object(installer, "_execute_install_scripts", return_value=[]), \
             patch.object(installer, "_reinstall_comfyui_requirements"), \
             patch("builtins.print"):
            result = installer.install_all(timeout=60, nodes_map=None)
        # problematic_deps 在 dependencies 内部，是 DependencyInfo 序列化后的 dict 列表
        prob_names = {d["package_name"] for d in result["dependencies"]["problematic_deps"]}
        self.assertTrue(any("torch" in name for name in prob_names))

    def test_step4_called_after_scripts(self):
        """install_all 正常流程中，_reinstall_comfyui_requirements 应被调用一次"""
        self._make_node("n", requirements="requests\n")
        with patch("services.pip.pip_installer.subprocess.check_output",
                   return_value="Package Version\n"):
            installer = PIPInstaller()
        with patch.object(installer, "_install_merged_dependencies") as mock_dep, \
             patch.object(installer, "_execute_install_scripts", return_value=[]), \
             patch.object(installer, "_reinstall_comfyui_requirements") as mock_step4, \
             patch("builtins.print"):
            mock_dep.return_value = DependencyInstallRecord(
                requirements_txt="", duration=0.0, success=True, error_msg=""
            )
            installer.install_all(timeout=60, nodes_map=None)
        mock_step4.assert_called_once()

    def test_step4_not_called_when_no_nodes(self):
        """没有节点时整个安装流程提前返回，Step 4 不应被调用"""
        with patch("services.pip.pip_installer.subprocess.check_output",
                   return_value="Package Version\n"):
            installer = PIPInstaller()
        with patch.object(installer, "_reinstall_comfyui_requirements") as mock_step4, \
             patch("builtins.print"):
            installer.install_all(timeout=60, nodes_map={})
        mock_step4.assert_not_called()

    def test_custom_nodes_dirs_scans_extra_dir(self):
        """custom_nodes_dirs 指定额外目录时，其中的插件应被识别"""
        extra_dir = os.path.join(self.tmp, "extra_nodes")
        os.makedirs(extra_dir)
        extra_node_dir = os.path.join(extra_dir, "extra-node")
        os.makedirs(extra_node_dir)
        with open(os.path.join(extra_node_dir, "requirements.txt"), "w") as f:
            f.write("requests\n")

        with patch("services.pip.pip_installer.subprocess.check_output",
                   return_value="Package Version\n"):
            installer = PIPInstaller()
        with patch.object(installer, "_install_merged_dependencies") as mock_dep, \
             patch.object(installer, "_execute_install_scripts", return_value=[]), \
             patch.object(installer, "_reinstall_comfyui_requirements"), \
             patch("builtins.print"):
            mock_dep.return_value = DependencyInstallRecord(
                requirements_txt="", duration=0.0, success=True, error_msg=""
            )
            result = installer.install_all(
                timeout=60,
                nodes_map=None,
                custom_nodes_dirs=[extra_dir],
            )
        self.assertIn("baseline", result)
        # extra-node 被扫描到，触发依赖安装流程
        mock_dep.assert_called_once()

    def test_custom_nodes_dirs_none_uses_default(self):
        """custom_nodes_dirs=None 时，应退回到默认的 custom_nodes 目录"""
        self._make_node("default-node", requirements="numpy\n")
        with patch("services.pip.pip_installer.subprocess.check_output",
                   return_value="Package Version\n"):
            installer = PIPInstaller()
        with patch.object(installer, "_install_merged_dependencies") as mock_dep, \
             patch.object(installer, "_execute_install_scripts", return_value=[]), \
             patch.object(installer, "_reinstall_comfyui_requirements"), \
             patch("builtins.print"):
            mock_dep.return_value = DependencyInstallRecord(
                requirements_txt="", duration=0.0, success=True, error_msg=""
            )
            installer.install_all(timeout=60, nodes_map=None, custom_nodes_dirs=None)
        mock_dep.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# 14. _install_merged_dependencies — 边界情况
#     （两轮完整链路由 batch_install_test.py 详细覆盖）
# ─────────────────────────────────────────────────────────────────────────────
class TestInstallMergedDependenciesEdgeCases(_Base):

    def setUp(self):
        super().setUp()
        self.inst = self._installer()

    def test_empty_deps_returns_success_immediately(self):
        """空依赖字典：立即返回成功，不调用 pip"""
        with patch("subprocess.run") as mock_run, patch("builtins.print"):
            record = self.inst._install_merged_dependencies(
                {}, timeout=600, start_time=time.time()
            )
        mock_run.assert_not_called()
        self.assertTrue(record.success)
        self.assertEqual(record.requirements_txt, "")
        self.assertEqual(record.problematic_deps, [])

    def test_global_timeout_all_deps_become_problematic(self):
        """全局超时：所有依赖进入 problematic_deps，success 仍为 True（两轮均优雅处理）"""
        deps = {"requests": self._dep("requests")}
        past_time = time.time() - 9999
        with patch("subprocess.run") as mock_run, patch("builtins.print"):
            record = self.inst._install_merged_dependencies(
                deps, timeout=1, start_time=past_time
            )
        mock_run.assert_not_called()
        self.assertTrue(record.success)
        self.assertEqual(len(record.problematic_deps), 1)

    def test_pip_success_on_first_batch(self):
        """第一轮批次成功：success=True，无 problematic_deps"""
        deps = {"requests": self._dep("requests")}
        with patch("subprocess.run",
                   return_value=subprocess.CompletedProcess(args=[], returncode=0)), \
             patch("builtins.print"):
            record = self.inst._install_merged_dependencies(
                deps, timeout=600, start_time=time.time()
            )
        self.assertTrue(record.success)
        self.assertEqual(record.problematic_deps, [])

    def test_batch_subprocess_timeout_dep_in_problematic(self):
        """批次 subprocess 超时：两轮均超时，依赖进入 problematic_deps，success=True"""
        deps = {"requests": self._dep("requests")}
        with patch("subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="pip", timeout=1)), \
             patch("builtins.print"):
            record = self.inst._install_merged_dependencies(
                deps, timeout=600, start_time=time.time()
            )
        self.assertTrue(record.success)
        self.assertEqual(len(record.problematic_deps), 1)
        self.assertEqual(record.problematic_deps[0].package_name, "requests")


# ─────────────────────────────────────────────────────────────────────────────
# 15. _reinstall_comfyui_requirements
# ─────────────────────────────────────────────────────────────────────────────
class TestReinstallComfyuiRequirements(_Base):

    def setUp(self):
        super().setUp()
        self.inst = self._installer()
        self.req_path = os.path.join(self.comfyui_dir, "requirements.txt")

    def _make_comfyui_requirements(self, content="torch>=2.0.0\nnumpy\n"):
        with open(self.req_path, "w") as f:
            f.write(content)

    def _call(self, timeout=600, elapsed=0.0):
        start_time = time.time() - elapsed
        with patch("builtins.print"):
            self.inst._reinstall_comfyui_requirements(timeout=timeout, start_time=start_time)

    def test_requirements_not_found_skips(self):
        """requirements.txt 不存在时直接跳过，不调用 pip"""
        with patch("subprocess.run") as mock_run, patch("builtins.print"):
            self.inst._reinstall_comfyui_requirements(timeout=600, start_time=time.time())
        mock_run.assert_not_called()

    def test_already_timed_out_skips(self):
        """全局超时已耗尽时直接跳过，不调用 pip"""
        self._make_comfyui_requirements()
        with patch("subprocess.run") as mock_run, patch("builtins.print"):
            # elapsed > timeout
            self.inst._reinstall_comfyui_requirements(timeout=1, start_time=time.time() - 9999)
        mock_run.assert_not_called()

    def test_pip_install_success(self):
        """pip install -r requirements.txt 成功（returncode=0）"""
        self._make_comfyui_requirements()
        mock_result = subprocess.CompletedProcess(args=[], returncode=0)
        with patch("subprocess.run", return_value=mock_result) as mock_run, \
             patch("builtins.print"):
            self.inst._reinstall_comfyui_requirements(timeout=600, start_time=time.time())
        mock_run.assert_called_once()
        cmd_args = mock_run.call_args[0][0]
        self.assertIn("install", cmd_args)
        self.assertIn("-r", cmd_args)
        self.assertIn(self.req_path, cmd_args)

    def test_pip_install_failure_returncode(self):
        """pip install 返回非零 returncode 时，方法仍正常结束（不抛异常）"""
        self._make_comfyui_requirements()
        mock_result = subprocess.CompletedProcess(args=[], returncode=1)
        with patch("subprocess.run", return_value=mock_result), \
             patch("builtins.print") as mock_print:
            self.inst._reinstall_comfyui_requirements(timeout=600, start_time=time.time())
        printed = " ".join(str(c) for c in mock_print.call_args_list)
        self.assertIn("returncode=1", printed)

    def test_pip_install_timeout_expired(self):
        """subprocess.TimeoutExpired 时，方法正常结束（不向外抛异常）"""
        self._make_comfyui_requirements()
        with patch("subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="pip", timeout=1)), \
             patch("builtins.print") as mock_print:
            self.inst._reinstall_comfyui_requirements(timeout=600, start_time=time.time())
        printed = " ".join(str(c) for c in mock_print.call_args_list)
        self.assertIn("Timed out", printed)

    def test_pip_cmd_uses_venv_executable(self):
        """pip 命令应以 VENV_EXECUTABLE -m pip 开头"""
        self._make_comfyui_requirements()
        mock_result = subprocess.CompletedProcess(args=[], returncode=0)
        with patch("subprocess.run", return_value=mock_result) as mock_run, \
             patch("builtins.print"):
            self.inst._reinstall_comfyui_requirements(timeout=600, start_time=time.time())
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[0], "/fake/venv/bin/python")
        self.assertEqual(cmd[1], "-m")
        self.assertEqual(cmd[2], "pip")

    def test_pip_env_has_no_proxy(self):
        """pip install 执行时环境变量中不含代理设置"""
        self._make_comfyui_requirements()
        mock_result = subprocess.CompletedProcess(args=[], returncode=0)
        base_env = {
            "PATH": "/usr/bin",
            "http_proxy": "http://proxy:8080",
            "HTTPS_PROXY": "https://proxy:8080",
        }
        with patch("subprocess.run", return_value=mock_result) as mock_run, \
             patch("os.environ.copy", return_value=base_env.copy()), \
             patch("builtins.print"):
            self.inst._reinstall_comfyui_requirements(timeout=600, start_time=time.time())
        used_env = mock_run.call_args[1]["env"]
        self.assertNotIn("http_proxy", used_env)
        self.assertNotIn("HTTPS_PROXY", used_env)
        self.assertIn("PATH", used_env)

    def test_uses_fallback_index_url(self):
        """Step 4 应使用 fallback 源，不受 pip.conf 中其他镜像源影响"""
        self._make_comfyui_requirements()
        mock_result = subprocess.CompletedProcess(args=[], returncode=0)
        base_env = {
            "PATH": "/usr/bin",
            "PIP_EXTRA_INDEX_URL": "https://some.other.mirror/simple/",
        }
        with patch("subprocess.run", return_value=mock_result) as mock_run, \
             patch("os.environ.copy", return_value=base_env.copy()), \
             patch("builtins.print"):
            self.inst._reinstall_comfyui_requirements(timeout=600, start_time=time.time())
        used_env = mock_run.call_args[1]["env"]
        self.assertEqual(used_env["PIP_INDEX_URL"], "https://mirrors.aliyun.com/pypi/simple/")
        self.assertNotIn("PIP_EXTRA_INDEX_URL", used_env)

    def test_remaining_timeout_passed_to_subprocess(self):
        """subprocess.run 的 timeout 参数应等于剩余时间（总超时 - 已耗时）"""
        self._make_comfyui_requirements()
        mock_result = subprocess.CompletedProcess(args=[], returncode=0)
        with patch("subprocess.run", return_value=mock_result) as mock_run, \
             patch("builtins.print"):
            start = time.time() - 10   # 已耗时 ~10s
            self.inst._reinstall_comfyui_requirements(timeout=600, start_time=start)
        used_timeout = mock_run.call_args[1]["timeout"]
        self.assertAlmostEqual(used_timeout, 590, delta=2)


# ─────────────────────────────────────────────────────────────────────────────
# 16. timed_out 字段追踪
# ─────────────────────────────────────────────────────────────────────────────
class TestTimedOutTracking(_Base):
    """验证 install_all 及各步骤中 _timed_out 状态追踪的正确性"""

    def test_no_nodes_returns_timed_out_false(self):
        """没有节点时直接返回，timed_out=False"""
        with patch("services.pip.pip_installer.subprocess.check_output",
                   return_value="Package Version\n"):
            installer = PIPInstaller()
        with patch("builtins.print"):
            result = installer.install_all(timeout=60, nodes_map={})
        self.assertIn("timed_out", result)
        self.assertFalse(result["timed_out"])

    def test_normal_install_timed_out_false(self):
        """正常安装完成 → timed_out=False"""
        self._make_node("node-a", requirements="requests\n")
        with patch("services.pip.pip_installer.subprocess.check_output",
                   return_value="Package Version\n"):
            installer = PIPInstaller()
        with patch("subprocess.run",
                   return_value=subprocess.CompletedProcess(args=[], returncode=0)), \
             patch.object(installer, "_execute_install_scripts", return_value=[]), \
             patch.object(installer, "_reinstall_comfyui_requirements"), \
             patch("builtins.print"):
            result = installer.install_all(timeout=600, nodes_map=None)
        self.assertFalse(result["timed_out"])
        self.assertFalse(installer._timed_out)

    def test_timeout_in_merge_sets_timed_out_true(self):
        """merge 阶段超时 → timed_out=True"""
        self._make_node("slow-node", requirements="requests\n")
        with patch("services.pip.pip_installer.subprocess.check_output",
                   return_value="Package Version\n"):
            installer = PIPInstaller()
        with patch("time.time", side_effect=[0] + [9999] * 20), \
             patch("builtins.print"):
            result = installer.install_all(timeout=1, nodes_map=None)
        self.assertTrue(result["timed_out"])
        self.assertTrue(installer._timed_out)

    def test_batch_timeout_sets_timed_out_true(self):
        """第一轮批次安装超时 → _timed_out=True"""
        self._make_node("node-a", requirements="requests\nnumpy\n")
        with patch("services.pip.pip_installer.subprocess.check_output",
                   return_value="Package Version\n"):
            installer = PIPInstaller()

        call_count = [0]
        def mock_time():
            call_count[0] += 1
            if call_count[0] <= 3:
                return 0.0
            return 9999.0

        with patch("time.time", side_effect=mock_time), \
             patch("subprocess.run",
                   return_value=subprocess.CompletedProcess(args=[], returncode=0)), \
             patch.object(installer, "_execute_install_scripts", return_value=[]), \
             patch.object(installer, "_reinstall_comfyui_requirements"), \
             patch("builtins.print"):
            self.mock_constants.INSTALL_BATCH_SIZE = 1
            result = installer.install_all(timeout=1, nodes_map=None)
        self.assertTrue(installer._timed_out)

    def test_round2_timeout_sets_timed_out_true(self):
        """第二轮逐个安装超时 → _timed_out=True，剩余包进入 problematic_deps"""
        with patch("services.pip.pip_installer.subprocess.check_output",
                   return_value="Package Version\n"):
            installer = PIPInstaller()
        installer._timed_out = False
        installer._problematic_deps = {}
        deps = [self._dep("pkg-a"), self._dep("pkg-b")]

        # start_time 远在过去 → remaining <= 0，立即超时
        past_start = time.time() - 9999
        with patch("builtins.print"):
            installer._install_individually(deps, timeout=1, start_time=past_start)

        self.assertTrue(installer._timed_out)
        self.assertEqual(len(installer._problematic_deps), 2)

    def test_step3_skipped_on_timeout_sets_timed_out_true(self):
        """Step 3（install.py 脚本执行）因超时被跳过 → _timed_out=True"""
        with patch("services.pip.pip_installer.subprocess.check_output",
                   return_value="Package Version\n"):
            installer = PIPInstaller()
        installer._timed_out = False

        past_time = time.time() - 9999
        with patch("builtins.print"):
            result = installer._execute_install_scripts(
                ["node-a"], {"node-a": "/fake/path"}, timeout=1, start_time=past_time
            )
        self.assertEqual(result, [])
        self.assertTrue(installer._timed_out)

    def test_step4_skipped_on_timeout_sets_timed_out_true(self):
        """Step 4（重装 ComfyUI 依赖）因超时被跳过 → _timed_out=True"""
        with patch("services.pip.pip_installer.subprocess.check_output",
                   return_value="Package Version\n"):
            installer = PIPInstaller()
        installer._timed_out = False

        past_time = time.time() - 9999
        with patch("builtins.print"):
            installer._reinstall_comfyui_requirements(timeout=1, start_time=past_time)
        self.assertTrue(installer._timed_out)

    def test_timed_out_reset_each_install_all_call(self):
        """每次 install_all 调用 → _timed_out 重新初始化为 False"""
        with patch("services.pip.pip_installer.subprocess.check_output",
                   return_value="Package Version\n"):
            installer = PIPInstaller()
        installer._timed_out = True

        with patch("builtins.print"):
            result = installer.install_all(timeout=60, nodes_map={})
        self.assertFalse(result["timed_out"])
        self.assertFalse(installer._timed_out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
