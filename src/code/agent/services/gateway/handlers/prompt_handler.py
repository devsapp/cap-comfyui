"""
Prompt Handler
处理 /prompt 请求逻辑
"""
from flask import request, jsonify

from utils.logger import log


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
        
        # 转发给GPU
        task_id, result = self.task_manager.forward_to_gpu_async(
            prompt=prompt,
            client_id=client_id
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
