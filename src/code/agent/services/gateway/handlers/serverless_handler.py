"""
Serverless Handler
处理 /serverless/run 请求逻辑
"""
import traceback
import requests
from flask import request, jsonify

import constants
from utils.logger import log


class ServerlessHandler:
    """处理 /serverless/run 请求"""
    
    def __init__(self):
        pass
    
    def handle_post_request(self):
        """
        处理 POST /api/serverless/run 请求
        
        转发到 GPU，支持异步/同步两种模式：
        - 异步模式：透传 X-Fc-Invocation-Type: Async，GPU 立即返回 202
        - 同步模式：等待 GPU 完成任务并返回结果
        
        通过请求头 X-Fc-Invocation-Type 控制：
        - 不传或传其他值：同步模式
        - X-Fc-Invocation-Type: Async：异步模式
        
        Returns:
            tuple: (response_data, status_code)
        """
        # 获取请求数据
        body = request.get_json(force=True, silent=True)
        
        # 检查 GPU URL 配置
        if not constants.GPU_FUNCTION_URL:
            log("ERROR", "[ServerlessHandler] GPU_FUNCTION_URL not configured")
            return jsonify({
                "type": "error",
                "error_code": constants.ERROR_CODE.CONFIGURATION_ERROR.value,
                "error_message": "GPU_FUNCTION_URL not configured for CPU mode"
            }), 500
        
        # 构造 GPU URL
        gpu_url = f"{constants.GPU_FUNCTION_URL.rstrip('/')}/api/serverless/run"
        
        # 提取 task_id（用于日志和 headers）
        task_id = (request.headers.get(constants.HEADER_FC_ASYNC_TASK_ID) or 
                   request.headers.get(constants.HEADER_FC_REQUEST_ID) or 
                   'unknown')
        
        # 检测是否为异步调用
        invocation_type = request.headers.get(constants.HEADER_FC_INVOCATION_TYPE, '').lower()
        is_async = (invocation_type == 'async')
        
        # 准备 headers
        forward_headers = {
            'x-fc-request-id': task_id,
            'x-fc-trace-id': task_id,
        }
        
        # 如果是异步调用，需要设置 x-fc-invocation-type 告诉 GPU 函数进行异步处理
        if is_async:
            forward_headers['x-fc-invocation-type'] = 'Async'
        
        # 复制客户端的其他 headers
        # 跳过我们已经设置的 headers，避免被覆盖
        # 透传host会导致请求在cpu函数上循环调用，透传content-length会导致下游读取payload截断
        skip_headers = {'x-fc-request-id', 'x-fc-trace-id', 'x-fc-invocation-type', 'host', 'content-length'}
        for k, v in request.headers.items():
            if k.lower() not in skip_headers:
                forward_headers[k] = v
        
        try:
            # 根据调用类型设置超时时间
            timeout = 30 if is_async else 600
            
            log("INFO", f"[ServerlessHandler][{task_id}] Forwarding {'async' if is_async else 'sync'} request")
            
            resp = requests.post(
                gpu_url,
                json=body,
                headers=forward_headers,
                params=request.args,
                timeout=timeout
            )
            
            # 原样返回 GPU 的响应
            try:
                return resp.json(), resp.status_code
            except Exception:
                # GPU 返回非 JSON（如空响应体）
                return {}, resp.status_code
        
        except Exception as e:
            log("ERROR", f"[ServerlessHandler][{task_id}] Internal error: {e}\n{traceback.format_exc()}")
            return jsonify({
                "type": "error",
                "error_code": constants.ERROR_CODE.INTERNAL_ERROR.value,
                "error_message": str(e)
            }), 500
