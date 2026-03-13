"""
Interrupt Handler
处理 POST /api/interrupt 请求
"""
from flask import jsonify


class InterruptHandler:
    """处理 POST /api/interrupt"""

    def handle_post(self):
        """
        POST /api/interrupt 暂不支持：FC StopAsyncTask 会带来非预期体验，
        禁止客户端中止正在运行的任务，返回 403。
        """
        return jsonify({
            "error": {
                "type": "not_supported",
                "message": "Interrupting a running task is not supported.",
            }
        }), 403
