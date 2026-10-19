#!/usr/bin/env python3
"""Run real CPU inference and tenant isolation checks in the built image.

docker run --rm --entrypoint /root/venv/bin/python \
  -v "$PWD/src/code/comfyui/v0.42.1/tests/smoke_runtime.py:/tmp/smoke.py:ro" \
  comfyui:v5.0.0-comfyui-v0.42.1 /tmp/smoke.py

The default isolates the production builtin compatibility plugins from the
community plugin catalog. Set FUNART_SMOKE_ALL_CUSTOM_NODES=1 for full startup.
For actual CUDA tensor execution, add --gpus all -e FUNART_SMOKE_DEVICE=gpu.
No model download, NAS mount, credentials or production resources needed.
"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


COMFYUI = Path(os.environ.get("COMFYUI_DIR", "/root/comfyui"))
BASE_URL = "http://127.0.0.1:18188"
PLUGINS = ["FunArt-ComfyUI-Multi-User", "funart_prompt_id_compat", "FunArt-ComfyUI-APIs", "FunArt-ComfyUI-v0421-Template-Assets"]


def request(path, tenant="default", payload=None, binary=False):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(BASE_URL + path, data=data, headers={
        "Content-Type": "application/json", "X-FunArt-Comfy-UserId": tenant,
    })
    with urllib.request.urlopen(req, timeout=15) as response:
        body = response.read()
    return body if binary else json.loads(body)


def infer(prompt, tenant):
    task_id = f"fc-smoke-{tenant}-{uuid.uuid4().hex}"
    accepted = request("/prompt", tenant, {
        "prompt": prompt, "prompt_id": task_id, "client_id": f"smoke-{tenant}",
        "extra_data": {"x-funart-comfy-userid": tenant},
    })
    assert accepted["prompt_id"] == task_id, accepted
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        history = request("/history/" + task_id, tenant)
        if task_id in history:
            item = history[task_id]
            assert item["status"]["status_str"] == "success", item
            assert item["status"]["completed"], item
            return item
        time.sleep(0.5)
    raise AssertionError(f"Inference timed out: {task_id}")


def output_file(workspace, tenant, item):
    output = item["outputs"]["2"]["images"][0]
    assert output["type"] == "output", output
    path = workspace / "output" / "users" / tenant / output["subfolder"] / output["filename"]
    assert path.is_file(), (tenant, path, output)
    return path


def main():
    device = os.environ.get("FUNART_SMOKE_DEVICE", "cpu")
    assert device in ("cpu", "gpu"), "FUNART_SMOKE_DEVICE must be cpu or gpu"
    assert (COMFYUI / ".funart-comfyui-version").read_text().strip() == "v0.42.1"
    assert Path("/root/built-in/version.txt").read_text().strip() == "5.0.0"
    manifest = json.loads((COMFYUI / "custom_nodes/FunArt-ComfyUI-v0421-Template-Assets/official_template_inputs.json").read_text())
    assert manifest["source"]["workflow_templates_version"] == "0.11.89"
    with tempfile.TemporaryDirectory(prefix="funart-v5-smoke-") as tmp:
        workspace = Path(tmp)
        for kind in ("input", "output", "temp", "user"):
            (workspace / kind).mkdir()
        # --gpu-only puts intermediate tensors (including EmptyImage) on CUDA.
        command = [sys.executable, "main.py", "--cpu" if device == "cpu" else "--gpu-only", "--listen", "127.0.0.1", "--port", "18188", "--offline", "--disable-auto-launch"]
        for kind in ("input", "output", "temp", "user"):
            command.extend([f"--{kind}-directory", str(workspace / kind)])
        all_plugins = os.environ.get("FUNART_SMOKE_ALL_CUSTOM_NODES") == "1"
        if not all_plugins:
            command.extend(["--disable-all-custom-nodes", "--whitelist-custom-nodes", *PLUGINS])
        environment = dict(os.environ, ENABLE_COMFYUI_MULTI_USER="true", PYTHONUNBUFFERED="1")
        log_path = workspace / "startup.log"
        with log_path.open("w") as log:
            process = subprocess.Popen(command, cwd=COMFYUI, env=environment, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 240
                while time.monotonic() < deadline:
                    assert process.poll() is None, f"ComfyUI exited: {process.returncode}"
                    try:
                        stats = request("/system_stats")
                        break
                    except (OSError, urllib.error.URLError):
                        time.sleep(1)
                else:
                    raise AssertionError("ComfyUI startup timed out")
                assert stats["system"]["comfyui_version"] == "0.42.1", stats
                if device == "gpu":
                    assert any(item["type"] == "cuda" for item in stats["devices"]), stats
                nodes = request("/object_info", "tenant-a")
                assert all(name in nodes for name in ("EmptyImage", "LoadImage", "SaveImage"))

                empty_image = {
                    "1": {"class_type": "EmptyImage", "inputs": {"width": 64, "height": 64, "batch_size": 1, "color": 16711680}},
                    "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": "cap_v5_smoke"}},
                }
                paths = {}
                for tenant in ("tenant-a", "tenant-b"):
                    paths[tenant] = output_file(workspace, tenant, infer(empty_image, tenant))
                assert paths["tenant-a"] != paths["tenant-b"]
                assert paths["tenant-a"].stat().st_ino != paths["tenant-b"].stat().st_ino

                for tenant in ("tenant-a", "tenant-b"):
                    for asset in manifest["assets"]:
                        query = urllib.parse.urlencode({"filename": asset["filename"], "type": "input"})
                        request("/view?" + query, tenant, binary=True)
                        local = workspace / "input" / "users" / tenant / asset["filename"]
                        assert hashlib.sha256(local.read_bytes()).hexdigest() == asset["sha256"]
                        assert not (workspace / "input" / asset["filename"]).exists()
                    prompt = {
                        "1": {"class_type": "LoadImage", "inputs": {"image": manifest["assets"][0]["filename"]}},
                        "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": "template_smoke"}},
                    }
                    output_file(workspace, tenant, infer(prompt, tenant))

                # A user's existing file must survive subsequent template loads.
                asset = manifest["assets"][0]
                tenant_input = workspace / "input/users/tenant-a" / asset["filename"]
                shutil.copyfile(paths["tenant-a"], tenant_input)
                before = tenant_input.read_bytes()
                query = urllib.parse.urlencode({"filename": asset["filename"], "type": "input"})
                request("/view?" + query, "tenant-a", binary=True)
                assert tenant_input.read_bytes() == before
                other_input = workspace / "input/users/tenant-b" / asset["filename"]
                assert hashlib.sha256(other_input.read_bytes()).hexdigest() == asset["sha256"]
                startup_warnings = [line for line in log_path.read_text(errors="replace").splitlines() if "IMPORT FAILED" in line or "Cannot import" in line]
                print(json.dumps({"result": "PASS", "comfyui": "0.42.1", "cap": "5.0.0", "device": device, "devices": stats["devices"], "all_custom_nodes": all_plugins, "startup_import_warnings": startup_warnings, "checks": ["startup/system_stats", "object_info", "non-UUID task IDs", f"EmptyImage->SaveImage {device} tensor inference", "two-tenant output/cache isolation", "official template preview and LoadImage", "tenant input no-clobber"]}))
            except BaseException:
                print(log_path.read_text(errors="replace")[-40000:], file=sys.stderr)
                raise
            finally:
                process.terminate()
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)


if __name__ == "__main__":
    main()
