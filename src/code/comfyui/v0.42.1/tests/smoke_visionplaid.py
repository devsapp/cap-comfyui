#!/usr/bin/env python3
"""Verify the production VisionPlaid builtin imports and registers on CUDA.

docker run --rm --gpus all --network none \
  --entrypoint /root/venv/bin/python \
  -v "$PWD/src/code/comfyui/v0.42.1/tests/smoke_visionplaid.py:/tmp/probe.py:ro" \
  comfyui:v5.0.0-comfyui-v0.42.1 /tmp/probe.py

Uses existing image dependencies, a temporary workspace and loopback HTTP only.
No model downloads, external APIs or inference-model execution. This is an
import/registration contract check, not a VisionPlaid numerical correctness test.
"""

from importlib.metadata import version
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


COMFYUI = Path(os.environ.get("COMFYUI_DIR", "/root/comfyui"))
COMFY_PYTHON = os.environ.get("COMFY_PYTHON", "/root/venv/bin/python")
BASE_URL = "http://127.0.0.1:18189"
PLUGINS = ["FunArt-ComfyUI-Multi-User", "funart_prompt_id_compat",
           "FunArt-ComfyUI-APIs", "FunArt-ComfyUI-v0421-Template-Assets",
           "Comfy-VisionPlaid"]
EXPECTED_NODES = ["DiffusionBoost", "LoadDiffusionModel", "ParallelKSampler",
                  "ParallelKSamplerAdvanced", "ParallelSamplerCustomAdvanced"]


def request(path):
    with urllib.request.urlopen(BASE_URL + path, timeout=15) as response:
        return json.loads(response.read())


def main():
    assert version("vision-plaid") == "1.1.0"
    assert (COMFYUI / ".funart-comfyui-version").read_text().strip() == "v0.42.1"
    for root in (COMFYUI / "custom_nodes", Path("/root/built-in/custom_nodes")):
        assert (root / "Comfy-VisionPlaid/__init__.py").is_file(), root
    with tempfile.TemporaryDirectory(prefix="funart-v5-visionplaid-") as tmp:
        workspace = Path(tmp)
        command = [COMFY_PYTHON, "main.py", "--gpu-only", "--listen", "127.0.0.1",
                   "--port", "18189", "--offline", "--disable-auto-launch",
                   "--disable-all-custom-nodes", "--whitelist-custom-nodes", *PLUGINS]
        for name in ("input", "output", "temp", "user"):
            (workspace / name).mkdir()
            command.extend([f"--{name}-directory", str(workspace / name)])
        log_path = workspace / "startup.log"
        env = dict(os.environ, ENABLE_COMFYUI_MULTI_USER="true", PYTHONUNBUFFERED="1",
                   HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", NO_PROXY="127.0.0.1,localhost")
        with log_path.open("w") as log:
            process = subprocess.Popen(command, cwd=COMFYUI, env=env,
                                       stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 240
                while time.monotonic() < deadline:
                    assert process.poll() is None, f"ComfyUI exited: {process.returncode}"
                    try:
                        stats = request("/system_stats")
                        break
                    except (OSError, urllib.error.URLError):
                        time.sleep(0.5)
                else:
                    raise AssertionError("ComfyUI startup timed out")
                assert stats["system"]["comfyui_version"] == "0.42.1", stats
                assert any(device["type"] == "cuda" for device in stats["devices"]), stats
                registered = {}
                for name in EXPECTED_NODES:
                    data = request("/object_info/" + name)
                    assert name in data, f"Missing VisionPlaid node: {name}"
                    info = data[name]
                    assert info["python_module"] == "custom_nodes.Comfy-VisionPlaid", info
                    assert isinstance(info["input"], dict), info
                    registered[name] = {"python_module": info["python_module"],
                                        "display_name": info.get("display_name"),
                                        "input_groups": sorted(info["input"])}
                warnings = [line for line in log_path.read_text(errors="replace").splitlines()
                            if "IMPORT FAILED" in line or "Cannot import" in line]
                assert not warnings, warnings
                print(json.dumps({"result": "PASS", "comfyui": "0.42.1",
                                  "vision_plaid": version("vision-plaid"),
                                  "devices": stats["devices"], "registered_nodes": registered,
                                  "startup_import_warnings": warnings,
                                  "boundary": "GPU import/registration only; no model inference or external API"}))
            except BaseException:
                print(log_path.read_text(errors="replace")[-40000:], file=sys.stderr)
                raise
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)


if __name__ == "__main__":
    main()
