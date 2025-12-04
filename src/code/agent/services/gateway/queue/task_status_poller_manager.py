"""
任务状态轮询管理器 - 管理状态轮询器和状态更新处理
"""
import threading
import time
from typing import Dict, Callable, Optional

from .task_models import TaskStatus
from utils.logger import log


class TaskStatusPollerManager:
    """管理任务状态轮询器和状态更新处理"""
    
    def __init__(self,
                 update_task_to_terminal_status_fn: Callable[[str, TaskStatus, str], bool],
                 broadcast_task_status_fn: Callable[[str, dict], None],
                 broadcast_queue_status_fn: Callable[[], None],
                 schedule_task_cleanup_fn: Callable[[str, str], None]):
        """
        Args:
            update_task_to_terminal_status_fn: 更新任务到终态的函数
            broadcast_task_status_fn: 广播任务状态的函数
            broadcast_queue_status_fn: 广播队列状态的函数
            schedule_task_cleanup_fn: 调度任务清理的函数
        """
        self._status_pollers: Dict[str, object] = {}
        self._poller_lock = threading.Lock()
        
        self._update_task_to_terminal_status = update_task_to_terminal_status_fn
        self._broadcast_task_status = broadcast_task_status_fn
        self._broadcast_queue_status = broadcast_queue_status_fn
        self._schedule_task_cleanup = schedule_task_cleanup_fn
    
    def start_polling(self, task_id: str, status_callback: Callable[[str, dict], None]):
        """
        为任务启动状态轮询
        
        Args:
            task_id: 任务ID
            status_callback: 状态更新回调函数
        """
        try:
            from services.gateway.status import StatusPoller
            
            with self._poller_lock:
                if task_id in self._status_pollers:
                    return
                
                poller = StatusPoller(
                    task_id=task_id,
                    poll_interval=0.5
                )
                
                # 设置状态更新回调
                poller.set_status_callback(status_callback)
                
                # 启动轮询
                poller.start()
                
                # 存储轮询器
                self._status_pollers[task_id] = poller
                
                log("INFO", f"[StatusPoller] Started status polling for task {task_id} (poll_interval={self.poll_interval}s)")
                
        except Exception as e:
            log("ERROR", f"Failed to start status polling for task {task_id}: {e}")
    
    def stop_polling(self, task_id: str, async_stop: bool = False):
        """停止任务的状态轮询
        
        Args:
            task_id: 任务ID
            async_stop: 是否异步停止（用于避免死锁）
        """
        with self._poller_lock:
            if task_id not in self._status_pollers:
                return
            
            poller = self._status_pollers.pop(task_id)
            
            if async_stop:
                # 在状态回调中异步停止，避免死锁
                def stop_poller_with_timeout():
                    try:
                        # 尝试正常停止
                        if hasattr(poller, 'stop'):
                            poller.stop()
                    except Exception as e:
                        log("ERROR", f"Error async stopping poller for task {task_id}: {e}")
                        # 如果正常停止失败，尝试强制清理
                        try:
                            if hasattr(poller, 'force_stop'):
                                poller.force_stop()
                            elif hasattr(poller, '_stop_event'):
                                # 强制设置停止事件
                                poller._stop_event.set()
                        except Exception as force_error:
                            log("ERROR", f"Failed to force stop poller for task {task_id}: {force_error}")
                
                # 使用新线程异步停止，设置超时保护
                stop_thread = threading.Thread(target=stop_poller_with_timeout, daemon=True)
                stop_thread.start()
            else:
                # 直接停止（用于除状态回调外的其他地方）
                try:
                    if hasattr(poller, 'stop'):
                        poller.stop()
                    log("INFO", f"[StatusPoller] Stopped status polling for task {task_id} (polled_count={poller.last_status_count if hasattr(poller, 'last_status_count') else 'N/A'})")
                except Exception as e:
                    log("ERROR", f"Error stopping poller for task {task_id}: {e}")
    
    def stop_all_pollers(self):
        """停止所有状态轮询器"""
        with self._poller_lock:
            poller_ids = list(self._status_pollers.keys())
            for task_id in poller_ids:
                self.stop_polling(task_id, async_stop=False)
    
    def on_status_update(self, task_id: str, status_data: dict):
        """状态更新回调函数
        
        确保状态检查和更新是原子性的，避免在检查状态和更新状态之间
        任务被删除或状态被修改导致的竞态条件。
        """
        try:
            # 根据状态类型处理更新
            status_type = status_data.get('type', '')
            
            # 原子性地检查任务状态并更新（在锁内完成所有检查和更新）
            if status_type == 'serverless_api':
                # 任务完成状态
                if self._update_task_to_terminal_status(task_id, TaskStatus.COMPLETED, "completion"):
                    self._async_handle_task_termination_after_update(task_id, status_data, is_completed=True, broadcast_queue=True)
                    
            elif status_type in ('error', 'execution_error'):
                # 任务失败状态
                if self._update_task_to_terminal_status(task_id, TaskStatus.FAILED, "failure"):
                    self._async_handle_task_termination_after_update(task_id, status_data, is_completed=False, broadcast_queue=True)
            
            elif status_type == 'status':
                # 队列状态由 _broadcast_queue_status() 统一管理
                return
            else:
                # 其他状态消息（progress, executing等）正常广播
                log("DEBUG", f"[TaskStatusPollerManager] Broadcasting status update for task {task_id} (type: {status_type})")
                self._broadcast_task_status(task_id, status_data)
            
                
        except Exception as e:
            log("ERROR", f"Error in status update callback for task {task_id}: {e}")
            import traceback
            traceback.print_exc()
    
    def _async_handle_task_termination_after_update(self, task_id: str, status_data: dict, is_completed: bool, broadcast_queue: bool = False):
        """异步处理任务终止（完成或失败）
        
        在状态已原子性地更新为终态后，执行后续操作：
        - 广播任务完成/失败消息
        - 记录生命周期日志
        - 停止状态轮询器
        - 调度任务清理
        - 广播队列状态（如果需要）
        
        Args:
            task_id: 任务ID
            status_data: 状态数据
            is_completed: True表示完成，False表示失败
            broadcast_queue: 是否需要广播队列状态
        """
        def handle_termination():
            try:
                # 先广播任务完成/失败消息（同步，确保顶序）
                self._broadcast_task_status(task_id, status_data)
                
                # 生命周期日志
                if is_completed:
                    data = status_data.get('data', {})
                    output_count = len(data.get('results', []))
                    prompt_id = data.get('prompt_id', task_id)
                    execution_time = data.get('execution_time')
                    exec_time_str = f"{execution_time:.1f}s" if execution_time else "N/A"
                    log("INFO", f"[TaskLifecycle][{task_id}][COMPLETED] Task completed (prompt_id={prompt_id}, outputs={output_count}, execution_time={exec_time_str})")
                else:
                    data = status_data.get('data', {})
                    error_msg = data.get('exception_message', 'Unknown error')
                    node_id = data.get('node_id') or data.get('node', 'unknown')
                    node_type = data.get('node_type', 'unknown')
                    prompt_id = data.get('prompt_id', task_id)
                    log("INFO", f"[TaskLifecycle][{task_id}][FAILED] Task failed (prompt_id={prompt_id}, node_id={node_id}, node_type={node_type}, error={error_msg})")
                
                # 异步停止轮询器
                self.stop_polling(task_id, async_stop=True)
                
                # 延迟清理任务
                self._schedule_task_cleanup(task_id, "completed" if is_completed else "failed")
                
                # 最后广播队列状态更新
                if broadcast_queue:
                    self._broadcast_queue_status()
                    
            except Exception as e:
                log("ERROR", f"Error handling task termination for {task_id}: {e}")
        
        # 在单独线程中处理
        threading.Thread(target=handle_termination, daemon=True).start()

