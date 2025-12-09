"""
代理工具模块
提供将请求转发到 ComfyUI 后端的通用功能
"""
from flask import request, Response
import requests

import constants
from services.management_service import ManagementService, BackendStatus
from utils.logger import log
from utils.error_handler import ErrorResponse


def proxy_to_comfyui(uri=None, check_status=True, timeout=30, log_prefix="Proxy", service=None):
    """
    将 HTTP 请求代理转发到 ComfyUI 后端
    
    Args:
        uri: 目标 URI，如果不提供则使用 request.environ.get('RAW_URI', request.path)
        check_status: 是否检查后端服务状态，默认为 True
        timeout: 请求超时时间（秒），默认为 30
        log_prefix: 日志前缀，默认为 "Proxy"
        service: ManagementService 实例，如果不提供则创建新实例
    
    Returns:
        Response: Flask Response 对象，包含转发后的响应
        ErrorResponse: 如果检查失败或转发失败，返回错误响应
    """
    # 检查后端服务状态
    if check_status:
        if service is None:
            service = ManagementService()
        backend_status = service.status
        if backend_status not in (BackendStatus.RUNNING, BackendStatus.SAVING):
            return ErrorResponse.create(
                error_type="service_not_running",
                message="Please start your comfyui/sd service first",
                status_code=503
            )

    # issue: https://teambition.alibaba-inc.com/task/67c96194e6efb1c42a7ee904
    if uri is None:
        uri = request.environ.get('RAW_URI', request.path)
    target_url = f"http://{constants.APP_HOST}{uri}"
    # print(f"Forwarding http request to path: {target_url}")

    resp = requests.request(
        method=request.method,
        url=target_url,
        headers=dict(request.headers),
        params=request.args,
        data=request.get_data(),
        cookies=request.cookies,
        allow_redirects=False,
        verify=False  # 如果需要验证SSL证书，将其设置为True
    )

    # issue: 实际内容被requests库解码，若保留content-encoding，可能会导致客户端试图重复解码，导致浏览器渲染SD页面失败
    excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
    response_headers = {}
    for name, value in resp.headers.items():
        if name.lower() not in excluded_headers:
            response_headers[name] = value

    return Response(
        response=resp.content,
        status=resp.status_code,
        headers=response_headers
    )

