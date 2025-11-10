"""
Status Poller
处理状态轮询相关的逻辑
"""
import json
import time
import threading
from typing import Optional, Callable, Any

from .storage import StatusStorageService
from utils.logger import log


class StatusPoller:
    """
    状态轮询器
    用于定期从存储中轮询工作流执行状态
    """
    
    def __init__(self, task_id: str, storage_service: StatusStorageService, poll_interval: float = 1.0):
        """
        初始化状态轮询器
        
        Args:
            task_id: 要轮询的任务ID
            storage_service: 状态存储服务实例
            poll_interval: 轮询间隔，单位秒，默认1.0秒
        """
        self.task_id = task_id
        self.storage_service = storage_service
        self.poll_interval = poll_interval
        self.is_running = False
        self.thread: Optional[threading.Thread] = None
        self.on_status_update: Optional[Callable[[str, Any], None]] = None
        
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
        log("INFO", f"Started polling for task {self.task_id}")
        
    def stop(self):
        """停止轮询线程"""
        if not self.is_running:
            return
            
        self.is_running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5.0)
        log("INFO", f"Stopped polling for task {self.task_id}")
        
    def _poll_loop(self):
        """轮询循环逻辑（使用增量文件读取）"""
        # 是否已找到任务完成状态
        task_completed = False
        
        while self.is_running and not task_completed:
            try:
                # 时间监控：轮询周期开始
                poll_start = time.time()
                
                # 使用增量文件读取，仅获取新增状态
                read_start = time.time()
                new_statuses = self.storage_service.get_status_incremental(self.task_id)
                read_cost = (time.time() - read_start) * 1000
                
                if new_statuses:
                    log("INFO", f"[Perf][{self.task_id}] File read cost: {read_cost:.1f}ms, got {len(new_statuses)} statuses")
                    
                    # 调用回调函数处理新状态
                    callback_start = time.time()
                    for status in new_statuses:
                        if self.on_status_update:
                            self.on_status_update(self.task_id, status)
                        else:
                            # 默认输出到控制台
                            log("DEBUG", f"Task {self.task_id} status update: {json.dumps(status, ensure_ascii=False)}")
                        
                        # 检查是否为任务完成状态
                        if self._is_status_completed(status):
                            task_completed = True
                            break
                    
                    callback_cost = (time.time() - callback_start) * 1000
                    poll_total = (time.time() - poll_start) * 1000
                    log("INFO", f"[Perf][{self.task_id}] Poll cycle: read={read_cost:.1f}ms, callback={callback_cost:.1f}ms, total={poll_total:.1f}ms")
                    
            except Exception as e:
                log("ERROR", f"Error polling task {self.task_id}: {e}")
                from traceback import print_exception
                print_exception(e)
            
            # 等待下次轮询
            if not task_completed:
                time.sleep(self.poll_interval)
            
        self.is_running = False
        
        # 清理状态读取缓存
        try:
            self.storage_service.cleanup_cache(self.task_id)
        except Exception as e:
            log("WARNING", f"Error cleaning up cache for task {self.task_id}: {e}")
    
    def _is_status_completed(self, status: dict) -> bool:
        """
        检查单个状态是否表示任务完成
        
        Args:
            status: 单个状态对象
            
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

