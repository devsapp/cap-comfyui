"""
builtin_custom_nodes 单元测试
==============================
覆盖 services/custom_nodes/builtin_custom_nodes.py 的完整功能：
- setup_builtin_custom_nodes：Delta 目录构建、软链接逻辑、config 写入、版本文件缺失时跳过
- 版本文件读写：get_builtin_version / get_installed_dependency_version / _save_installed_dependency_version
- 按需安装依赖：_install_builtin_dependencies_if_needed
"""
import os
import shutil
import tempfile
from unittest.mock import patch, MagicMock

import pytest

import services.custom_nodes.builtin_custom_nodes as bcn_module
from services.custom_nodes.builtin_custom_nodes import (
    setup_builtin_custom_nodes,
    get_builtin_version,
    get_installed_dependency_version,
    _save_installed_dependency_version,
)


# ==================== Fixtures ====================

@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def setup_env(tmp_dir):
    """setup_builtin_custom_nodes 所需的完整目录结构 + 已存在的版本文件"""
    env = {
        "comfyui_dir": os.path.join(tmp_dir, "comfyui"),
        "user_nodes_dir": os.path.join(tmp_dir, "nas", "custom_nodes"),
        "builtin_src_dir": os.path.join(tmp_dir, "built-in", "custom_nodes"),
        "builtin_delta_dir": os.path.join(tmp_dir, "built-in", "custom_nodes_delta"),
        "installed_ver_file": os.path.join(tmp_dir, ".funart", "dependency_version.txt"),
    }
    os.makedirs(env["comfyui_dir"])
    os.makedirs(env["user_nodes_dir"])
    os.makedirs(env["builtin_src_dir"])
    os.makedirs(os.path.dirname(env["installed_ver_file"]), exist_ok=True)
    with open(env["installed_ver_file"], "w") as f:
        f.write("v1.0.0")
    return env


@pytest.fixture
def install_env(tmp_dir):
    """_install_builtin_dependencies_if_needed 所需的目录结构"""
    env = {
        "user_nodes_dir": os.path.join(tmp_dir, "nas", "custom_nodes"),
        "builtin_src_dir": os.path.join(tmp_dir, "built-in", "custom_nodes"),
        "builtin_ver_file": os.path.join(tmp_dir, "version.txt"),
        "installed_ver_file": os.path.join(tmp_dir, ".funart", "dependency_version.txt"),
    }
    os.makedirs(env["user_nodes_dir"])
    os.makedirs(env["builtin_src_dir"])
    return env


def _call_setup(env):
    """调用 setup，mock 掉依赖安装步骤，专注于 Delta 目录逻辑"""
    with patch.object(bcn_module, "INSTALLED_VERSION_FILE", env["installed_ver_file"]), \
         patch.object(bcn_module, "_install_builtin_dependencies_if_needed"):
        setup_builtin_custom_nodes(
            comfyui_dir=env["comfyui_dir"],
            user_nodes_dir=env["user_nodes_dir"],
            builtin_src_dir=env["builtin_src_dir"],
            builtin_delta_dir=env["builtin_delta_dir"],
        )


def _call_install(env):
    with patch.object(bcn_module, "BUILTIN_VERSION_FILE", env["builtin_ver_file"]), \
         patch.object(bcn_module, "INSTALLED_VERSION_FILE", env["installed_ver_file"]):
        bcn_module._install_builtin_dependencies_if_needed(
            env["user_nodes_dir"], env["builtin_src_dir"]
        )


def _write_ver(path: str, ver: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(ver)


# ==================== 一、setup_builtin_custom_nodes 测试 ====================

class TestSetupBuiltinCustomNodes:
    """测试 setup_builtin_custom_nodes 的 Delta Directory 构建逻辑"""

    def test_skips_entire_setup_when_version_file_missing(self, setup_env):
        """INSTALLED_VERSION_FILE 不存在时，跳过整个 setup，不创建 delta 目录或写入 config"""
        with patch.object(bcn_module, "INSTALLED_VERSION_FILE", "/nonexistent/dep_version.txt"):
            setup_builtin_custom_nodes(
                comfyui_dir=setup_env["comfyui_dir"],
                user_nodes_dir=setup_env["user_nodes_dir"],
                builtin_src_dir=setup_env["builtin_src_dir"],
                builtin_delta_dir=setup_env["builtin_delta_dir"],
            )

        assert not os.path.exists(setup_env["builtin_delta_dir"])
        assert not os.path.exists(os.path.join(setup_env["comfyui_dir"], "extra_model_paths.yaml"))

    def test_prepares_delta_dir_creates_when_missing(self, setup_env):
        """Delta 目录不存在时，自动创建"""
        _call_setup(setup_env)

        assert os.path.isdir(setup_env["builtin_delta_dir"])

    def test_prepares_delta_dir_rebuilds_when_exists(self, setup_env):
        """Delta 目录已存在时，先清空再重建（清除过期软链接）"""
        os.makedirs(setup_env["builtin_delta_dir"])
        stale_file = os.path.join(setup_env["builtin_delta_dir"], "stale_link")
        open(stale_file, "w").close()

        _call_setup(setup_env)

        assert os.path.isdir(setup_env["builtin_delta_dir"])
        assert not os.path.exists(stale_file)

    def test_links_builtin_not_in_nas(self, setup_env):
        """NAS 中不存在的内置插件，在 delta 目录创建软链接"""
        plugin_src = os.path.join(setup_env["builtin_src_dir"], "ComfyUI-Advanced")
        os.makedirs(plugin_src)

        _call_setup(setup_env)

        link_path = os.path.join(setup_env["builtin_delta_dir"], "ComfyUI-Advanced")
        assert os.path.islink(link_path)
        assert os.readlink(link_path) == plugin_src

    def test_skips_builtin_already_in_nas(self, setup_env):
        """NAS 中已存在的内置插件，不创建软链接（用户插件优先）"""
        os.makedirs(os.path.join(setup_env["builtin_src_dir"], "ComfyUI-ControlNet"))
        os.makedirs(os.path.join(setup_env["user_nodes_dir"], "ComfyUI-ControlNet"))

        _call_setup(setup_env)

        link_path = os.path.join(setup_env["builtin_delta_dir"], "ComfyUI-ControlNet")
        assert not os.path.exists(link_path)

    def test_case_insensitive_exclusion(self, setup_env):
        """排除逻辑忽略大小写（内置: ComfyUI-Plugin，NAS: comfyui-plugin）"""
        os.makedirs(os.path.join(setup_env["builtin_src_dir"], "ComfyUI-Plugin"))
        os.makedirs(os.path.join(setup_env["user_nodes_dir"], "comfyui-plugin"))

        _call_setup(setup_env)

        link_path = os.path.join(setup_env["builtin_delta_dir"], "ComfyUI-Plugin")
        assert not os.path.exists(link_path)

    def test_nas_dir_created_if_missing(self, setup_env):
        """user_nodes_dir 不存在时，自动创建"""
        shutil.rmtree(setup_env["user_nodes_dir"])

        _call_setup(setup_env)

        assert os.path.isdir(setup_env["user_nodes_dir"])

    def test_writes_extra_model_paths_when_file_missing(self, setup_env):
        """extra_model_paths.yaml 不存在时，新建并写入 delta 目录配置"""
        _call_setup(setup_env)

        config_file = os.path.join(setup_env["comfyui_dir"], "extra_model_paths.yaml")
        assert os.path.exists(config_file)
        content = open(config_file).read()
        assert "funart_builtin_custom_nodes" in content
        assert "custom_nodes_delta" in content

    def test_writes_extra_model_paths_appends_when_file_exists(self, setup_env):
        """extra_model_paths.yaml 已存在但无 funart 块时，追加配置"""
        config_file = os.path.join(setup_env["comfyui_dir"], "extra_model_paths.yaml")
        with open(config_file, "w") as f:
            f.write("existing_config:\n    base_path: /some/path\n")

        _call_setup(setup_env)

        content = open(config_file).read()
        assert "existing_config" in content
        assert "funart_builtin_custom_nodes" in content

    def test_does_not_duplicate_extra_model_paths(self, setup_env):
        """extra_model_paths.yaml 已含 funart 块时，不重复追加"""
        config_file = os.path.join(setup_env["comfyui_dir"], "extra_model_paths.yaml")
        with open(config_file, "w") as f:
            f.write("funart_builtin_custom_nodes:\n    base_path: /old\n    custom_nodes: delta/\n")

        _call_setup(setup_env)

        content = open(config_file).read()
        assert content.count("funart_builtin_custom_nodes") == 1

    def test_ignores_non_directory_entries_in_builtin_src(self, setup_env):
        """内置插件目录中的普通文件不创建软链接"""
        open(os.path.join(setup_env["builtin_src_dir"], "README.md"), "w").close()

        _call_setup(setup_env)

        assert not os.path.exists(os.path.join(setup_env["builtin_delta_dir"], "README.md"))

    def test_ignores_hidden_and_dunder_entries_in_builtin_src(self, setup_env):
        """内置插件目录中以 '.' 或 '__' 开头的条目不处理"""
        os.makedirs(os.path.join(setup_env["builtin_src_dir"], ".hidden_plugin"))
        os.makedirs(os.path.join(setup_env["builtin_src_dir"], "__pycache__"))

        _call_setup(setup_env)

        assert not os.path.exists(os.path.join(setup_env["builtin_delta_dir"], ".hidden_plugin"))
        assert not os.path.exists(os.path.join(setup_env["builtin_delta_dir"], "__pycache__"))


# ==================== 二、版本文件读取测试 ====================

class TestGetBuiltinVersion:
    """测试 get_builtin_version"""

    def test_reads_version_from_file(self, tmp_dir):
        """从 /root/built-in/version.txt 读取版本号"""
        ver_file = os.path.join(tmp_dir, "version.txt")
        with open(ver_file, "w") as f:
            f.write("v2.0.0\n")

        with patch.object(bcn_module, "BUILTIN_VERSION_FILE", ver_file):
            result = get_builtin_version()

        assert result == "v2.0.0"

    def test_returns_unknown_if_file_missing(self):
        """文件不存在时返回 "unknown"""
        with patch.object(bcn_module, "BUILTIN_VERSION_FILE", "/nonexistent/path/version.txt"):
            result = get_builtin_version()

        assert result == "unknown"


class TestGetInstalledDependencyVersion:
    """测试 get_installed_dependency_version"""

    def test_reads_version_from_nas(self, tmp_dir):
        """从 NAS 标记文件读取已安装版本"""
        ver_file = os.path.join(tmp_dir, "dep_version.txt")
        with open(ver_file, "w") as f:
            f.write("v1.0.0")

        with patch.object(bcn_module, "INSTALLED_VERSION_FILE", ver_file):
            result = get_installed_dependency_version()

        assert result == "v1.0.0"

    def test_returns_empty_string_if_file_missing(self):
        """NAS 文件不存在时返回 ""（触发安装）"""
        with patch.object(bcn_module, "INSTALLED_VERSION_FILE", "/nonexistent/path/dep_version.txt"):
            result = get_installed_dependency_version()

        assert result == ""


# ==================== 三、_install_builtin_dependencies_if_needed 测试 ====================

class TestInstallBuiltinDependenciesIfNeeded:
    """测试 _install_builtin_dependencies_if_needed"""

    def test_skips_when_version_file_missing(self, install_env):
        """INSTALLED_VERSION_FILE 不存在时，直接跳过，不调用 PIPInstaller"""
        with patch.object(bcn_module, "INSTALLED_VERSION_FILE", "/nonexistent/dep_version.txt"), \
             patch("services.pip.pip_installer.PIPInstaller") as mock_pip:
            bcn_module._install_builtin_dependencies_if_needed(
                install_env["user_nodes_dir"], install_env["builtin_src_dir"]
            )

        mock_pip.assert_not_called()

    def test_skips_when_version_matches(self, install_env):
        """版本一致时不调用 PIPInstaller"""
        _write_ver(install_env["builtin_ver_file"], "v2.0.0")
        _write_ver(install_env["installed_ver_file"], "v2.0.0")

        with patch("services.pip.pip_installer.PIPInstaller") as mock_pip:
            _call_install(install_env)

        mock_pip.assert_not_called()

    def test_installs_when_version_differs(self, install_env):
        """版本不一致时调用 PIPInstaller，传入 user_nodes_dir 和 builtin_src_dir"""
        _write_ver(install_env["builtin_ver_file"], "v2.0.0")
        _write_ver(install_env["installed_ver_file"], "v1.0.0")

        mock_installer = MagicMock()
        with patch("services.pip.pip_installer.PIPInstaller", return_value=mock_installer):
            _call_install(install_env)

        mock_installer.install_all.assert_called_once_with(
            custom_nodes_dirs=[install_env["user_nodes_dir"], install_env["builtin_src_dir"]]
        )

    def test_updates_version_file_after_install(self, install_env):
        """安装成功后，将 builtin_ver 持久化到 INSTALLED_VERSION_FILE"""
        _write_ver(install_env["builtin_ver_file"], "v2.0.0")
        _write_ver(install_env["installed_ver_file"], "v1.0.0")

        with patch("services.pip.pip_installer.PIPInstaller", return_value=MagicMock()):
            _call_install(install_env)

        assert open(install_env["installed_ver_file"]).read().strip() == "v2.0.0"

    def test_does_not_update_version_on_failure(self, install_env):
        """安装失败时不更新 NAS 版本标记，下次启动会重试"""
        _write_ver(install_env["builtin_ver_file"], "v2.0.0")
        _write_ver(install_env["installed_ver_file"], "v1.0.0")

        mock_installer = MagicMock()
        mock_installer.install_all.side_effect = Exception("pip install failed")

        with patch("services.pip.pip_installer.PIPInstaller", return_value=mock_installer):
            with pytest.raises(Exception, match="pip install failed"):
                _call_install(install_env)

        assert open(install_env["installed_ver_file"]).read().strip() == "v1.0.0"

    def test_save_installed_dependency_version_tolerates_write_error(self):
        """NAS 不可写时捕获异常，不中断主流程"""
        with patch.object(bcn_module, "INSTALLED_VERSION_FILE", "/nonexistent/readonly/dep_version.txt"), \
             patch("os.makedirs", side_effect=OSError("read-only filesystem")):
            _save_installed_dependency_version("v2.0.0")
