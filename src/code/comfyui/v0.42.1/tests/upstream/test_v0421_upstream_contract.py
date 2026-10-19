"""Contract tests against a real v0.42.1 checkout without loading CUDA.

COMFYUI_UPSTREAM_DIR=/path/to/ComfyUI python -m pytest <this-directory>
Functions are compiled directly from upstream ASTs, not copied test doubles.
"""

import ast
import asyncio
import importlib
import os
from pathlib import Path
import sys
import types
import uuid

import pytest


UPSTREAM = os.environ.get("COMFYUI_UPSTREAM_DIR")
pytestmark = pytest.mark.skipif(not UPSTREAM, reason="set COMFYUI_UPSTREAM_DIR")
COMFYUI = Path(__file__).resolve().parents[3]


def _tree(filename):
    return ast.parse((Path(UPSTREAM) / filename).read_text())


def _function(filename, name, class_name=None):
    tree = _tree(filename)
    if class_name:
        tree = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    return next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def _compile(functions, namespace):
    exec(compile(ast.Module(body=functions, type_ignores=[]), "<upstream>", "exec"), namespace)


def _plugin(monkeypatch, name, directory):
    package = types.ModuleType(name)
    package.__path__ = [str(directory)]
    monkeypatch.setitem(sys.modules, name, package)
    return lambda module: importlib.import_module(f"{name}.{module}")


def test_upstream_task_id_validator_is_patched_in_both_namespaces(monkeypatch):
    namespace = {"uuid": uuid}
    _compile([_function("comfy_execution/jobs.py", "validate_job_id")], namespace)
    jobs = types.SimpleNamespace(validate_job_id=namespace["validate_job_id"])
    server = types.SimpleNamespace(validate_job_id=jobs.validate_job_id)
    task_id = "1-6a992ac9-174ae003-e532a22e47b1"
    with pytest.raises(ValueError):
        server.validate_job_id(task_id)
    plugin = _plugin(monkeypatch, "v0421_upstream_prompt", COMFYUI / "custom_nodes/funart_prompt_id_compat")
    assert plugin("prompt_id_compat").install_prompt_id_compat(server, jobs)
    assert server.validate_job_id(task_id) == jobs.validate_job_id(task_id) == task_id
    for invalid in [None, {}, 1, ""]:
        with pytest.raises(ValueError):
            server.validate_job_id(invalid)


def test_upstream_executor_keeps_user_context_through_async_execution(monkeypatch):
    method = _function("execution.py", "execute", "PromptExecutor")
    assert isinstance(method, ast.FunctionDef)
    namespace = {"asyncio": asyncio}
    _compile([method], namespace)
    plugin = _plugin(monkeypatch, "v0421_upstream_execution", COMFYUI / "custom_nodes/FunArt-ComfyUI-Multi-User")
    context = plugin("context")
    observed = []

    class Executor:
        execute = namespace["execute"]

        async def execute_async(self, prompt, prompt_id, extra_data, execute_outputs):
            await asyncio.sleep(0)
            observed.append((prompt_id, context.get_current_user()))

    monkeypatch.setitem(sys.modules, "execution", types.SimpleNamespace(PromptExecutor=Executor))
    plugin("execution_patch").install_execution_patch()
    for user in ("tenant-a", "tenant-b"):
        Executor().execute({}, f"fc-{user}", {"x-funart-comfy-userid": user}, [])
        assert context.get_current_user() == "default"
    assert observed == [("fc-tenant-a", "tenant-a"), ("fc-tenant-b", "tenant-b")]


def test_upstream_cache_signature_hook_remains_async_and_compatible():
    method = _function("comfy_execution/caching.py", "get_immediate_node_signature", "CacheKeySetInputSignature")
    assert isinstance(method, ast.AsyncFunctionDef)
    assert [arg.arg for arg in method.args.args] == ["self", "dynprompt", "node_id", "ancestor_order_mapping"]


def test_upstream_folder_paths_respect_tenants_and_traversal_checks(monkeypatch, tmp_path):
    names = ["get_input_directory", "get_output_directory", "get_temp_directory", "get_user_directory", "get_directory_by_type", "annotated_filepath", "is_within_directory", "get_annotated_filepath", "exists_annotated_filepath"]
    folder_paths = types.ModuleType("folder_paths")
    folder_paths.os = os
    for kind in ("input", "output", "temp", "user"):
        setattr(folder_paths, f"{kind}_directory", str(tmp_path / kind))
    folder_paths.get_save_image_path = lambda *args: args
    _compile([_function("folder_paths.py", name) for name in names], vars(folder_paths))
    monkeypatch.setitem(sys.modules, "folder_paths", folder_paths)
    plugin = _plugin(monkeypatch, "v0421_upstream_folders", COMFYUI / "custom_nodes/FunArt-ComfyUI-Multi-User")
    plugin("folder_paths_patch").install_folder_paths_patch()
    context = plugin("context")
    try:
        for user in ("tenant-a", "tenant-b"):
            context.set_current_user(user)
            expected = tmp_path / "input" / "users" / user / "image.png"
            assert os.fspath(folder_paths.get_input_directory()) == str(expected.parent)
            expected.write_bytes(user.encode())
            assert folder_paths.get_annotated_filepath("image.png [input]") == str(expected)
            assert folder_paths.exists_annotated_filepath("image.png")
            assert not folder_paths.exists_annotated_filepath("../tenant-other/private.png")
            with pytest.raises(ValueError):
                folder_paths.get_annotated_filepath("../tenant-other/private.png")
    finally:
        context.clear_current_user()
