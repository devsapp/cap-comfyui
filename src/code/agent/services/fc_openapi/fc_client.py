"""
FC OpenAPI 客户端
用于在 CPU 侧调用函数计算 OpenAPI，操作 GPU 上的异步任务。
使用实例 RAM 角色凭证：优先从请求头（FC 注入）获取，否则从环境变量获取。
"""
from flask import request

from alibabacloud_tea_openapi.client import Client as OpenApiClient
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_tea_util import models as util_models

import constants
from utils.logger import log


def _get_credentials():
    """
    获取阿里云凭证（与 ServerlessApiService.get_credentials 一致）。
    优先从请求头获取（FC 实例 RAM 角色注入），否则从环境变量获取。
    Returns:
        tuple: (access_key_id, access_key_secret, security_token)
    """
    ak = ""
    sk = ""
    sts = ""
    try:
        ak = request.headers.get(constants.HEADER_KEY_ACCESS_KEY_ID, "")
        sk = request.headers.get(constants.HEADER_KEY_ACCESS_KEY_SECRET, "")
        sts = request.headers.get(constants.HEADER_KEY_SECURITY_TOKEN, "")
    except Exception as e:
        log("WARNING", f"get credentials from header failed: {e}")
    if not ak or not sk:
        ak = getattr(constants, "ALIBABA_CLOUD_ACCESS_KEY_ID", "") or ""
        sk = getattr(constants, "ALIBABA_CLOUD_ACCESS_KEY_SECRET", "") or ""
        sts = getattr(constants, "ALIBABA_CLOUD_SECURITY_TOKEN", "") or ""
    return ak, sk, sts


def _create_client(ak: str, sk: str, sts: str, endpoint: str) -> OpenApiClient:
    """
    构造 FC OpenApiClient，供各 API 调用方复用，避免重复构建 Config。
    """
    config = open_api_models.Config(
        access_key_id=ak,
        access_key_secret=sk,
        security_token=sts or None,
    )
    config.endpoint = endpoint
    return OpenApiClient(config)


def stop_async_task(task_id: str) -> bool:
    """
    调用 FC OpenAPI StopAsyncTask 停止指定异步任务（带签名，使用实例 RAM 角色凭证）。

    Args:
        task_id: 异步任务 ID（与我们的 task_id/prompt_id 一致）。

    Returns:
        bool: 请求成功且为 2xx 返回 True，否则 False。
    """
    account_id = getattr(constants, "FC_ACCOUNT_ID", "") or ""
    region = getattr(constants, "FC_REGION", "cn-hangzhou") or "cn-hangzhou"
    cpu_function_name = getattr(constants, "FC_FUNCTION_NAME", "") or ""

    if not account_id or not cpu_function_name:
        return False

    ak, sk, sts = _get_credentials()
    if not ak or not sk:
        log("WARNING", "StopAsyncTask: no credentials (header or env)")
        return False

    gpu_function_name = cpu_function_name.replace("-gw", "")
    endpoint = f"{account_id}.{region}.fc.aliyuncs.com"

    try:
        client = _create_client(ak, sk, sts, endpoint)

        params = open_api_models.Params(
            action="StopAsyncTask",
            version="2023-03-30",
            protocol="HTTPS",
            method="PUT",
            auth_type="AK",
            style="FC",
            pathname=f"/2023-03-30/functions/{gpu_function_name}/async-tasks/{task_id}/stop",
            req_body_type="json",
            body_type="json",
        )
        req = open_api_models.OpenApiRequest(query={"qualifier": "LATEST"})
        runtime = util_models.RuntimeOptions(read_timeout=5000, connect_timeout=5000)

        resp = client.call_api(params, req, runtime)
        status_code = resp.get("statusCode") or 0
        if status_code >= 200 and status_code < 300:
            return True
        log("WARNING", f"StopAsyncTask failed: task_id={task_id}, status={status_code}, body={resp.get('body', '')[:200]}")
        return False
    except Exception as e:
        log("WARNING", f"StopAsyncTask request error: task_id={task_id}, error={e}")
        return False
