"""
Status Poller
处理状态轮询相关的逻辑
"""
import json
import time
import threading
from typing import Optional, Callable, Any

from utils.logger import log


def _is_status_completed(status: dict) -> bool:
    """
    检查单个状态是否表示任务完成

    Args:
        status

    Returns:
        True if status indicates task completion, False otherwise
    """
    if not status:
        return False

    status_type = status.get("type", "")

    # 如果是最终结果（serverless_api类型）或错误状态，认为任务完成
    if status_type in ["serverless_api", "error", "execution_error"]:
        return True

    return False


class StatusPoller:
    """
    状态轮询器
    用于定期从存储中轮询工作流执行状态
    """
    
    def __init__(self, task_id: str, poll_interval: float = 1.0):
        """
        初始化状态轮询器
        
        Args:
            task_id: 要轮询的任务ID
            poll_interval: 轮询间隔，单位秒，默认1.0秒
        """
        self.task_id = task_id
        self.poll_interval = poll_interval
        self.is_running = False
        self.thread: Optional[threading.Thread] = None
        self.on_status_update: Optional[Callable[[str, Any], None]] = None
        self.last_status_count = 0  # 记录已处理的状态数量
        
        from services.serverlessapi.serverless_api_service import ServerlessApiService
        self.service = ServerlessApiService()
        
    def set_status_callback(self, callback: Callable[[str, Any], None]):
        """
        设置状态更新回调函数
        
        Args:
            callback: 回调函数，参数为 (task_id, status_data)
        """
        self.on_status_update = callback
        
    def start(self):
        """启动轮询线程"""
        if self.is_running:
            log("DEBUG", f"Task {self.task_id} poller is already running")
            return
            
        self.is_running = True
        self.thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.thread.start()
        log("INFO", f"Started status polling for task {self.task_id}")
        
    def stop(self):
        """停止轮询线程"""
        if not self.is_running:
            return
            
        self.is_running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5.0)
        log("INFO", f"Stopped polling for task {self.task_id}")
        
    def _poll_loop(self):
        """轮询循环逻辑（通过serverless_api接口查询状态）"""
        # 是否已找到任务完成状态
        task_completed = False
        
        while self.is_running and not task_completed:
            try:
                all_statuses = self.service.get_status_from_store(self.task_id)
                
                # 只处理新增的状态
                new_statuses = all_statuses[self.last_status_count:]
                
                if new_statuses:
                    for status in new_statuses:
                        if self.on_status_update:
                            self.on_status_update(self.task_id, status)
                        else:
                            log("DEBUG", f"[Task] {self.task_id} status update: {json.dumps(status, ensure_ascii=False)}")
                        
                        self.last_status_count += 1
                        
                        if _is_status_completed(status):
                            task_completed = True
                            break
            except Exception as e:
                log("ERROR", f"Error polling task {self.task_id}: {e}")
                from traceback import print_exception
                print_exception(e)
            
            # 等待下次轮询
            if not task_completed:
                time.sleep(self.poll_interval)
            
        self.is_running = False

        log("DEBUG", f"Polling stopped for task {self.task_id}, processed {self.last_status_count} statuses")

