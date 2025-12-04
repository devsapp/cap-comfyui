"""
CPU Gateway Service
处理 CPU 函数作为网关转发请求到 GPU 函数的逻辑
"""
import json

from flask import request, jsonify

import constants
from utils.logger import log
from .queue_handler import QueueHandler
from .gpu_forwarder import GpuForwarder


class CpuGatewayService:
    """CPU函数网关服务，负责转发请求到GPU函数"""
    
    def __init__(self):
        self.gpu_function_url = constants.GPU_FUNCTION_URL
        # 获取任务队列单例
        from services.gateway import get_task_queue
        self.task_queue = get_task_queue()
        
        # 初始化子处理器
        self.queue_handler = QueueHandler(self.task_queue)
        self.gpu_forwarder = GpuForwarder(self.gpu_function_url, self.task_queue)
    
    def _validate_prompt_request(self, prompt, error_format: str = "comfyui") -> tuple:
        """
        验证 prompt 请求
        
        Args:
            prompt: 要验证的 prompt 数据
            error_format: 错误响应格式 ('comfyui' 或 'serverless')
            
        Returns:
            tuple: (is_valid, error_response)
                   is_valid为True时error_response为None
                   is_valid为False时error_response为(jsonify(...), status_code)
        """
        if prompt is None:
            if error_format == "serverless":
                return False, (jsonify({
                    "type": "error",
                    "error_code": "invalid_request_error",
                    "error_message": "Request body must be valid JSON containing ComfyUI workflow definition"
                }), 400)
            else:
                return False, (jsonify({
                    "error": {
                        "type": "invalid_request_error",
                        "message": "Request body must be valid JSON"
                    }
                }), 400)
        
        if not isinstance(prompt, dict) or len(prompt) == 0:
            if error_format == "serverless":
                return False, (jsonify({
                    "type": "error",
                    "error_code": "invalid_request_error",
                    "error_message": "Prompt (workflow definition) cannot be empty. Please provide a valid ComfyUI workflow."
                }), 400)
            else:
                return False, (jsonify({
                    "error": {
                        "type": "invalid_request_error",
                        "message": "Prompt (workflow definition) cannot be empty. Please provide a valid ComfyUI workflow."
                    }
                }), 400)
        
        return True, None
    
    def handle_queue_get_request(self):
        """处理 GET /api/queue 请求 获取队列状态"""
        return self.queue_handler.handle_get_request()
    
    def handle_queue_post_request(self):
        """处理 POST /api/queue 请求 队列管理"""
        return self.queue_handler.handle_post_request()
    
    def handle_prompt_request_async(self):
        """
        处理 POST /api/prompt 请求（异步转发到GPU函数）
        
        Returns:
            tuple: (response_data, status_code)
        """
        # 获取请求数据
        request_data = request.get_json()
        if not request_data:
            return jsonify({
                "error": {
                    "type": "invalid_request_error",
                    "message": "Request body must be valid JSON"
                }
            }), 400
        
        # 提取 prompt 数据和 client_id
        prompt = request_data.get("prompt")
        client_id = request_data.get("client_id", "")
        
        if not prompt:
            return jsonify({
                "error": {
                    "type": "invalid_request_error", 
                    "message": "Missing 'prompt' in request body"
                }
            }), 400
        
        # 转发给GPU
        task_id, result = self.gpu_forwarder.forward_async(
            api_type="prompt",
            prompt=prompt,
            client_id=client_id,
            task_id_headers=["x-fc-async-task-id", "x-fc-request-id"],
            forward_by_name="CPU-Router-Async"
        )
        
        # 处理结果
        if task_id:
            # 成功：返回ComfyUI格式
            return jsonify({
                "prompt_id": task_id,
                "number": 1,
                "node_errors": {}
            })
        else:
            # 失败：result 是 (status_code, error_type, error_message)
            status_code, error_type, error_message = result
            return jsonify({
                "error": {
                    "type": error_type,
                    "message": error_message
                }
            }), status_code
    
    def handle_serverless_run_async(self):
        """
        处理 POST /api/serverless/run 请求（异步转发到GPU函数）
        
        Returns:
            tuple: (response_data, status_code)
        """
        # 获取请求数据 - /serverless/run 的请求体直接是 prompt
        prompt = request.get_json(force=True, silent=True)
        
        # 验证请求
        is_valid, error_response = self._validate_prompt_request(prompt, error_format="serverless")
        if not is_valid:
            return error_response

        client_id = ""
        
        # 转发给GPU
        task_id, result = self.gpu_forwarder.forward_async(
            api_type="serverless",
            prompt=prompt,
            client_id=client_id,
            task_id_headers=["x-fc-async-task-id", "x-fc-request-id"],
            forward_by_name="CPU-Router-Serverless-Async"
        )
        
        # 处理结果
        if task_id:
            # 成功：返回Serverless格式
            return jsonify({
                "task_id": task_id,
                "status": "pending"
            }), 202
        else:
            # 失败：result 是 (status_code, error_type, error_message)
            status_code, error_type, error_message = result
            return jsonify({
                "type": "error",
                "error_code": error_type,
                "error_message": error_message
            }), status_code
    
    def handle_serverless_run_sync(self):
        """
        处理 POST /api/serverless/run 请求（同步转发到GPU函数）
        
        与 handle_prompt_request_async 不同:
        - 不使用任务队列
        - 同步等待 GPU 函数返回结果
        - 直接返回结果给客户端
        
        Returns:
            response: GPU函数的响应
        """
        # 获取请求数据 - /serverless/run 的请求体直接是 prompt（ComfyUI 工作流定义）
        request_body = request.get_json(force=True, silent=True)
        
        # 验证请求
        is_valid, error_response = self._validate_prompt_request(request_body, error_format="serverless")
        if not is_valid:
            log("ERROR", f"[CPU Gateway Sync] Invalid request body")
            return error_response
        
        # 转发给GPU（同步）
        return self.gpu_forwarder.forward_sync(request_body)
