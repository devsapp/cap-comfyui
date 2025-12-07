"""
Userdata Handler
处理 /userdata 请求逻辑
"""
from flask import jsonify

from utils.logger import log


class UserdataHandler:
    """处理 /userdata 请求"""
    
    def handle_post_request(self, file: str):
        """
        处理 POST /api/userdata/<path:file> 请求
        在生产模式下禁止保存工作流
        
        Args:
            file: 文件路径
            
        Returns:
            Flask response
        """
        log("INFO", f"Disable Saving Userdata in prod mode: {file}")
        return jsonify({
            "error": {
                "type": "forbidden",
                "message": "Saving workflow is disabled in prod mode"
            }
        }), 403
