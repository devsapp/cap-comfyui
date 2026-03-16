"""
内置插件 Delta Directory 管理模块

采用 Delta Directory 模式：
1. 维护 /root/built-in/custom_nodes_delta/，仅包含用户 NAS 中不存在的内置插件的软链接。
2. 配置 extra_model_paths.yaml，追加 Delta 目录，使内置插件在用户插件之后加载。
"""

import os
import shutil

from utils.logger import log
import constants

BUILTIN_VERSION_FILE = os.path.join(os.path.dirname(constants.BUILTIN_NODES_DIR), "version.txt")
INSTALLED_VERSION_FILE = os.path.join(constants.MNT_DIR, ".funart", "dependency_version.txt")

def setup_builtin_custom_nodes(
    comfyui_dir: str = constants.COMFYUI_DIR,
    user_nodes_dir: str = None,
    builtin_src_dir: str = constants.BUILTIN_NODES_DIR,
    builtin_delta_dir: str = constants.BUILTIN_DELTA_NODES_DIR,
) -> None:
    if not os.path.exists(INSTALLED_VERSION_FILE):
        # 首次启动时，版本文件不存在，跳过内置插件 setup
        log("INFO", f"[BuiltinCustomNodes] Dependency version file not found at {INSTALLED_VERSION_FILE}, skipping built-in nodes setup.")
        return

    if user_nodes_dir is None:
        user_nodes_dir = os.path.join(constants.MNT_DIR, "custom_nodes")

    log("INFO", "[BuiltinCustomNodes] Setting up Delta Directory...")

    # 步骤 1：准备 Delta 目录
    if os.path.exists(builtin_delta_dir):
        shutil.rmtree(builtin_delta_dir)
    os.makedirs(builtin_delta_dir)

    # 步骤 2：扫描用户插件目录 (大小写不敏感)
    os.makedirs(user_nodes_dir, exist_ok=True)
    user_node_names = set()
    try:
        user_node_names = {
            name.lower()
            for name in os.listdir(user_nodes_dir)
            if os.path.isdir(os.path.join(user_nodes_dir, name))
        }
    except Exception as e:
        log("ERROR", f"[BuiltinCustomNodes] Failed to scan user nodes dir: {e}")

    # 步骤 3：填充 Delta 目录 (排除与用户插件冲突的内置插件)
    if not os.path.isdir(builtin_src_dir):
        log("WARNING", f"[BuiltinCustomNodes] Built-in dir not found: {builtin_src_dir}")
    else:
        linked = skipped = 0
        for name in os.listdir(builtin_src_dir):
            if name.startswith(".") or name.startswith("__"):
                continue

            if name.lower() in user_node_names:
                skipped += 1
                continue

            src_path = os.path.join(builtin_src_dir, name)
            if not os.path.isdir(src_path):
                continue

            link_path = os.path.join(builtin_delta_dir, name)
            try:
                os.symlink(src_path, link_path)
                linked += 1
            except Exception as e:
                log("ERROR", f"[BuiltinCustomNodes] Failed to link {name}: {e}")

        log(
            "INFO",
            f"[BuiltinCustomNodes] Delta dir ready: {linked} linked, {skipped} skipped (user overrides)",
        )

    # 步骤 4：按需安装内置插件依赖（安装成功后再写入配置，避免依赖缺失时 ComfyUI 加载残缺的 delta 目录）
    # TODO: 安装失败也会继续走到下一步
    _install_builtin_dependencies_if_needed(user_nodes_dir, builtin_src_dir)

    # 步骤 5：写入 extra_model_paths.yaml
    _write_config(comfyui_dir, builtin_delta_dir)


def get_builtin_version() -> str:
    """读取镜像内嵌的内置版本号"""
    try:
        with open(BUILTIN_VERSION_FILE) as f:
            return f.read().strip()
    except Exception:
        return "unknown"


def get_installed_dependency_version() -> str:
    """读取 NAS 上记录的已安装版本号，不存在时返回空字符串（视为需要安装）"""
    try:
        with open(INSTALLED_VERSION_FILE) as f:
            return f.read().strip()
    except Exception:
        return ""


def _save_installed_dependency_version(version: str) -> None:
    """安装完成后将版本号持久化到 NAS"""
    try:
        os.makedirs(os.path.dirname(INSTALLED_VERSION_FILE), exist_ok=True)
        with open(INSTALLED_VERSION_FILE, "w") as f:
            f.write(version)
    except Exception as e:
        log("ERROR", f"[BuiltinCustomNodes] Failed to save installed version: {e}")


def _install_builtin_dependencies_if_needed(user_nodes_dir: str, builtin_src_dir: str) -> None:
    """按需安装内置插件依赖：版本文件不存在则跳过，版本一致则跳过，版本变化才安装"""
    # 前置检查在 setup_builtin_custom_nodes 中已完成，此处理论上不会触发，保留作防御性校验
    if not os.path.exists(INSTALLED_VERSION_FILE):
        log("INFO", f"[BuiltinCustomNodes] Dependency version file not found at {INSTALLED_VERSION_FILE}, skipping dependency install.")
        return

    builtin_ver = get_builtin_version()
    installed_ver = get_installed_dependency_version()

    if builtin_ver == installed_ver:
        log("INFO", f"[BuiltinCustomNodes] Built-in dependencies are up-to-date (installed={builtin_ver}), skipping install.")
        return

    log("INFO", f"[BuiltinCustomNodes] Built-in dependency version changed: {installed_ver!r} -> {builtin_ver!r}. Starting dependency install...")

    from services.pip.pip_installer import PIPInstaller
    installer = PIPInstaller()
    installer.install_all(custom_nodes_dirs=[user_nodes_dir, builtin_src_dir])

    # 安装成功后持久化版本号；若安装中途失败则不更新，下次启动时会自动重试
    _save_installed_dependency_version(builtin_ver)
    log("INFO", f"[BuiltinCustomNodes] Dependency install complete, version updated to {builtin_ver!r}.")


def _write_config(comfyui_dir: str, builtin_delta_dir: str) -> None:
    extra_paths_file = os.path.join(comfyui_dir, "extra_model_paths.yaml")
    delta_base = os.path.dirname(builtin_delta_dir)  # /root/built-in
    delta_name = os.path.basename(builtin_delta_dir)  # custom_nodes_delta

    yaml_block = (
        f"\nfunart_builtin_custom_nodes:\n"
        f"    base_path: {delta_base}\n"
        f"    custom_nodes: {delta_name}/\n"
    )

    if not os.path.exists(extra_paths_file):
        with open(extra_paths_file, "w") as f:
            f.write(yaml_block.lstrip())
    else:
        with open(extra_paths_file) as f:
            content = f.read()
        if "funart_builtin_custom_nodes" not in content:
            with open(extra_paths_file, "a") as f:
                f.write(yaml_block)
