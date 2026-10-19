#!/usr/bin/env python3
"""Exercise the real Agent HTTP -> ComfyUI WS/prompt/history/view path.

Run in the source image with Agent sources mounted read-only and its requirements
installed in the disposable container (the source image is not the Agent image):

  docker run --rm --entrypoint /bin/bash \
    -v "$PWD/src/code/agent:/tmp/agent:ro" \
    -v "$PWD/src/code/comfyui/v0.42.1/tests:/tmp/smoke-tests:ro" \
    -e AGENT_SMOKE_SOURCE_DIR=/tmp/agent \
    comfyui:v5.0.0-comfyui-v0.42.1 -c \
    '/root/venv/bin/pip install -r /tmp/agent/requirements.txt && \
     /root/venv/bin/python /tmp/smoke-tests/smoke_agent_api.py'

All network requests are real loopback requests. No requests monkeypatches,
credential injection, FC calls, OSS calls, model downloads, or NAS mounts.
Only the Agent service endpoint is configured to the isolated test backend.
The Agent uses GPU routing mode while ComfyUI uses CPU tensor execution by
default. Set FUNART_SMOKE_DEVICE=gpu and --gpus all for CUDA tensors.

This deliberately checks returned bytes against each tenant's output, not just
PNG magic: otherwise a default-tenant PNG could mask wrong-tenant retrieval.
This does not test snapshot restore or the CPU gateway/FC invocation chain.
"""

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


COMFYUI = Path(os.environ.get("COMFYUI_DIR", "/root/comfyui"))
BACKEND = "http://127.0.0.1:18188"
AGENT = "http://127.0.0.1:19000"
PLUGINS = ["FunArt-ComfyUI-Multi-User", "funart_prompt_id_compat",
           "FunArt-ComfyUI-APIs", "FunArt-ComfyUI-v0421-Template-Assets"]
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def http(url, payload=None, tenant=None, task_id=None, timeout=15):
    headers = {"Content-Type": "application/json"}
    if tenant is not None:
        headers["X-FunArt-Comfy-UserId"] = tenant
    if task_id is not None:
        headers["x-fc-async-task-id"] = task_id
    req = urllib.request.Request(
        url, data=None if payload is None else json.dumps(payload).encode(),
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def serve_agent():
    source = Path(os.environ["AGENT_SMOKE_SOURCE_DIR"])
    sys.path.insert(0, str(source))
    from flask import Flask
    from routes.serverless_api_routes import ServerlessApiRoutes

    app = Flask("real-agent-v5-smoke")
    routes = ServerlessApiRoutes()
    routes.service.endpoint = BACKEND
    routes.register(app)

    @app.get("/smoke-ready")
    def ready():
        return {"ready": True}

    app.run(host="127.0.0.1", port=19000, threaded=True, use_reloader=False)


def await_ready(process, url, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        assert process.poll() is None, f"Process exited with {process.returncode}: {url}"
        try:
            status, body = http(url)
            if status == 200:
                return json.loads(body)
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.5)
    raise AssertionError(f"Startup timed out: {url}")


def infer_case(workspace, tenant, color):
    task_id = f"fc-agent-smoke-{tenant}-{uuid.uuid4().hex}"
    payload = {
        "prompt": {
            "1": {"class_type": "EmptyImage", "inputs": {
                "width": 64, "height": 64, "batch_size": 1, "color": color}},
            "2": {"class_type": "SaveImage", "inputs": {
                "images": ["1", 0], "filename_prefix": "same_tenant_filename"}},
        },
        "extra_data": {"x-funart-comfy-userid": tenant},
    }
    code, body = http(AGENT + "/api/serverless/run?output_base64=true",
                      payload, tenant, task_id, timeout=180)
    case = {"tenant": tenant, "task_id": task_id, "http_status": code}
    if code != 200:
        return dict(case, passed=False, error=body.decode(errors="replace")[:4000])
    result = json.loads(body)
    assert result["type"] == "serverless_api", result
    assert result["data"]["prompt_id"] == task_id, result
    results = result["data"]["results"]
    assert len(results) == 1, result
    output = results[0]["output"]
    raw = output["raw"]
    directory = workspace / "output"
    if tenant != "default":
        directory = directory / "users" / tenant
    generated = (directory / raw["subfolder"] / raw["filename"]).read_bytes()
    assert generated.startswith(PNG_MAGIC), "Actual inference did not produce PNG"
    returned = base64.b64decode(output["base64"]["content"], validate=True)
    query = urllib.parse.urlencode({key: raw[key] for key in ("filename", "type", "subfolder")})
    view_status, view_bytes = http(BACKEND + "/view?" + query, tenant=tenant)
    no_header_status, no_header_bytes = http(BACKEND + "/view?" + query)
    assert view_status == 200 and view_bytes == generated, "Tenant /view failed"
    history_code, history_body = http(BACKEND + "/api/history/" + task_id, tenant=tenant)
    assert history_code == 200, history_body
    history = json.loads(history_body)[task_id]
    assert history["status"]["completed"] and history["status"]["status_str"] == "success", history
    status_code, events_body = http(AGENT + "/api/serverless/status?task_id=" + task_id)
    assert status_code == 200, events_body
    events = json.loads(events_body)
    message_types = sorted({event.get("type", "") for event in events if isinstance(event, dict)})
    return dict(case, passed=returned == generated,
                response_is_png=returned.startswith(PNG_MAGIC),
                response_matches_tenant_output=returned == generated,
                returned_sha256=hashlib.sha256(returned).hexdigest(),
                tenant_output_sha256=hashlib.sha256(generated).hexdigest(),
                response_matches_headerless_view=returned == no_header_bytes,
                headerless_view_status=no_header_status,
                generated_filename=raw["filename"], websocket_event_types=message_types)


def main():
    source = Path(os.environ.get("AGENT_SMOKE_SOURCE_DIR", Path(__file__).resolve().parents[3] / "agent"))
    assert (source / "routes/serverless_api_routes.py").is_file(), source
    device = os.environ.get("FUNART_SMOKE_DEVICE", "cpu")
    assert device in ("cpu", "gpu")
    with tempfile.TemporaryDirectory(prefix="funart-agent-v5-smoke-") as tmp:
        workspace = Path(tmp)
        for name in ("input", "output", "temp", "user", "work"):
            (workspace / name).mkdir()
        env = dict(os.environ, ENABLE_COMFYUI_MULTI_USER="true", PYTHONUNBUFFERED="1",
                   COMFYUI_MODE="gpu", MODEL_ASSET_DIR=tmp, WORK_DIR=str(workspace / "work"),
                   INPUT_DIR=str(workspace / "input"), MNT_INPUT_DIR=str(workspace / "input"),
                   COMFYUI_DIR=str(COMFYUI), AGENT_SMOKE_SOURCE_DIR=str(source),
                   ALIBABA_CLOUD_ACCESS_KEY_ID="", ALIBABA_CLOUD_ACCESS_KEY_SECRET="",
                   ALIBABA_CLOUD_SECURITY_TOKEN="", OSS_BUCKET_DOMAIN="", NO_PROXY="127.0.0.1,localhost")
        env.pop("AUTO_LAUNCH_SNAPSHOT_NAME", None)
        command = [sys.executable, "main.py", "--cpu" if device == "cpu" else "--gpu-only",
                   "--listen", "127.0.0.1", "--port", "18188", "--offline", "--disable-auto-launch",
                   "--disable-all-custom-nodes", "--whitelist-custom-nodes", *PLUGINS]
        for name in ("input", "output", "temp", "user"):
            command.extend([f"--{name}-directory", str(workspace / name)])
        processes = []
        log_paths = [workspace / "comfyui.log", workspace / "agent.log"]
        with log_paths[0].open("w") as comfy_log, log_paths[1].open("w") as agent_log:
            try:
                backend = subprocess.Popen(command, cwd=COMFYUI, env=env, stdout=comfy_log, stderr=subprocess.STDOUT)
                processes.append(backend)
                stats = await_ready(backend, BACKEND + "/system_stats", 240)
                assert stats["system"]["comfyui_version"] == "0.42.1", stats
                agent = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve-agent"],
                                         cwd=source, env=env, stdout=agent_log, stderr=subprocess.STDOUT)
                processes.append(agent)
                await_ready(agent, AGENT + "/smoke-ready", 30)
                cases = [infer_case(workspace, tenant, color) for tenant, color in
                         [("default", 16711680), ("tenant-a", 65280), ("tenant-b", 255)]]
                passed = all(case["passed"] for case in cases)
                print(json.dumps({"result": "PASS" if passed else "FAIL", "device": device,
                                  "checks": "real Agent HTTP -> WS/prompt/history/view; tenant-exact base64 output",
                                  "cases": cases}), flush=True)
                assert passed, "Agent returned bytes do not match tenant inference output; see case diagnostics"
            except BaseException:
                for path in log_paths:
                    print(f"--- {path.name} ---\n{path.read_text(errors='replace')[-40000:]}", file=sys.stderr)
                raise
            finally:
                for process in reversed(processes):
                    process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)


if __name__ == "__main__":
    if "--serve-agent" in sys.argv:
        serve_agent()
    else:
        main()
