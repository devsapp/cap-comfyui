"""
FC OpenAPI 客户端
用于在 CPU 侧调用函数计算 OpenAPI，操作 GPU 上的异步任务。
使用实例 RAM 角色凭证：优先从请求头（FC 注入）获取，否则从环境变量获取。
"""
from typing import Optional

from flask import request

from alibabacloud_tea_openapi.client import Client as OpenApiClient
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_tea_util import models as util_models

import constants
from utils.logger import log

ALLOWED_STATUSES = frozenset({
    "Enqueued", "Dequeued", "Running", "Succeeded", "Failed", "Expired", "Retrying",
})


class FCClientException(Exception):
    """
    FC OpenAPI 调用异常。
    status_code = 0  : 配置/凭证缺失或网络/SDK 异常（非 HTTP 层错误）
    status_code != 0 : FC 返回的非 2xx HTTP 状态码
    """
    def __init__(self, message: str, *, status_code: int = 0, body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


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


def _get_gpu_function_name() -> str:
    gpu_function_name = getattr(constants, "GPU_FUNCTION_NAME", "") or ""
    if gpu_function_name:
        return gpu_function_name
    # fallback：从 CPU 函数名去除 -gw- 推导，如 foo-gw-prod → foo-prod
    cpu_function_name = getattr(constants, "FC_FUNCTION_NAME", "") or ""
    return cpu_function_name.replace("-gw-", "-")


def _get_endpoint() -> str:
    account_id = getattr(constants, "FC_ACCOUNT_ID", "") or ""
    region = getattr(constants, "FC_REGION", "cn-hangzhou") or "cn-hangzhou"
    return f"{account_id}.{region}.fc.aliyuncs.com"


def _create_client(ak: str, sk: str, sts: str, endpoint: str) -> OpenApiClient:
    config = open_api_models.Config(
        access_key_id=ak,
        access_key_secret=sk,
        security_token=sts or None,
    )
    config.endpoint = endpoint
    return OpenApiClient(config)


def _build_client():
    """构建 client 并返回 (client, gpu_function_name)，配置/凭证缺失时 raise FCClientException。"""
    account_id = getattr(constants, "FC_ACCOUNT_ID", "") or ""
    cpu_function_name = getattr(constants, "FC_FUNCTION_NAME", "") or ""
    if not account_id or not cpu_function_name:
        msg = f"FC OpenAPI: missing config (FC_ACCOUNT_ID set={bool(account_id)}, FC_FUNCTION_NAME set={bool(cpu_function_name)})"
        log("WARNING", msg)
        raise FCClientException(msg)

    ak, sk, sts = _get_credentials()
    if not ak or not sk:
        msg = "FC OpenAPI: no credentials (header or env)"
        log("WARNING", msg)
        raise FCClientException(msg)

    client = _create_client(ak, sk, sts, _get_endpoint())
    return client, _get_gpu_function_name()


def stop_async_task(task_id: str) -> bool:
    """
    调用 FC OpenAPI StopAsyncTask 停止指定异步任务。

    Returns:
        bool: 请求成功且为 2xx 返回 True，否则 False。
    """
    try:
        client, gpu_function_name = _build_client()
    except FCClientException:
        return False

    try:
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
        if 200 <= status_code < 300:
            return True
        log("WARNING", f"StopAsyncTask non-2xx: task_id={task_id}, status={status_code}, body={str(resp.get('body', ''))[:200]}")
        return False
    except Exception as e:
        log("WARNING", f"StopAsyncTask request error: task_id={task_id}, error={e}")
        return False


def get_async_task(task_id: str) -> dict:
    """
    调用 FC OpenAPI GetAsyncTask 查询单个异步任务。

    Returns:
        dict: {"statusCode": int, "body": {...}}（仅 2xx）
    Raises:
        FCClientException: 配置/凭证缺失、FC 返回非 2xx、或 SDK 异常。
    """
    client, gpu_function_name = _build_client()

    try:
        params = open_api_models.Params(
            action="GetAsyncTask",
            version="2023-03-30",
            protocol="HTTPS",
            method="GET",
            auth_type="AK",
            style="FC",
            pathname=f"/2023-03-30/functions/{gpu_function_name}/async-tasks/{task_id}",
            req_body_type="json",
            body_type="json",
        )
        req = open_api_models.OpenApiRequest(query={"qualifier": "LATEST"})
        runtime = util_models.RuntimeOptions(read_timeout=10000, connect_timeout=5000)

        resp = client.call_api(params, req, runtime)
        status_code = resp.get("statusCode") or 0
        if not (200 <= status_code < 300):
            body_snippet = str(resp.get("body", ""))[:200]
            log("WARNING", f"GetAsyncTask non-2xx: task_id={task_id}, status={status_code}, body={body_snippet}")
            raise FCClientException(
                f"GetAsyncTask failed with HTTP {status_code}",
                status_code=status_code,
                body=body_snippet,
            )
        return resp
    except FCClientException:
        raise
    except Exception as e:
        log("WARNING", f"GetAsyncTask error: task_id={task_id}, error={e}")
        raise FCClientException(f"GetAsyncTask error: {e}") from e


def list_async_tasks(
    status: Optional[str] = None,
    started_time_begin: Optional[int] = None,
    started_time_end: Optional[int] = None,
    limit: Optional[int] = None,
    next_token: Optional[str] = None,
    sort_order_by_time: Optional[str] = None,
    prefix: Optional[str] = None,
) -> dict:
    """
    调用 FC OpenAPI ListAsyncTasks 查询异步任务列表。

    Returns:
        dict: {"statusCode": int, "body": {"tasks": [...], "nextToken": ...}}（仅 2xx）
    Raises:
        FCClientException: 配置/凭证缺失、FC 返回非 2xx、或 SDK 异常。
    """
    client, gpu_function_name = _build_client()

    query = {"qualifier": "LATEST"}
    if status is not None:
        query["status"] = str(status)
    if started_time_begin is not None:
        query["startedTimeBegin"] = str(started_time_begin)
    if started_time_end is not None:
        query["startedTimeEnd"] = str(started_time_end)
    if limit is not None:
        query["limit"] = str(limit)
    if next_token is not None:
        query["nextToken"] = str(next_token)
    if sort_order_by_time is not None:
        query["sortOrderByTime"] = str(sort_order_by_time)
    if prefix is not None:
        query["prefix"] = str(prefix)

    try:
        params = open_api_models.Params(
            action="ListAsyncTasks",
            version="2023-03-30",
            protocol="HTTPS",
            method="GET",
            auth_type="AK",
            style="FC",
            pathname=f"/2023-03-30/functions/{gpu_function_name}/async-tasks",
            req_body_type="json",
            body_type="json",
        )
        req = open_api_models.OpenApiRequest(query=query)
        runtime = util_models.RuntimeOptions(read_timeout=10000, connect_timeout=5000)

        resp = client.call_api(params, req, runtime)
        status_code = resp.get("statusCode") or 0
        if not (200 <= status_code < 300):
            body_snippet = str(resp.get("body", ""))[:200]
            log("WARNING", f"ListAsyncTasks non-2xx: status={status_code}, body={body_snippet}")
            raise FCClientException(
                f"ListAsyncTasks failed with HTTP {status_code}",
                status_code=status_code,
                body=body_snippet,
            )
        return resp
    except FCClientException:
        raise
    except Exception as e:
        log("WARNING", f"ListAsyncTasks error: error={e}")
        raise FCClientException(f"ListAsyncTasks error: {e}") from e
