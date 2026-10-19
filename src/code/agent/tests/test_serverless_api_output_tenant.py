"""Tenant-scoped result downloads; no Flask request context or external services."""

import base64
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import MagicMock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.serverlessapi import serverless_api_service as service_module


HEADER = service_module.constants.HEADER_FUNART_COMFY_USERID
TENANT_BYTES = {"default": b"default-image", "tenant-a": b"tenant-a-image", "tenant-b": b"tenant-b-image"}
HISTORY = {"task": {"outputs": {"2": {"images": [{
    "filename": "same.png", "type": "output", "subfolder": "",
}]}}}}


def response(content, status=200):
    result = requests.Response()
    result.status_code = status
    result.url = "http://comfyui.invalid/view"
    result._content = content
    return result


class OutputTenantTests(unittest.TestCase):
    def setUp(self):
        self.service = service_module.ServerlessApiService.__new__(service_module.ServerlessApiService)
        self.service.endpoint = "http://comfyui.invalid"
        self.service.api_get_history = MagicMock(return_value=HISTORY)
        self.oss = MagicMock(region="cn-hangzhou", bucket_name="test-bucket")
        self.oss.ready.return_value = True
        self.oss.object_key.side_effect = lambda filename: "outputs/" + filename
        self.oss.sign.side_effect = lambda filename: "https://oss.invalid/" + filename
        self.service.get_oss_store = MagicMock(return_value=self.oss)

    def tenant_response(self, url, *, headers, params):
        self.assertEqual(url, "http://comfyui.invalid/view")
        self.assertEqual(params["filename"], "same.png")
        return response(TENANT_BYTES[headers[HEADER]])

    def test_base64_and_oss_download_the_requested_tenant(self):
        for tenant in TENANT_BYTES:
            with self.subTest(tenant=tenant), patch.object(service_module.requests, "get", side_effect=self.tenant_response) as get:
                result = self.service.get_history_result("task", output_base64=True, output_oss=True, user_id=tenant)
                output = result["data"]["results"][0]["output"]
                self.assertEqual(base64.b64decode(output["base64"]["content"]), TENANT_BYTES[tenant])
                self.assertEqual(self.oss.put.call_args.args[1], TENANT_BYTES[tenant])
                self.assertTrue(output["oss"]["url"].startswith("https://oss.invalid/"))
                self.assertEqual(get.call_args.kwargs["headers"], {HEADER: tenant})

    def test_oss_only_uses_the_same_tenant_header(self):
        with patch.object(service_module.requests, "get", side_effect=self.tenant_response):
            result = self.service.get_history_result("task", output_oss=True, user_id="tenant-b")
        output = result["data"]["results"][0]["output"]
        self.assertIsNone(output["base64"]["content"])
        self.assertEqual(self.oss.put.call_args.args[1], TENANT_BYTES["tenant-b"])

    def test_legacy_positional_calls_default_to_default_tenant(self):
        with patch.object(service_module.requests, "get", side_effect=self.tenant_response):
            self.assertEqual(self.service.api_view_image("same.png", "output", ""), TENANT_BYTES["default"])
            result = self.service.get_history_result("task", True, False)
        self.assertEqual(base64.b64decode(result["data"]["results"][0]["output"]["base64"]["content"]), TENANT_BYTES["default"])
        self.oss.put.assert_not_called()

    def test_concurrent_tenants_do_not_share_request_state(self):
        barrier = threading.Barrier(2)

        def concurrent_response(url, *, headers, params):
            barrier.wait(timeout=5)
            return self.tenant_response(url, headers=headers, params=params)

        with patch.object(service_module.requests, "get", side_effect=concurrent_response):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = {
                    tenant: executor.submit(self.service.get_history_result, "task", True, False, tenant)
                    for tenant in ("tenant-a", "tenant-b")
                }
                for tenant, future in futures.items():
                    output = future.result(timeout=5)["data"]["results"][0]["output"]
                    self.assertEqual(base64.b64decode(output["base64"]["content"]), TENANT_BYTES[tenant])

    def test_http_errors_are_not_encoded_or_uploaded_as_images(self):
        for status in (404, 500):
            with self.subTest(status=status), patch.object(service_module.requests, "get", return_value=response(b"error page", status)):
                with self.assertRaises(requests.HTTPError):
                    self.service.get_history_result("task", output_base64=True, output_oss=True, user_id="tenant-a")
                self.oss.put.assert_not_called()

    def test_metadata_only_does_not_download(self):
        with patch.object(service_module.requests, "get") as get:
            result = self.service.get_history_result("task", user_id="tenant-a")
        get.assert_not_called()
        self.assertEqual(result["data"]["results"][0]["output"]["raw"]["filename"], "same.png")

    def test_run_passes_extra_data_tenant_without_flask_request_context(self):
        self.service._wait_for_ready = MagicMock()
        self.service.parse_prompt = MagicMock(side_effect=lambda prompt, extra_data: prompt)
        self.service.api_prompt = MagicMock(return_value={"prompt_id": "task"})
        self.service.put_status_to_store = MagicMock()

        def websocket(client_id, on_message, **kwargs):
            ws = MagicMock()
            on_message(ws, json.dumps({"type": "status", "data": {"sid": "client"}}))
            return ws

        self.service.api_websocket = websocket
        for tenant in ("default", "tenant-a", "tenant-b"):
            body = {"prompt": {"2": {"class_type": "SaveImage", "inputs": {}}}}
            if tenant != "default":
                body["extra_data"] = {HEADER.lower(): tenant}
            with self.subTest(tenant=tenant), patch.object(service_module.requests, "get", side_effect=self.tenant_response), \
                    patch.object(service_module, "wake_input_cleaner"), patch.object(service_module, "TaskEventEmitter"):
                result = self.service.run(body, output_base64=True, task_id="task")
            output = result["data"]["results"][0]["output"]
            self.assertEqual(base64.b64decode(output["base64"]["content"]), TENANT_BYTES[tenant])


if __name__ == "__main__":
    unittest.main()
