"""
Queue Handler
处理队列相关的请求逻辑
"""
from flask import jsonify, Response, request

from utils.logger import log


class QueueHandler:
    """处理队列相关的请求"""
    
    def __init__(self, task_manager):
        self.task_manager = task_manager
    
    def handle_get_request(self):
        """
        处理 GET /api/queue 请求 获取队列状态
        
        Returns:
            Flask response
        """
        from services.gateway.task.task import TaskStatus
        
        try:
            # 获取任务列表
            all_tasks = self.task_manager.get_all_tasks()
        except Exception as e:
            log("ERROR", f"Error fetching tasks for queue request: {e}")
            return jsonify({
                "queue_running": [],
                "queue_pending": [],
                "_error": "Failed to fetch queue status"
            })
        
        comfyui_queue_info = {
            "queue_running": [],  # 正在运行的任务列表
            "queue_pending": []   # 等待中的任务列表
        }
        
        # 构造任务信息的辅助函数
        def _build_task_info(task):
            """构造ComfyUI兼容的任务信息格式"""
            # 安全地提取 prompt 和 extra_data
            prompt_body = task.prompt_body or {}
            
            # 兼容两种格式：
            # 1. 新格式: {"prompt": {...}, "extra_data": {...}}
            # 2. 旧格式: 直接是 prompt 工作流定义
            if isinstance(prompt_body, dict) and "prompt" in prompt_body:
                prompt = prompt_body.get("prompt", {})
                extra_data = prompt_body.get("extra_data", {})
            else:
                prompt = prompt_body
                extra_data = {}
            
            return [
                1,  # number - 任务优先级
                task.task_id,  # prompt_id
                prompt or {},  # prompt - 避免None导致序列化失败
                extra_data or {},  # extra_data
                []  # outputs_to_execute    
            ]

        for task in all_tasks:
            # 根据任务状态分类
            if task.status == TaskStatus.RUNNING:
                comfyui_queue_info["queue_running"].append(_build_task_info(task))
            elif task.status == TaskStatus.PENDING:
                comfyui_queue_info["queue_pending"].append(_build_task_info(task))
        
        return jsonify(comfyui_queue_info)
    
    def handle_post_request(self):
        """
        处理 POST /api/queue 请求
        队列管理（清空/删除任务）
        
        Returns:
            Flask response
        """
        log("DEBUG", f"Handling POST /api/queue request")
        
        request_data = request.get_json() or {}
        
        if "clear" in request_data and request_data["clear"]:
            # 清空队列
            log("INFO", f"Clearing task queue")
            
            cleared_count = self.task_manager.clear_queue()
            log("INFO", f"Cleared {cleared_count} tasks from queue")
            
            return Response(status=200)
        
        elif "delete" in request_data:
            # 删除指定任务，停止对应的异步任务
            to_delete = request_data.get("delete", [])
            log("INFO", f"Deleting tasks: {to_delete}")
            
            deleted_count = 0
            for task_id in to_delete:
                cancel_result = self.task_manager.cancel_task(task_id)
                if cancel_result:
                    deleted_count += 1
                    log("DEBUG", f"Deleted task: {task_id}")
                else:
                    log("WARNING", f"Failed to delete task (not found or cannot be cancelled): {task_id}")
            
            log("INFO", f"Deleted {deleted_count} tasks from queue")
            
            return Response(status=200)
        
        else:
            # 无效的队列操作请求
            return jsonify({
                "error": {
                    "type": "invalid_request_error",
                    "message": "Invalid queue operation. Supported operations: clear, delete"
                }
            }), 400

