"""
Prompt Handler
处理 /prompt 请求逻辑
"""
import traceback
from flask import request, jsonify, g

import constants
from utils.logger import log
from exceptions.exceptions import TaskError, InternalError
from services.metrics.task_event_emitter import TaskEventEmitter


class PromptHandler:
    """处理 /prompt 请求"""
    
    def __init__(self, task_manager):
        self.task_manager = task_manager
    
    def handle_post_request(self):
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
        
        
        # 注入 user_id 到 extra_data
        user_id = getattr(g, 'user_id', 'default')
        if 'extra_data' not in request_data:
            request_data['extra_data'] = {}
        request_data['extra_data'][constants.HEADER_FUNART_COMFY_USERID.lower()] = user_id

        # 提取 task_id（用于事件追踪，同 ServerlessHandler 的模式）
        task_id = (request.headers.get(constants.HEADER_FC_ASYNC_TASK_ID) or 
                   request.headers.get(constants.HEADER_FC_REQUEST_ID) or 
                   'unknown')

        # 入口哨兵
        TaskEventEmitter.emit_submitted(task_id, "Async")

        try:
            # 转发给GPU
            task_id, result = self.task_manager.forward_to_gpu_async(
                request_body=request_data,
                client_id=client_id
            )
            
            # 成功：返回ComfyUI格式（completed 由 GPU 侧闭环）
            return jsonify({
                "prompt_id": task_id,
                "number": 1,
                "node_errors": {}
            })
            
        except (TaskError, InternalError) as e:
            # 统一兜底：CPU 侧提交失败
            log("ERROR", f"[PromptHandler] Task error: {e.message}")
            TaskEventEmitter.emit_completed(task_id, "failed", error_type="submit_failed", error_message=e.message)
            return jsonify({
                "error": {
                    "type": e.error_code if hasattr(e, 'error_code') else "internal_error",
                    "message": e.message
                }
            }), e.code
            
        except Exception as e:
            log("ERROR", f"[PromptHandler] Unexpected error: {str(e)}\n{traceback.format_exc()}")
            TaskEventEmitter.emit_completed(task_id, "failed", error_type="submit_failed", error_message=str(e))
            return jsonify({
                "error": {
                    "type": "internal_error",
                    "message": str(e)
                }
            }), 500
