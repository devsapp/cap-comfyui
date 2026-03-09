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

BUILTIN_NODES_DIR = os.getenv("BUILTIN_NODES_DIR", "/root/built-in/custom_nodes")
BUILTIN_DELTA_DIR = os.getenv("BUILTIN_DELTA_DIR", "/root/built-in/custom_nodes_delta")


def setup_builtin_custom_nodes(
    comfyui_dir: str = constants.COMFYUI_DIR,
    user_nodes_dir: str = None,
    builtin_src_dir: str = BUILTIN_NODES_DIR,
    builtin_delta_dir: str = BUILTIN_DELTA_DIR,
) -> None:
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

    # 步骤 4：写入 extra_model_paths.yaml
    _write_config(comfyui_dir, builtin_delta_dir)


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
