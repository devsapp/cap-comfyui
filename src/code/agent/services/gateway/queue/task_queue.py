import time
import threading
import uuid
from typing import Dict, Optional, Callable, List

import constants
from .task_models import TaskStatus, TaskRequest
from utils.logger import log


class TaskQueue:
    """任务队列 - 包含任务跟踪、状态轮询、状态广播功能
    
    注意：任务实际执行在GPU函数端，CPU端只负责跟踪和监控任务状态
    """
    
    _instance = None
    _instance_lock = threading.Lock()  # 类级别的锁，用于单例创建
    
    def __new__(cls, max_active_tasks: int = 20, max_total_tasks: int = 100):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    instance._max_active_tasks = max_active_tasks
                    instance._max_total_tasks = max_total_tasks
                    cls._instance = instance
        return cls._instance
    
    def __init__(self, max_active_tasks: int = 20, max_total_tasks: int = 100):
        # 只初始化一次
        if self._initialized:
            return
        
        self._tasks: Dict[str, TaskRequest] = {}  # 存储任务信息
        self._lock = threading.Lock()  # 实例级别的锁，保护任务字典
        
        self._status_pollers = {}  # 存储每个任务的状态轮询器
        self._poller_lock = threading.Lock()
        
        self._queue_status_broadcast_enabled = True
        self._queue_status_broadcast_interval = 1.0
        self._queue_status_broadcast_thread = None
        self._last_queue_status = None
        
        self._initialized = True
        log("INFO", f"TaskQueue initialized (max_active_tasks={self._max_active_tasks}, max_total_tasks={self._max_total_tasks})")
    
    def start(self):
        # 启动队列状态广播
        self._start_queue_status_broadcast()
        log("INFO", "TaskQueue started")
    
    def stop(self):
        # 停止队列状态广播
        self._stop_queue_status_broadcast()
        
        # 停止所有状态轮询器
        self._stop_all_pollers()
        log("INFO", "TaskQueue stopped")
    
    def submit_task(self, 
                    prompt: dict,
                    client_id: str,
                    task_id: Optional[str] = None,
                    output_base64: bool = False,
                    output_oss: bool = False,
                    callback: Optional[Callable] = None) -> str:
        if task_id is None:
            task_id = str(uuid.uuid4())
        
        task_request = TaskRequest(
            task_id=task_id,
            client_id=client_id,
            prompt=prompt,
            output_base64=output_base64,
            output_oss=output_oss,
            callback=callback
        )
        
        with self._lock:
            # 检查活跃任务数量（只计算 pending、submitted 和 processing 状态的任务）
            active_tasks = sum(
                1 for task in self._tasks.values()
                if task.status in [TaskStatus.PENDING, TaskStatus.SUBMITTED, TaskStatus.PROCESSING]
            )
            
            # 检查总任务数量
            total_tasks = len(self._tasks)
            
            if active_tasks >= self._max_active_tasks:
                raise RuntimeError(
                    f"Task queue is full. Active tasks: {active_tasks}/{self._max_active_tasks}. "
                    f"Please wait for some tasks to complete before submitting new ones."
                )
            
            if total_tasks >= self._max_total_tasks:
                # 尝试清理已完成的任务
                self._cleanup_completed_tasks_unsafe()
                
                # 重新检查
                if len(self._tasks) >= self._max_total_tasks:
                    raise RuntimeError(
                        f"Task storage is full. Total tasks: {len(self._tasks)}/{self._max_total_tasks}. "
                        f"Some completed tasks could not be cleaned up. Please try again later."
                    )
            
            self._tasks[task_id] = task_request
        
        log("INFO", f"Task {task_id} registered for tracking (client: {client_id})")
        
        # 启动状态轮询（监控GPU函数端的状态）
        self._start_status_polling(task_id)
        
        return task_id
    
    def get_task(self, task_id: str) -> Optional[TaskRequest]:
        with self._lock:
            return self._tasks.get(task_id)
    
    def get_all_tasks(self) -> List[TaskRequest]:
        with self._lock:
            # 快速创建浅拷贝，减少持锁时间
            return list(self._tasks.values())
    
    def clear_queue(self) -> int:
        """清空等待中的任务（仅清理 pending 和 submitted 状态）"""
        cleared_count = 0
        
        with self._lock:
            task_ids_to_remove = []
            for task_id, task in self._tasks.items():
                if task.status in [TaskStatus.PENDING, TaskStatus.SUBMITTED]:
                    task_ids_to_remove.append(task_id)
            
            for task_id in task_ids_to_remove:
                self._tasks.pop(task_id, None)
                cleared_count += 1
        
        return cleared_count
    
    def update_task_status(self, task_id: str, new_status: TaskStatus) -> bool:
        """线程安全地更新任务状态
        
        Args:
            task_id: 任务ID
            new_status: 新状态
            
        Returns:
            bool: 是否成功更新
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                log("WARNING", f"Cannot update status: task {task_id} not found")
                return False
            
            old_status = task.status
            
            success = task.update_status(new_status)
            
            if success:
                log("INFO", f"Task {task_id} status updated: {old_status.value} -> {new_status.value}")
            else:
                log("WARNING", f"Failed to update task {task_id} status from {old_status.value} to {new_status.value} (invalid transition)")
            
            return success
    
    def cancel_task(self, task_id: str) -> bool:
        # 先停止状态轮询
        self._stop_status_polling(task_id)
        
        # 取消任务
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            
            # 只能取消未开始执行的任务
            if task.status not in [TaskStatus.PENDING, TaskStatus.SUBMITTED]:
                return False
            
            # 从内存中删除
            self._tasks.pop(task_id, None)
        
        return True
    
    def _cleanup_completed_tasks_unsafe(self):
        """清理已完成的任务（必须在持有 _lock 的情况下调用）
        
        注意：此方法不加锁，调用者必须已经持有 self._lock
        """
        now = time.time()
        to_remove = []
        
        for task_id, task in self._tasks.items():
            if task.status.is_terminal() and task.completed_at:
                # 清理完成超过 30 秒的任务
                if now - task.completed_at > 30:
                    to_remove.append(task_id)
        
        for task_id in to_remove:
            self._tasks.pop(task_id, None)
            log("DEBUG", f"Cleaned up old task {task_id} during queue full check")
        
        return len(to_remove)

    def _stop_all_pollers(self):
        with self._poller_lock:
            poller_ids = list(self._status_pollers.keys())
            for task_id in poller_ids:
                self._stop_status_polling(task_id, async_stop=False)
    
    def _start_status_polling(self, task_id: str):
        """
        为任务启动状态轮询
        """
        try:
            from services.gateway.status import StatusPoller, get_status_storage_service
            
            with self._poller_lock:
                if task_id in self._status_pollers:
                    log("DEBUG", f"Task {task_id} already has status poller")
                    return
                
                storage_service = get_status_storage_service()
                
                poller = StatusPoller(
                    task_id=task_id,
                    storage_service=storage_service,
                    poll_interval=0.5
                )
                
                # 设置状态更新回调
                poller.set_status_callback(self._on_status_update)
                
                # 启动轮询
                poller.start()
                
                # 存储轮询器
                self._status_pollers[task_id] = poller
                
                log("INFO", f"Started status polling for task {task_id}")
                
        except Exception as e:
            log("ERROR", f"Failed to start status polling for task {task_id}: {e}")
    
    def _stop_status_polling(self, task_id: str, async_stop: bool = False):
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
                        log("DEBUG", f"Async stopped status polling for task {task_id}")
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
                # 不等待线程完成，让它在后台运行
            else:
                # 直接停止（用于除状态回调外的其他地方）
                try:
                    if hasattr(poller, 'stop'):
                        poller.stop()
                    log("INFO", f"Stopped status polling for task {task_id}")
                except Exception as e:
                    log("ERROR", f"Error stopping poller for task {task_id}: {e}")
    
    def _on_status_update(self, task_id: str, status_data: dict):
        """状态更新回调函数（线程安全版本 - 修复竞态条件）
        
        确保状态检查和更新是原子性的，避免在检查状态和更新状态之间
        任务被删除或状态被修改导致的竞态条件。
        
        延迟链路：
        1. 状态轮询器检测到状态 (在 poller 中)
        2. -> 调用此回调函数 (此处开始计时)
        3. -> 在锁内更新内存任务状态
        4. -> 提交异步广播到线程池 (广播提交耗时)
        5. -> 在线程中进行 WS 发送 (广播实际耗时)
        """
        import time as callback_time
        callback_start = callback_time.time()
        
        try:
            # 根据状态类型处理更新
            status_type = status_data.get('type', '')
            log("DEBUG", f"Processing status update for task {task_id}, type: {status_type}")
            
            # 原子性地检查任务状态并更新（在锁内完成所有检查和更新）
            if status_type == 'serverless_api':
                # 任务完成状态：原子性地检查并更新
                with self._lock:
                    task = self._tasks.get(task_id)
                    if not task:
                        log("WARNING", f"Task {task_id} not found in queue (completion update ignored)")
                        return
                    
                    # 在锁内检查状态并更新
                    if task.status != TaskStatus.COMPLETED:
                        if task.update_status(TaskStatus.COMPLETED):
                            # 状态更新成功
                            log("INFO", f"Task {task_id} marked as completed (status: {task.status.value})")
                        else:
                            # 状态更新失败（可能是无效的状态转换）
                            log("WARNING", f"Failed to update task {task_id} to COMPLETED (current status: {task.status.value}, invalid transition)")
                            return
                    else:
                        # 任务已经是完成状态，可能是重复的状态更新
                        log("DEBUG", f"Task {task_id} already completed, ignoring duplicate update")
                        return
                
                # 在锁外执行异步操作，避免持锁时间过长
                self._async_handle_task_completion_after_update(task_id, status_data)
                    
            elif status_type == 'error' or status_type == 'execution_error':
                # 任务失败状态：原子性地检查并更新
                with self._lock:
                    task = self._tasks.get(task_id)
                    if not task:
                        log("WARNING", f"Task {task_id} not found in queue (failure update ignored)")
                        return
                    
                    if task.status != TaskStatus.FAILED:
                        if task.update_status(TaskStatus.FAILED):
                            log("INFO", f"Task {task_id} marked as failed (status: {task.status.value})")
                        else:
                            log("WARNING", f"Failed to update task {task_id} to FAILED (current status: {task.status.value}, invalid transition)")
                            return
                    else:
                        log("DEBUG", f"Task {task_id} already failed, ignoring duplicate update")
                        return
                
                # 在锁外执行异步操作
                self._async_handle_task_failure_after_update(task_id, status_data)
                    
            elif status_type == 'executing':
                # 任务执行中状态：原子性地检查并更新
                node = status_data.get('data', {}).get('node')
                if node:
                    with self._lock:
                        task = self._tasks.get(task_id)
                        if not task:
                            # 任务不存在，忽略执行中状态更新
                            return
                        
                        if task.status == TaskStatus.PENDING:
                            if task.update_status(TaskStatus.PROCESSING):
                                log("INFO", f"Task {task_id} marked as processing via status polling")
                                
                                # 生命周期日志：任务执行中
                                log("INFO", f"[TaskLifecycle][{task_id}][EXECUTING] Task execution started on GPU")
            
            # 广播状态（不依赖任务状态，可以在锁外执行）
            broadcast_start = callback_time.time()
            self._async_broadcast_status(task_id, status_data)
            broadcast_queued_time = callback_time.time() - broadcast_start
            
            callback_time_elapsed = callback_time.time() - callback_start
            if callback_time_elapsed > 0.1:
                log("DEBUG", f"Status update callback took {callback_time_elapsed:.3f}s for task {task_id} "
                      f"(broadcast queue time: {broadcast_queued_time*1000:.2f}ms, status_type: {status_type})")
                
        except Exception as e:
            log("ERROR", f"Error in status update callback for task {task_id}: {e}")
            import traceback
            traceback.print_exc()

    def _start_queue_status_broadcast(self):
        """启动队列状态广播"""
        if not self._queue_status_broadcast_enabled:
            return
        
        if self._queue_status_broadcast_thread and self._queue_status_broadcast_thread.is_alive():
            return
        
        self._queue_status_broadcast_thread = threading.Thread(
            target=self._queue_status_broadcast_loop, 
            daemon=True,
            name="queue-status-broadcast"
        )
        self._queue_status_broadcast_thread.start()
        log("INFO", "Started queue status broadcast")
    
    def _stop_queue_status_broadcast(self):
        """停止队列状态广播"""
        self._queue_status_broadcast_enabled = False
        if self._queue_status_broadcast_thread and self._queue_status_broadcast_thread.is_alive():
            self._queue_status_broadcast_thread.join(timeout=5.0)
        log("INFO", "Stopped queue status broadcast")
    
    def _queue_status_broadcast_loop(self):
        """队列状态广播循环"""
        log("INFO", "Queue status broadcast loop started")
        
        while self._queue_status_broadcast_enabled:
            try:
                # 获取当前队列状态
                current_status = self._get_queue_status_for_broadcast()
                
                # 检查状态是否有变化
                if self._has_queue_status_changed(current_status):
                    # 广播队列状态
                    self._broadcast_queue_status(current_status)
                    self._last_queue_status = current_status
                
                # 等待下次广播
                time.sleep(self._queue_status_broadcast_interval)
                
            except Exception as e:
                log("ERROR", f"Error in queue status broadcast loop: {e}")
                time.sleep(self._queue_status_broadcast_interval)
        
        log("INFO", "Queue status broadcast loop stopped")
    
    def _get_queue_status_for_broadcast(self) -> dict:
        """获取用于广播的队列状态"""
        try:
            # 快速获取队列状态
            with self._lock:
                total_tasks = len(self._tasks)
                pending_tasks = sum(1 for task in self._tasks.values() 
                                  if task.status in [TaskStatus.PENDING, TaskStatus.SUBMITTED])
                processing_tasks = sum(1 for task in self._tasks.values() 
                                     if task.status == TaskStatus.PROCESSING)
                completed_tasks = sum(1 for task in self._tasks.values() 
                                    if task.status == TaskStatus.COMPLETED)
                failed_tasks = sum(1 for task in self._tasks.values() 
                                 if task.status == TaskStatus.FAILED)
            
            # 获取轮询器数量
            with self._poller_lock:
                active_pollers = len(self._status_pollers)
            
            # queue_size 表示等待处理的任务数（pending + processing）
            queue_size = pending_tasks + processing_tasks
            
            return {
                'timestamp': time.time(),
                'queue_size': queue_size,  # 等待和处理中的任务总数
                'total_tasks': total_tasks,
                'pending_tasks': pending_tasks,
                'processing_tasks': processing_tasks,
                'completed_tasks': completed_tasks,
                'failed_tasks': failed_tasks,
                'active_pollers': active_pollers
            }
            
        except Exception as e:
            log("ERROR", f"Error getting queue status: {e}")
            return {
                'timestamp': time.time(),
                'queue_size': 0,
                'total_tasks': 0,
                'pending_tasks': 0,
                'processing_tasks': 0,
                'completed_tasks': 0,
                'failed_tasks': 0,
                'active_pollers': 0
            }
    
    def _has_queue_status_changed(self, current_status: dict) -> bool:
        """检查队列状态是否有变化"""
        if not self._last_queue_status:
            return True
        
        # 比较关键字段
        key_fields = ['queue_size', 'pending_tasks', 'processing_tasks', 'completed_tasks', 'failed_tasks']
        
        for field in key_fields:
            if current_status.get(field) != self._last_queue_status.get(field):
                return True
        
        return False
    
    def _broadcast_queue_status(self, queue_status: dict):
        """广播队列状态给所有WebSocket连接（异步非阻塞）"""
        try:
            # 只在CPU模式下广播
            if constants.COMFYUI_MODE != "cpu":
                return
            
            # 构建ComfyUI格式的队列状态消息
            # ComfyUI的queue_remaining应该包含所有等待和正在处理的任务
            queue_remaining = queue_status['pending_tasks'] + queue_status['processing_tasks']
            comfyui_message = {
                "type": "status",
                "data": {
                    "status": {
                        "exec_info": {
                            "queue_remaining": queue_remaining
                        }
                    }
                }
            }
            
            # 广播给所有WebSocket连接
            from services.process.websocket.websocket_manager import ws_manager
            
            # 获取所有活跃连接
            active_connections = len(ws_manager.active_connections)
            if active_connections > 0:
                # 使用特殊的广播ID "queue_status" 来标识队列状态广播
                # 异步广播，不阻塞队列状态线程
                sent_count = ws_manager.broadcast_comfyui_message_async("queue_status", comfyui_message)
                
                log("DEBUG", f"Queued queue status broadcast to {sent_count} connections: "
                      f"pending={queue_status['pending_tasks']}, "
                      f"processing={queue_status['processing_tasks']}, "
                      f"total={queue_status['total_tasks']}")
            
        except Exception as e:
            log("ERROR", f"Error broadcasting queue status: {e}")
    
    def _async_handle_task_completion_after_update(self, task_id: str, status_data: dict):
        """异步处理任务完成（状态已更新版本）
        
        在状态已经原子性地更新为 COMPLETED 后，执行后续操作：
        - 记录生命周期日志
        - 停止状态轮询器
        - 调度任务清理
        
        注意：此方法假设状态已经在 _on_status_update 中原子性地更新了
        """
        def handle_completion():
            try:
                # 验证任务仍然存在（可能在更新后很快被清理）
                with self._lock:
                    task = self._tasks.get(task_id)
                    if not task:
                        log("WARNING", f"Task {task_id} was removed before completion handling")
                        return
                    
                    # 验证状态确实是 COMPLETED
                    if task.status != TaskStatus.COMPLETED:
                        log("WARNING", f"Task {task_id} status is {task.status.value}, expected COMPLETED")
                        return
                
                # 生命周期日志：任务完成
                data = status_data.get('data', {})
                output_count = len(data.get('results', []))
                log("INFO", f"[TaskLifecycle][{task_id}][COMPLETED] Task completed, outputs={output_count}")
                
                # 异步停止轮询器
                self._stop_status_polling(task_id, async_stop=True)
                
                # 延迟清理任务
                self._schedule_task_cleanup(task_id, "completed")
                    
            except Exception as e:
                log("ERROR", f"Error handling task completion for {task_id}: {e}")
        
        # 在单独线程中处理
        threading.Thread(target=handle_completion, daemon=True).start()
    
    def _async_handle_task_failure_after_update(self, task_id: str, status_data: dict):
        """异步处理任务失败（状态已更新版本）
        
        在状态已经原子性地更新为 FAILED 后，执行后续操作：
        - 记录生命周期日志
        - 停止状态轮询器
        - 调度任务清理
        
        注意：此方法假设状态已经在 _on_status_update 中原子性地更新了
        """
        def handle_failure():
            try:
                # 验证任务仍然存在（可能在更新后很快被清理）
                with self._lock:
                    task = self._tasks.get(task_id)
                    if not task:
                        log("WARNING", f"Task {task_id} was removed before failure handling")
                        return
                    
                    # 验证状态确实是 FAILED
                    if task.status != TaskStatus.FAILED:
                        log("WARNING", f"Task {task_id} status is {task.status.value}, expected FAILED")
                        return
                
                # 生命周期日志：任务失败
                error_msg = status_data.get('data', {}).get('exception_message', 'Unknown error')
                log("INFO", f"[TaskLifecycle][{task_id}][FAILED] Task failed, error={error_msg}")
                
                # 异步停止轮询器
                self._stop_status_polling(task_id, async_stop=True)
                
                # 延迟清理任务
                self._schedule_task_cleanup(task_id, "failed")
                    
            except Exception as e:
                log("ERROR", f"Error handling task failure for {task_id}: {e}")
        
        # 在单独线程中处理
        threading.Thread(target=handle_failure, daemon=True).start()
    
    def _async_broadcast_status(self, task_id: str, status_data: dict):
        """异步广播状态更新"""
        def broadcast():
            try:
                # WebSocket广播
                self._broadcast_task_status_via_websocket(task_id, status_data)
            except Exception as e:
                log("ERROR", f"Error broadcasting status for task {task_id}: {e}")
        
        # 在单独线程中处理WebSocket广播
        threading.Thread(target=broadcast, daemon=True).start()
    
    def _schedule_task_cleanup(self, task_id: str, status: str, delay: float = 5.0):
        """调度任务清理
        
        Args:
            task_id: 任务ID
            status: 任务状态描述
            delay: 延迟清理时间（秒），默认5秒让前端获取最终状态
        """
        def cleanup():
            try:
                time.sleep(delay)
                
                with self._lock:
                    task = self._tasks.pop(task_id, None)
                    if task:
                        log("DEBUG", f"Cleaned up {status} task {task_id} from queue")
                    else:
                        log("DEBUG", f"Task {task_id} already cleaned up")
                
            except Exception as e:
                log("ERROR", f"Error cleaning up {status} task {task_id}: {e}")
                # 确保任务最终被清理，即使出错
                try:
                    with self._lock:
                        self._tasks.pop(task_id, None)
                except:
                    pass
        
        # 在单独线程中处理清理
        cleanup_thread = threading.Thread(target=cleanup, daemon=True, name=f"cleanup-{task_id}")
        cleanup_thread.start()
    
    def _broadcast_task_status_via_websocket(self, task_id: str, status_data: dict):
        """
        通过WebSocket广播任务状态给订阅者，使用ComfyUI原生消息格式
        
        Args:
            task_id: 任务ID
            status_data: 从 GPU函数获取的原始状态数据
        """
        try:
            # 只在CPU模式下广播
            if constants.COMFYUI_MODE != "cpu":
                return
            
            from services.process.websocket.websocket_manager import ws_manager
            
            # 转换为ComfyUI格式
            comfyui_message = self._convert_to_comfyui_message_format(task_id, status_data)
            if not comfyui_message:
                return
            
            # 广播消息
            if isinstance(comfyui_message, list):
                for msg in comfyui_message:
                    sent_count = ws_manager.broadcast_comfyui_message(task_id, msg)
                    if sent_count > 0:
                        log("DEBUG", f"Broadcasted {msg.get('type')} message for task {task_id} to {sent_count} connections")
            else:
                sent_count = ws_manager.broadcast_comfyui_message(task_id, comfyui_message)
                if sent_count > 0:
                    log("DEBUG", f"Broadcasted {comfyui_message.get('type')} message for task {task_id} to {sent_count} connections")
            
        except Exception as e:
            log("ERROR", f"Error broadcasting task status via WebSocket: {e}")
    
    def _convert_to_comfyui_message_format(self, task_id: str, status_data: dict):
        """将状态数据转换为ComfyUI消息格式"""
        try:
            status_type = status_data.get('type', '')
            data = status_data.get('data', {})
            
            if status_type == 'serverless_api':
                # 最终结果
                return {
                    "type": "serverless_api",
                    "data": data
                }
            
            elif status_type == 'executing':
                # 执行中状态
                node = data.get('node')
                if node:
                    return {
                        "type": "executing",
                        "data": {
                            "node": node,
                            "prompt_id": data.get('prompt_id', task_id)
                        }
                    }
            
            elif status_type == 'progress':
                # 进度更新
                return {
                    "type": "progress",
                    "data": {
                        "value": data.get('value', 0),
                        "max": data.get('max', 100),
                        "prompt_id": data.get('prompt_id', task_id)
                    }
                }
            
            elif status_type == 'status':
                # 状态更新
                return {
                    "type": "status",
                    "data": {
                        "status": {
                            "exec_info": {
                                "queue_remaining": self._get_pending_task_count()
                            }
                        }
                    }
                }
            
            elif status_type == 'error' or status_type == 'execution_error':
                # 执行错误
                return {
                    "type": "execution_error",
                    "data": {
                        "prompt_id": data.get('prompt_id', task_id),
                        "node_id": data.get('node_id'),
                        "exception_message": data.get('exception_message', str(data.get('message', 'Unknown error'))),
                        "exception_type": data.get('exception_type', 'RuntimeError'),
                        "traceback": data.get('traceback', [])
                    }
                }
            
            # 其他类型的消息直接返回
            return status_data
            
        except Exception as e:
            log("ERROR", f"Error converting to ComfyUI message format: {e}")
            return None
    
    def _get_pending_task_count(self) -> int:
        """获取待处理任务数量（PENDING、SUBMITTED和PROCESSING状态）"""
        with self._lock:
            return sum(
                1 for task in self._tasks.values()
                if task.status in [TaskStatus.PENDING, TaskStatus.SUBMITTED, TaskStatus.PROCESSING]
            )
    
    def associate_task_with_client_id(self, task_id: str, client_id: str):
        """
        将任务与指定的ComfyUI客户端关联，使前端能够接收到任务状态更新
        
        Args:
            task_id: 任务ID
            client_id: ComfyUI客户端ID
        """
        log("DEBUG", f"Attempting to associate task {task_id} with client_id {client_id}")
        log("DEBUG", f"Current COMFYUI_MODE: {constants.COMFYUI_MODE}")
        
        # 只在CPU模式下才需要关联
        if constants.COMFYUI_MODE != "cpu":
            log("DEBUG", f"Skipping client association - not in CPU mode")
            return
        
        try:
            from services.process.websocket.websocket_manager import ws_manager
            
            # 将任务与客户端关联
            associated_count = ws_manager.associate_task_with_client_id(task_id, client_id)
            
            if associated_count > 0:
                log("INFO", f"Task {task_id} successfully associated with ComfyUI client {client_id} ({associated_count} connections)")
            else:
                log("WARNING", f"Failed to associate task {task_id} with client {client_id} - no connections found")
            
        except Exception as e:
            import traceback
            log("ERROR", f"Failed to associate task {task_id} with client {client_id}: {e}")
            log("ERROR", f"Traceback: {traceback.format_exc()}")

# 全局任务队列实例 - 延迟初始化
_task_queue = None

def get_task_queue() -> TaskQueue:
    """获取全局任务队列实例"""
    global _task_queue
    if _task_queue is None:
        log("DEBUG", f"Creating TaskQueue instance...")
        _task_queue = TaskQueue()
        # 启动队列状态广播线程
        _task_queue.start()
        log("DEBUG", f"TaskQueue instance created and started")
    return _task_queue

