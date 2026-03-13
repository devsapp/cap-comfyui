"""
History Handler
处理 /history 请求逻辑
从 TaskManager 读取历史数据并返回 ComfyUI 兼容格式
"""
import time
import traceback
from collections import OrderedDict
from typing import Optional, Dict, Any, List
from flask import request, jsonify, g

from utils.logger import log


class HistoryHandler:
    """处理 /history 请求，从内存队列读取历史数据"""
    
    def __init__(self):
        """初始化 handler，获取任务管理器和状态枚举"""
        try:
            from services.gateway.task.task_manager import get_task_manager
            from services.gateway.task.task import TaskStatus
            self.task_manager = get_task_manager()
            self.TaskStatus = TaskStatus
        except Exception as e:
            log("ERROR", f"Failed to initialize HistoryHandler: {e}")
            self.task_manager = None
            self.TaskStatus = None
    
    def handle_get_request(self):
        """处理 GET /api/history 请求"""
        if not self._is_initialized():
            return jsonify({}), 503
        
        max_items = self._parse_max_items_param()
        history = self.task_manager.get_history(max_items=max_items)
        return jsonify(history)
    
    def handle_post_request(self):
        """处理 POST /api/history 请求（clear、delete，与 ComfyUI 对齐）"""
        if not self._is_initialized():
            return "", 503
        data = request.get_json(silent=True) or {}
        user_id = getattr(g, "user_id", "default")
        if data.get("clear"):
            self.task_manager.clear_history(user_id)
        if "delete" in data:
            to_delete = data["delete"]
            if isinstance(to_delete, list):
                self.task_manager.delete_history_items(to_delete, user_id)
        return "", 200
    
    def _is_initialized(self) -> bool:
        """检查服务是否已正确初始化"""
        return self.task_manager is not None and self.TaskStatus is not None
    
    def _parse_max_items_param(self) -> Optional[int]:
        """解析请求中的 max_items 参数）"""
        max_items_param = request.args.get('max_items')
        if not max_items_param:
            return None
        
        try:
            max_items = int(max_items_param)
            return max_items if max_items > 0 else None
        except ValueError:
            return None
