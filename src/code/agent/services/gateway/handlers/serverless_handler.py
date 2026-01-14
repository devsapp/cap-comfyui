"""
Serverless Handler
处理 /serverless/run 请求逻辑
"""
import traceback
from flask import request, jsonify

from utils.logger import log
from exceptions.exceptions import TaskError, InternalError

class ServerlessHandler:
    """处理 /serverless/run 请求"""
    
    def __init__(self, task_manager):
        self.task_manager = task_manager
    
    def handle_post_request(self):
        """
        处理 POST /api/serverless/run 请求
        
        支持两种模式：
        - 同步模式（默认）：等待GPU处理完成，直接返回结果
        - 异步模式：立即返回任务ID，前端通过任务ID轮询获取结果
        
        通过请求头 X-Fc-Invocation-Type 控制：
        - 不传或传其他值：同步模式
        - X-Fc-Invocation-Type: Async：异步模式
        
        Returns:
            tuple: (response_data, status_code)
        """
        # 获取请求数据
        body = request.get_json(force=True, silent=True)
        client_id = ""
        
        # 检查是否为异步调用
        invocation_type = request.headers.get('X-Fc-Invocation-Type', '').lower()
        is_async = (invocation_type == 'async')
        
        try:
            if is_async:
                # 异步模式：立即返回任务ID
                log("INFO", f"[ServerlessHandler] Processing async request")
                task_id, result = self.task_manager.forward_to_gpu_async(
                    request_body=body,
                    client_id=client_id
                )
                
                # 成功：返回Serverless格式
                return jsonify({
                    "task_id": task_id,
                    "status": "pending"
                }), 202
            else:
                # 同步模式：等待GPU处理完成
                log("INFO", f"[ServerlessHandler] Processing sync request")
                response_data, status_code = self.task_manager.forward_to_gpu_sync(
                    request_body=body
                )
                return jsonify(response_data), status_code
                
        except TaskError as e:
            log("ERROR", f"[ServerlessHandler] Task error: {e.message}")
            return jsonify(e.to_dict()), e.code
        
        except InternalError as e:
            log("ERROR", f"[ServerlessHandler] Internal error: {e.message}")
            return jsonify({
                "type": "error",
                "error_code": "internal_error",
                "error_message": e.message
            }), e.code
            
        except Exception as e:
            log("ERROR", f"[ServerlessHandler] Unexpected error: {str(e)}\n{traceback.format_exc()}")
            return jsonify({
                "type": "error",
                "error_code": "internal_error",
                "error_message": str(e)
            }), 500
