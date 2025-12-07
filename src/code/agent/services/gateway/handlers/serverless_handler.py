"""
Serverless Handler
处理 /serverless/run 请求逻辑
"""
from flask import request, jsonify

from utils.logger import log


class ServerlessHandler:
    """处理 /serverless/run 请求"""
    
    def __init__(self, task_manager):
        self.task_manager = task_manager
    
    def handle_post_request(self):
        """
        处理 POST /api/serverless/run 请求（异步转发到GPU函数）
        
        Returns:
            tuple: (response_data, status_code)
        """
        # 获取请求数据 - /serverless/run 的请求体直接是 prompt
        prompt = request.get_json(force=True, silent=True)
        
        # 验证请求
        if prompt is None:
            return jsonify({
                "type": "error",
                "error_code": "invalid_request_error",
                "error_message": "Request body must be valid JSON containing ComfyUI workflow definition"
            }), 400
        
        if not isinstance(prompt, dict) or len(prompt) == 0:
            return jsonify({
                "type": "error",
                "error_code": "invalid_request_error",
                "error_message": "Prompt (workflow definition) cannot be empty. Please provide a valid ComfyUI workflow."
            }), 400

        client_id = ""
        
        # 转发给GPU
        task_id, result = self.task_manager.forward_to_gpu_async(
            prompt=prompt,
            client_id=client_id
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
