import json
import time
import threading
import uuid
import os
import queue
from typing import Dict, Optional, Callable, Any, List
from queue import Queue
from dataclasses import dataclass
from enum import Enum

import constants


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"      # 等待执行
    SUBMITTED = "submitted"  # 已提交
    PROCESSING = "processing"  # 正在执行
    COMPLETED = "completed"   # 已完成
    FAILED = "failed"        # 执行失败


@dataclass
class TaskRequest:
    """任务请求"""
    task_id: str
    client_id: str
    prompt: dict
    output_base64: bool = False
    output_oss: bool = False
    callback: Optional[Callable] = None
    create_at: Optional[float] = None
    started_at: Optional[float] = None
    status: TaskStatus = TaskStatus.PENDING
    
    def __post_init__(self):
        if self.create_at is None:
            self.create_at = time.time()


class TaskQueue:
    """任务队列"""
    
    def __init__(self, max_tasks: int = 20):
        self._queue = Queue()
        self._tasks: Dict[str, TaskRequest] = {}  # 存储任务信息
        self._lock = threading.Lock()
        self._worker = None
        self._running = False
        self._max_tasks = max_tasks  # 最大任务数量限制
        
        print(f"[TaskQueue] TaskQueue initialized (in-memory only)")
    
    
    def start_worker(self):
        """启动工作线程"""
        if self._running:
            return
            
        self._running = True
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()
        print("[TaskQueue] Worker started")
    
    def stop_worker(self):
        """停止工作线程"""
        if not self._running:
            return
            
        self._running = False
        self._queue.put(None)  # 停止信号
        if self._worker:
            self._worker.join(timeout=5.0)
        print("[TaskQueue] Worker stopped")
    
    def enqueue(self, 
                prompt: dict,
                client_id: str,
                task_id: str = None,
                output_base64: bool = False,
                output_oss: bool = False,
                callback: Optional[Callable] = None) -> str:
        """将任务加入队列"""
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
            # 先清理老任务，保持不超过最大数量
            if len(self._tasks) >= self._max_tasks:
                self._cleanup_old_tasks()
            
            self._tasks[task_id] = task_request
        
        self._queue.put(task_request)
        print(f"[TaskQueue] Task {task_id} enqueued for client {client_id}")
        return task_id
    
    def get_task(self, task_id: str) -> Optional[TaskRequest]:
        """获取任务信息"""
        with self._lock:
            return self._tasks.get(task_id)
    
    def get_task_status(self, task_id: str) -> Optional[TaskStatus]:
        """获取任务状态"""
        task = self.get_task(task_id)
        return task.status if task else None
    
    def get_queue_size(self) -> int:
        """获取队列大小"""
        return self._queue.qsize()
    
    def get_all_tasks(self) -> List[TaskRequest]:
        """获取所有任务列表（优化：快速复制避免长时间持锁）"""
        with self._lock:
            # 快速创建浅拷贝，减少持锁时间
            return list(self._tasks.values())
    
    def get_all_tasks_dict(self) -> Dict[str, dict]:
        """获取所有任务信息字典"""
        with self._lock:
            return {
                task_id: {
                    'task_id': task.task_id,
                    'client_id': task.client_id,
                    'create_at': task.create_at,
                    'started_at': task.started_at,
                    'status': task.status.value
                }
                for task_id, task in self._tasks.items()
            }
    
    def clear_queue(self) -> int:
        """清空队列，返回被清除的任务数量"""
        cleared_count = 0
        
        with self._lock:
            # 清空在内存队列中的任务(仅清理pending和submitted状态)
            task_ids_to_remove = []
            for task_id, task in self._tasks.items():
                if task.status in [TaskStatus.PENDING, TaskStatus.SUBMITTED]:
                    task_ids_to_remove.append(task_id)
            
            # 从内存中删除
            for task_id in task_ids_to_remove:
                self._tasks.pop(task_id, None)
                cleared_count += 1
            
            # 清空队列
            try:
                while True:
                    self._queue.get_nowait()
                    self._queue.task_done()
            except queue.Empty:
                pass  # 队列已空
        
        
        return cleared_count
    
    def cancel_task(self, task_id: str) -> bool:
        """取消任务，返回是否成功"""
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
    
    def update_task_id(self, old_task_id: str, new_task_id: str) -> bool:
        """更新任务ID，返回是否成功"""
        with self._lock:
            task = self._tasks.get(old_task_id)
            if not task:
                print(f"[TaskQueue] Cannot update task ID: task {old_task_id} not found")
                return False
            
            # 检查新任务ID是否已存在
            if new_task_id in self._tasks:
                print(f"[TaskQueue] Cannot update task ID: new task ID {new_task_id} already exists")
                return False
            
            # 更新任务ID
            task.task_id = new_task_id
            
            # 在字典中更新映射
            self._tasks[new_task_id] = task
            self._tasks.pop(old_task_id, None)
            
            print(f"[TaskQueue] Updated task ID: {old_task_id} -> {new_task_id}")
            return True
    
    def _cleanup_old_tasks(self):
        """
        清理最老的任务，确保不超过最大任务数量
        注意：此方法必须在持有 self._lock 的情况下调用
        """
        if len(self._tasks) <= self._max_tasks:
            return
        
        # 获取所有任务并按创建时间排序
        tasks_by_time = sorted(
            self._tasks.items(),
            key=lambda item: item[1].create_at or 0
        )
        
        # 计算需要删除的任务数量
        tasks_to_remove = len(self._tasks) - self._max_tasks + 1  # +1 为新任务腾出空间
        
        removed_count = 0
        for task_id, task in tasks_by_time[:tasks_to_remove]:
            # 只清理已完成或失败的任务，不清理正在处理的任务
            if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
                # 从内存中删除
                self._tasks.pop(task_id, None)
                
                removed_count += 1
                print(f"[TaskQueue] Removed old task {task_id} (status: {task.status.value})")
        
        if removed_count > 0:
            print(f"[TaskQueue] Cleaned up {removed_count} old tasks to maintain max {self._max_tasks} tasks")
    
    def _worker_loop(self):
        """工作线程循环"""
        print("[TaskQueue] Worker loop started")
        
        from .serverless_api_service import ServerlessApiService
        service = ServerlessApiService()
        
        while self._running:
            try:
                task_request = self._queue.get()
                
                # 检查停止信号
                if task_request is None:
                    break
                
                print(f"[TaskQueue] Processing task {task_request.task_id}")
                
                # 更新任务状态为处理中
                with self._lock:
                    task_request.status = TaskStatus.PROCESSING
                    task_request.started_at = time.time()
                
                try:
                    # 执行任务
                    result = service.run(
                        prompt=task_request.prompt,
                        output_base64=task_request.output_base64,
                        output_oss=task_request.output_oss,
                        callback=task_request.callback,
                        task_id=task_request.task_id
                    )

                    # 更新状态为完成
                    with self._lock:
                        task_request.status = TaskStatus.COMPLETED

                    print(f"[TaskQueue] Task {task_request.task_id} completed")
                    
                except Exception as e:
                    # 更新状态为失败
                    with self._lock:
                        task_request.status = TaskStatus.FAILED
                    
                    print(f"[TaskQueue] Task {task_request.task_id} failed: {e}")
                
                self._queue.task_done()
                
            except Exception as e:
                print(f"[TaskQueue] Worker error: {e}")
        
        print("[TaskQueue] Worker loop ended")


class TaskQueueManager:
    """任务队列管理器单例"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return
            
        self.queue = TaskQueue()
        self._status_pollers = {}  # 存储每个任务的状态轮询器
        self._poller_lock = threading.Lock()
        
        # 队列状态广播
        self._queue_status_broadcast_enabled = True
        self._queue_status_broadcast_interval = 5.0  # 5秒广播一次队列状态
        self._queue_status_broadcast_thread = None
        self._last_queue_status = None
        
        self._initialized = True
        print("[TaskQueueManager] Initialized with queue status broadcast")
    
    def start(self):
        """启动队列处理"""
        self.queue.start_worker()
        # 启动定期队列状态广播线程
        self._start_queue_status_broadcast()
    
    def stop(self):
        """停止队列处理"""
        self.queue.stop_worker()
        self._stop_queue_status_broadcast()
    
    def submit_task(self, **kwargs) -> str:
        """提交任务到队列"""
        task_id = self.queue.enqueue(**kwargs)
        self._start_status_polling(task_id)
        return task_id
    
    def get_task_info(self, task_id: str) -> Optional[dict]:
        """获取任务信息"""
        task = self.queue.get_task(task_id)
        if task:
            return {
                'task_id': task.task_id,
                'client_id': task.client_id,
                'create_at': task.create_at,
                'started_at': task.started_at,
                'status': task.status.value
            }
        return None
    
    def get_task_status(self, task_id: str) -> Optional[str]:
        """获取任务状态"""
        status = self.queue.get_task_status(task_id)
        return status.value if status else None
    
    def get_queue_status(self) -> dict:
        """获取队列状态"""
        return {
            'queue_size': self.queue.get_queue_size(),
            'all_tasks': self.queue.get_all_tasks()
        }
    
    def get_all_tasks(self) -> List[TaskRequest]:
        """获取所有任务列表"""
        return self.queue.get_all_tasks()
    
    def clear_queue(self) -> int:
        """清空队列，返回被清除的任务数量"""
        return self.queue.clear_queue()
    
    def cancel_task(self, task_id: str) -> bool:
        """取消任务，返回是否成功"""
        # 先停止状态轮询
        self._stop_status_polling(task_id)
        # 取消任务
        return self.queue.cancel_task(task_id)
    
    # NOTE: update_task_id方法已废弃 - 使用x-fc-trace-id保持请求ID一致性，无需动态更新
    # def update_task_id(self, old_task_id: str, new_task_id: str) -> bool:
    #     """更新任务ID，返回是否成功 - 已废弃，通过x-fc-trace-id保持ID一致性"""
    #     # 通过传递x-fc-trace-id给GPU函数，CPU和GPU两边的requestId保持一致
    #     # 无需在异步调用回调中更新task_id
    #     print(f"[TaskQueueManager] update_task_id method deprecated - using x-fc-trace-id for ID consistency")
    #     return True
    
    def _start_status_polling(self, task_id: str):
        """
        为任务启动状态轮询
        
        注意：
        - 只在CPU模式下使用，GPU函数不需要轮询
        - CPU函数负责转发任务到GPU函数，并通过轮询监控GPU函数写入的状态
        - GPU函数只负责执行任务并写入状态，不需要轮询
        """
        try:
            from services.gateway import StatusPoller, get_status_storage_service
            
            with self._poller_lock:
                # 检查是否已经有轮询器
                if task_id in self._status_pollers:
                    print(f"[TaskQueueManager] Task {task_id} already has status poller")
                    return
                
                # 获取状态存储服务
                storage_service = get_status_storage_service()
                
                # 创建状态轮询器（优化轮询频率提升并发性能）
                poller = StatusPoller(
                    task_id=task_id,
                    storage_service=storage_service,
                    poll_interval=0.5  # 0.5秒轮询一次，更快响应状态更新
                )
                
                # 设置状态更新回调
                poller.set_status_callback(self._on_status_update)
                
                # 启动轮询
                poller.start()
                
                # 存储轮询器
                self._status_pollers[task_id] = poller
                
                print(f"[TaskQueueManager] Started status polling for task {task_id}")
                
        except Exception as e:
            print(f"[TaskQueueManager] Failed to start status polling for task {task_id}: {e}")
    
    def _stop_status_polling(self, task_id: str, async_stop: bool = False):
        """停止任务的状态轮询"""
        with self._poller_lock:
            if task_id in self._status_pollers:
                poller = self._status_pollers.pop(task_id)
                
                if async_stop:
                    # 在状态回调中异步停止，避免死锁
                    def stop_poller():
                        try:
                            poller.stop()
                            print(f"[TaskQueueManager] Async stopped status polling for task {task_id}")
                        except Exception as e:
                            print(f"[TaskQueueManager] Error async stopping poller for task {task_id}: {e}")
                    
                    # 使用新线程异步停止
                    stop_thread = threading.Thread(target=stop_poller, daemon=True)
                    stop_thread.start()
                else:
                    # 直接停止（用于除状态回调外的其他地方）
                    poller.stop()
                    print(f"[TaskQueueManager] Stopped status polling for task {task_id}")
    
    def _on_status_update(self, task_id: str, status_data: dict):
        """状态更新回调函数（修复死锁：最小化持锁时间，异步化阻塞操作）"""
        import time as callback_time
        callback_start = callback_time.time()
        
        try:
            print(f"[TaskQueueManager] Processing status update for task {task_id}, type: {status_data.get('type', 'unknown')}")
            
            # 快速检查任务是否存在，立即释放锁
            task_exists = False
            current_status = None
            try:
                with self.queue._lock:
                    task_exists = task_id in self.queue._tasks
                    if task_exists:
                        current_status = self.queue._tasks[task_id].status
            except Exception as e:
                print(f"[TaskQueueManager] ERROR: Failed to check task {task_id}: {e}")
                return
            
            if not task_exists:
                print(f"[TaskQueueManager] Task {task_id} not found in queue")
                return
            
            # 根据状态类型处理更新
            status_type = status_data.get('type', '')
            
            if status_type == 'serverless_api':
                # 任务完成 - 异步处理避免死锁
                if current_status != TaskStatus.COMPLETED:
                    self._async_handle_task_completion(task_id, status_data)
                    
            elif status_type == 'error' or status_type == 'execution_error':
                # 任务失败 - 异步处理避免死锁
                if current_status != TaskStatus.FAILED:
                    self._async_handle_task_failure(task_id, status_data)
                    
            elif status_type == 'executing':
                # 任务执行中 - 快速状态更新
                node = status_data.get('data', {}).get('node')
                if node and current_status == TaskStatus.PENDING:
                    self._quick_update_to_processing(task_id)
            
            # 异步处理WebSocket广播，避免阻塞
            self._async_broadcast_status(task_id, status_data)
                
        except Exception as e:
            print(f"[TaskQueueManager] Error updating task {task_id} status: {e}")
    
    def _async_handle_task_completion(self, task_id: str, status_data: dict):
        """异步处理任务完成"""
        def handle_completion():
            try:
                # 原子更新状态
                updated = False
                with self.queue._lock:
                    if task_id in self.queue._tasks:
                        self.queue._tasks[task_id].status = TaskStatus.COMPLETED
                        updated = True
                
                if updated:
                    print(f"[TaskQueueManager] Task {task_id} marked as completed via status polling")
                    
                    # 生命周期日志：任务完成
                    from datetime import datetime
                    data = status_data.get('data', {})
                    output_count = len(data.get('results', []))
                    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [TaskLifecycle][{task_id}][COMPLETED] Task completed, outputs={output_count}")
                    
                    # 异步停止轮询器
                    self._stop_status_polling(task_id, async_stop=True)
                    
                    # 延迟清理任务
                    self._schedule_task_cleanup(task_id, "completed")
                    
            except Exception as e:
                print(f"[TaskQueueManager] Error handling task completion for {task_id}: {e}")
        
        # 在单独线程中处理
        threading.Thread(target=handle_completion, daemon=True).start()
    
    def _async_handle_task_failure(self, task_id: str, status_data: dict):
        """异步处理任务失败"""
        def handle_failure():
            try:
                # 原子更新状态
                updated = False
                with self.queue._lock:
                    if task_id in self.queue._tasks:
                        self.queue._tasks[task_id].status = TaskStatus.FAILED
                        updated = True
                
                if updated:
                    print(f"[TaskQueueManager] Task {task_id} marked as failed via status polling")
                    
                    # 生命周期日志：任务失败
                    from datetime import datetime
                    error_msg = status_data.get('data', {}).get('exception_message', 'Unknown error')
                    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [TaskLifecycle][{task_id}][FAILED] Task failed, error={error_msg}")
                    
                    # 异步停止轮询器
                    self._stop_status_polling(task_id, async_stop=True)
                    
                    # 延迟清理任务
                    self._schedule_task_cleanup(task_id, "failed")
                    
            except Exception as e:
                print(f"[TaskQueueManager] Error handling task failure for {task_id}: {e}")
        
        # 在单独线程中处理
        threading.Thread(target=handle_failure, daemon=True).start()
    
    def _quick_update_to_processing(self, task_id: str):
        """快速更新任务状态为处理中"""
        try:
            with self.queue._lock:
                if (task_id in self.queue._tasks and 
                    self.queue._tasks[task_id].status == TaskStatus.PENDING):
                    self.queue._tasks[task_id].status = TaskStatus.PROCESSING
                    if not self.queue._tasks[task_id].started_at:
                        self.queue._tasks[task_id].started_at = time.time()
                    print(f"[TaskQueueManager] Task {task_id} marked as processing via status polling")
                    
                    # 生命周期日志：任务执行中
                    from datetime import datetime
                    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [TaskLifecycle][{task_id}][EXECUTING] Task execution started on GPU")
        except Exception as e:
            print(f"[TaskQueueManager] Error updating task {task_id} to processing: {e}")
    
    def _async_broadcast_status(self, task_id: str, status_data: dict):
        """异步广播状态更新"""
        def broadcast():
            try:
                # WebSocket广播
                self._broadcast_task_status_via_websocket(task_id, status_data, True)
            except Exception as e:
                print(f"[TaskQueueManager] Error broadcasting status for task {task_id}: {e}")
        
        # 在单独线程中处理WebSocket广播
        threading.Thread(target=broadcast, daemon=True).start()
    
    def _schedule_task_cleanup(self, task_id: str, status: str):
        """调度任务清理"""
        def cleanup():
            try:
                import time
                time.sleep(5)  # 等待5秒让前端获取最终状态
                
                with self.queue._lock:
                    self.queue._tasks.pop(task_id, None)
                
                print(f"[TaskQueueManager] Cleaned up {status} task {task_id} from queue")
            except Exception as e:
                print(f"[TaskQueueManager] Error cleaning up {status} task {task_id}: {e}")
        
        # 在单独线程中处理清理
        threading.Thread(target=cleanup, daemon=True).start()
    
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
        print("[TaskQueueManager] Started queue status broadcast")
    
    def _stop_queue_status_broadcast(self):
        """停止队列状态广播"""
        self._queue_status_broadcast_enabled = False
        if self._queue_status_broadcast_thread and self._queue_status_broadcast_thread.is_alive():
            self._queue_status_broadcast_thread.join(timeout=5.0)
        print("[TaskQueueManager] Stopped queue status broadcast")
    
    def _queue_status_broadcast_loop(self):
        """队列状态广播循环"""
        print("[TaskQueueManager] Queue status broadcast loop started")
        
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
                print(f"[TaskQueueManager] Error in queue status broadcast loop: {e}")
                time.sleep(self._queue_status_broadcast_interval)
        
        print("[TaskQueueManager] Queue status broadcast loop stopped")
    
    def _get_queue_status_for_broadcast(self) -> dict:
        """获取用于广播的队列状态"""
        try:
            # 快速获取队列状态
            with self.queue._lock:
                total_tasks = len(self.queue._tasks)
                pending_tasks = sum(1 for task in self.queue._tasks.values() 
                                  if task.status in [TaskStatus.PENDING, TaskStatus.SUBMITTED])
                processing_tasks = sum(1 for task in self.queue._tasks.values() 
                                     if task.status == TaskStatus.PROCESSING)
                completed_tasks = sum(1 for task in self.queue._tasks.values() 
                                    if task.status == TaskStatus.COMPLETED)
                failed_tasks = sum(1 for task in self.queue._tasks.values() 
                                 if task.status == TaskStatus.FAILED)
            
            # 获取轮询器数量
            with self._poller_lock:
                active_pollers = len(self._status_pollers)
            
            return {
                'timestamp': time.time(),
                'queue_size': self.queue._queue.qsize(),
                'total_tasks': total_tasks,
                'pending_tasks': pending_tasks,
                'processing_tasks': processing_tasks,
                'completed_tasks': completed_tasks,
                'failed_tasks': failed_tasks,
                'active_pollers': active_pollers
            }
            
        except Exception as e:
            print(f"[TaskQueueManager] Error getting queue status: {e}")
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
        """广播队列状态给所有WebSocket连接"""
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
                sent_count = ws_manager.broadcast_comfyui_message("queue_status", comfyui_message)
                
                print(f"[TaskQueueManager] Broadcasted queue status to {sent_count} connections: "
                      f"pending={queue_status['pending_tasks']}, "
                      f"processing={queue_status['processing_tasks']}, "
                      f"total={queue_status['total_tasks']}")
            
        except Exception as e:
            print(f"[TaskQueueManager] Error broadcasting queue status: {e}")
    
    def broadcast_queue_status_immediately(self):
        """立即广播队列状态（用于手动触发）"""
        try:
            current_status = self._get_queue_status_for_broadcast()
            self._broadcast_queue_status(current_status)
            self._last_queue_status = current_status
            print("[TaskQueueManager] Manually broadcasted queue status")
        except Exception as e:
            print(f"[TaskQueueManager] Error in immediate queue status broadcast: {e}")
    
    def set_queue_status_broadcast_interval(self, interval: float):
        """设置队列状态广播间隔"""
        self._queue_status_broadcast_interval = max(1.0, interval)  # 最小1秒
        print(f"[TaskQueueManager] Queue status broadcast interval set to {self._queue_status_broadcast_interval}s")
    
    def enable_queue_status_broadcast(self, enabled: bool = True):
        """启用/禁用队列状态广播"""
        self._queue_status_broadcast_enabled = enabled
        if enabled:
            self._start_queue_status_broadcast()
        else:
            self._stop_queue_status_broadcast()
        print(f"[TaskQueueManager] Queue status broadcast {'enabled' if enabled else 'disabled'}")
    
    def cleanup_completed_tasks(self, max_age_seconds: int = 3600):
        """清理已完成的旧任务"""
        current_time = time.time()
        cleanup_task_ids = []
        
        with self.queue._lock:
            for task_id, task in self.queue._tasks.items():
                if (task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED] and 
                    task.create_at and 
                    current_time - task.create_at > max_age_seconds):
                    cleanup_task_ids.append(task_id)
        
        # 清理任务
        for task_id in cleanup_task_ids:
            # 停止轮询
            self._stop_status_polling(task_id)
            
            # 从内存中删除
            with self.queue._lock:
                self.queue._tasks.pop(task_id, None)
            
        
        if cleanup_task_ids:
            print(f"[TaskQueueManager] Cleaned up {len(cleanup_task_ids)} old completed tasks")
    
    
    def _broadcast_task_status_via_websocket(self, task_id: str, status_data: dict, queue_updated: bool):
        """
        通过WebSocket广播任务状态给订阅者，使用ComfyUI原生消息格式
        
        Args:
            task_id: 任务ID
            status_data: 从 GPU函数获取的原始状态数据
            queue_updated: 队列状态是否发生了更新
        """
        # 只在CPU模式下才需要推送（GPU模式下没有WebSocket订阅者）
        if constants.COMFYUI_MODE != "cpu":
            print(f"[TaskQueueManager] Skipping WebSocket broadcast - not in CPU mode (task: {task_id})")
            return
        
        try:
            from services.process.websocket.websocket_manager import ws_manager
            
            # 检查是否有订阅者
            subscriber_count = ws_manager.get_task_subscribers(task_id)
            print(f"[TaskQueueManager] Checking WebSocket subscribers for task {task_id}: {subscriber_count} subscribers")
            
            if subscriber_count == 0:
                print(f"[TaskQueueManager] No WebSocket subscribers for task {task_id}, skipping broadcast")
                return
            
            # 将GPU函数的状态数据转换为ComfyUI原生格式
            comfyui_message = self._convert_to_comfyui_message(task_id, status_data, queue_updated)
            
            if comfyui_message:
                # 处理单个消息或消息列表
                if isinstance(comfyui_message, list):
                    # 如果返回的是消息列表，逐个发送
                    for msg in comfyui_message:
                        msg_type = msg.get('type', 'unknown')
                        print(f"[TaskQueueManager] Broadcasting WebSocket message for task {task_id} "
                              f"(type: {msg_type}) to {subscriber_count} subscribers")
                        
                        sent_count = ws_manager.broadcast_comfyui_message(task_id, msg)
                        
                        print(f"[TaskQueueManager] ComfyUI WebSocket message broadcasted for task {task_id} "
                              f"(type: {msg_type}, sent to {sent_count} subscribers)")
                else:
                    # 单个消息
                    msg_type = comfyui_message.get('type', 'unknown')
                    print(f"[TaskQueueManager] Broadcasting WebSocket message for task {task_id} "
                          f"(type: {msg_type}) to {subscriber_count} subscribers")
                    
                    sent_count = ws_manager.broadcast_comfyui_message(task_id, comfyui_message)
                    
                    print(f"[TaskQueueManager] ComfyUI WebSocket message broadcasted for task {task_id} "
                          f"(type: {msg_type}, sent to {sent_count} subscribers)")
            else:
                print(f"[TaskQueueManager] Failed to convert status data to ComfyUI message for task {task_id}")
            
        except Exception as e:
            import traceback
            print(f"[TaskQueueManager] Failed to broadcast WebSocket status for task {task_id}: {e}")
            print(f"[TaskQueueManager] Traceback: {traceback.format_exc()}")
    
    def _convert_to_comfyui_message(self, task_id: str, status_data: dict, queue_updated: bool) -> dict:
        """
        将GPU函数的状态数据转换为ComfyUI原生消息格式
        
        Args:
            task_id: 任务ID
            status_data: GPU函数的原始状态数据
            queue_updated: 队列状态是否更新
            
        Returns:
            dict: ComfyUI原生格式的消息，如果不需要推送则返回None
        """
        try:
            status_type = status_data.get('type', '')
            data = status_data.get('data', {})
            
            if status_type == 'status':
                # 状态消息，更新队列信息
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
            
            elif status_type == 'executing':
                # 执行状态
                return {
                    "type": "executing",
                    "data": {
                        "node": data.get('node'),
                        "prompt_id": data.get('prompt_id', task_id)
                    }
                }
            
            elif status_type == 'progress':
                # 执行进度
                return {
                    "type": "progress",
                    "data": {
                        "value": data.get('value', 0),
                        "max": data.get('max', 100),
                        "node": data.get('node')
                    }
                }
            
            elif status_type == 'executed':
                # 节点执行完成
                return {
                    "type": "executed",
                    "data": {
                        "node": data.get('node'),
                        "output": data.get('output', {})
                    }
                }
            
            elif status_type == 'execution_start':
                # 执行开始
                return {
                    "type": "execution_start",
                    "data": {
                        "prompt_id": data.get('prompt_id', task_id)
                    }
                }
            
            elif status_type == 'execution_cached':
                # 缓存执行
                return {
                    "type": "execution_cached",
                    "data": {
                        "nodes": data.get('nodes', []),
                        "prompt_id": data.get('prompt_id', task_id)
                    }
                }
            
            elif status_type == 'serverless_api':
                # 任务完成，发送执行结束消息
                return [
                    # 首先发送执行结束消息
                    {
                        "type": "executing",
                        "data": {
                            "node": None,  # node为None表示执行结束
                            "prompt_id": data.get('prompt_id', task_id)
                        }
                    },
                    # 然后发送更新的队列状态
                    {
                        "type": "status",
                        "data": {
                            "status": {
                                "exec_info": {
                                    "queue_remaining": self._get_pending_task_count()
                                }
                            }
                        }
                    }
                ]
            
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
            print(f"[TaskQueueManager] Error converting to ComfyUI message format: {e}")
            return None
    
    def _get_pending_task_count(self) -> int:
        """获取待处理任务数量（PENDING、SUBMITTED和PROCESSING状态）"""
        with self.queue._lock:
            pending_count = 0
            for task in self.queue._tasks.values():
                if task.status in [TaskStatus.PENDING, TaskStatus.SUBMITTED, TaskStatus.PROCESSING]:
                    pending_count += 1
            return pending_count
    
    def associate_task_with_client_id(self, task_id: str, client_id: str):
        """
        将任务与指定的ComfyUI客户端关联，使前端能够接收到任务状态更新
        
        Args:
            task_id: 任务ID
            client_id: ComfyUI客户端ID
        """
        print(f"[TaskQueueManager] Attempting to associate task {task_id} with client_id {client_id}")
        print(f"[TaskQueueManager] Current COMFYUI_MODE: {constants.COMFYUI_MODE}")
        
        # 只在CPU模式下才需要关联
        if constants.COMFYUI_MODE != "cpu":
            print(f"[TaskQueueManager] Skipping client association - not in CPU mode")
            return
        
        try:
            from services.process.websocket.websocket_manager import ws_manager
            
            # 将任务与客户端关联
            associated_count = ws_manager.associate_task_with_client_id(task_id, client_id)
            
            if associated_count > 0:
                print(f"[TaskQueueManager] Task {task_id} successfully associated with ComfyUI client {client_id} ({associated_count} connections)")
            else:
                print(f"[TaskQueueManager] Failed to associate task {task_id} with client {client_id} - no connections found")
            
        except Exception as e:
            import traceback
            print(f"[TaskQueueManager] Failed to associate task {task_id} with client {client_id}: {e}")
            print(f"[TaskQueueManager] Traceback: {traceback.format_exc()}")
    
    def _log_current_task_summary(self):
        """输出当前任务状态摘要（用于诊断）"""
        try:
            with self.queue._lock:
                status_counts = {}
                current_time = time.time()
                old_tasks = []
                stuck_processing_tasks = []
                
                for task_id, task in self.queue._tasks.items():
                    status = task.status.value
                    status_counts[status] = status_counts.get(status, 0) + 1
                    
                    # 检查是否有老任务未清理
                    if task.create_at and current_time - task.create_at > 300:  # 5分钟以上
                        old_tasks.append({
                            'task_id': task_id[:8] + '...',  # 只显示前8位
                            'status': status,
                            'age_minutes': int((current_time - task.create_at) / 60),
                            'client_id': task.client_id[:8] + '...' if task.client_id else 'none'
                        })
                    
                    # 检查卡住的PROCESSING任务（超过5分钟仍在PROCESSING状态）
                    if (task.status == TaskStatus.PROCESSING and 
                        task.started_at and 
                        current_time - task.started_at > 300):  # 5分钟以上在处理
                        stuck_processing_tasks.append({
                            'task_id': task_id[:8] + '...',
                            'processing_minutes': int((current_time - task.started_at) / 60),
                            'client_id': task.client_id[:8] + '...' if task.client_id else 'none'
                        })
                
                pending_count = self._get_pending_task_count()
                active_pollers = len(self._status_pollers)
                
                print(f"[TaskQueueManager] === Task Summary ===")
                print(f"[TaskQueueManager] Total tasks in memory: {len(self.queue._tasks)}")
                print(f"[TaskQueueManager] Status counts: {status_counts}")
                print(f"[TaskQueueManager] Pending tasks (for queue_remaining): {pending_count}")
                print(f"[TaskQueueManager] Active status pollers: {active_pollers}")
                
                if old_tasks:
                    print(f"[TaskQueueManager] Old tasks (>5min): {old_tasks}")
                
                if stuck_processing_tasks:
                    print(f"[TaskQueueManager] ⚠️  Stuck PROCESSING tasks (>5min): {stuck_processing_tasks}")
                    print(f"[TaskQueueManager] ⚠️  These tasks may need manual cleanup!")
                
                print(f"[TaskQueueManager] ========================")
                
        except Exception as e:
            print(f"[TaskQueueManager] Error in task summary: {e}")
    
    def emergency_cleanup(self):
        """
        紧急清理机制：强制清理所有卡住的任务和轮询器
        用于解决死锁问题
        """
        print(f"[TaskQueueManager] 🆘 Starting EMERGENCY CLEANUP to resolve deadlocks...")
        
        cleanup_count = 0
        poller_cleanup_count = 0
        
        try:
            # 1. 强制清理所有轮询器（使用超时锁）
            try:
                if self._poller_lock.acquire(timeout=2.0):
                    try:
                        poller_ids = list(self._status_pollers.keys())
                        for task_id in poller_ids:
                            try:
                                poller = self._status_pollers.pop(task_id, None)
                                if poller:
                                    poller.stop()
                                    poller_cleanup_count += 1
                                    print(f"[TaskQueueManager] Force stopped poller for task {task_id[:8]}...")
                            except Exception as e:
                                print(f"[TaskQueueManager] Error stopping poller {task_id}: {e}")
                    finally:
                        self._poller_lock.release()
                else:
                    print(f"[TaskQueueManager] ⚠️  Cannot acquire poller lock, skipping poller cleanup")
            except Exception as e:
                print(f"[TaskQueueManager] Error in poller cleanup: {e}")
                        
            print(f"[TaskQueueManager] 🧽 Cleaned up {poller_cleanup_count} status pollers")
            
            # 2. 清理老任务（使用超时锁）
            current_time = time.time()
            try:
                if self.queue._lock.acquire(timeout=2.0):
                    try:
                        task_ids_to_remove = []
                        for task_id, task in list(self.queue._tasks.items()):
                            # 清理超过 2 分钟的任务
                            if (task.create_at and 
                                current_time - task.create_at > 120):  # 2分钟
                                task_ids_to_remove.append(task_id)
                                cleanup_count += 1
                        
                        for task_id in task_ids_to_remove:
                            self.queue._tasks.pop(task_id, None)
                            print(f"[TaskQueueManager] Force removed old task {task_id[:8]}...")
                    finally:
                        self.queue._lock.release()
                else:
                    print(f"[TaskQueueManager] ⚠️  Cannot acquire queue lock, skipping task cleanup")
            except Exception as e:
                print(f"[TaskQueueManager] Error in task cleanup: {e}")
            
            print(f"[TaskQueueManager] 🧽 Cleaned up {cleanup_count} old tasks")
            
            # 3. 清空队列（非阻塞方式）
            queue_cleared = 0
            while not self.queue._queue.empty():
                try:
                    self.queue._queue.get_nowait()
                    queue_cleared += 1
                except:
                    break
                    
            print(f"[TaskQueueManager] 🧽 Cleared {queue_cleared} items from task queue")
            
            print(f"[TaskQueueManager] ✅ EMERGENCY CLEANUP completed: {cleanup_count} tasks + {poller_cleanup_count} pollers + {queue_cleared} queue items removed")
            
        except Exception as e:
            print(f"[TaskQueueManager] ❌ Error in emergency cleanup: {e}")
            import traceback
            print(f"[TaskQueueManager] Cleanup error traceback: {traceback.format_exc()}")
    
    def check_deadlock_status(self) -> dict:
        """
        检查死锁状态
        返回系统是否可能处于死锁状态
        """
        deadlock_info = {
            'timestamp': time.time(),
            'possible_deadlock': False,
            'lock_status': {},
            'queue_status': {},
            'poller_status': {},
            'recommendations': []
        }
        
        try:
            # 检查队列锁状态
            if self.queue._lock.acquire(timeout=0.1):
                deadlock_info['lock_status']['queue_lock'] = 'available'
                self.queue._lock.release()
            else:
                deadlock_info['lock_status']['queue_lock'] = 'blocked'
                deadlock_info['possible_deadlock'] = True
                deadlock_info['recommendations'].append('Queue lock is blocked - possible deadlock')
            
            # 检查轮询器锁状态
            if self._poller_lock.acquire(timeout=0.1):
                deadlock_info['lock_status']['poller_lock'] = 'available'
                self._poller_lock.release()
            else:
                deadlock_info['lock_status']['poller_lock'] = 'blocked'
                deadlock_info['possible_deadlock'] = True
                deadlock_info['recommendations'].append('Poller lock is blocked - possible deadlock')
            
            # 检查队列状态
            deadlock_info['queue_status'] = {
                'queue_size': self.queue._queue.qsize(),
                'task_count': len(self.queue._tasks),
                'active_pollers': len(self._status_pollers)
            }
            
            # 检查是否有长时间运行的任务
            current_time = time.time()
            stuck_tasks = []
            for task_id, task in self.queue._tasks.items():
                if task.started_at and current_time - task.started_at > 300:  # 5分钟
                    stuck_tasks.append({
                        'task_id': task_id[:8] + '...',
                        'status': task.status.value,
                        'running_time': int(current_time - task.started_at)
                    })
            
            if stuck_tasks:
                deadlock_info['poller_status']['stuck_tasks'] = stuck_tasks
                deadlock_info['possible_deadlock'] = True
                deadlock_info['recommendations'].append(f'Found {len(stuck_tasks)} stuck tasks')
            
            # 检查轮询器状态
            active_pollers = []
            for task_id in self._status_pollers.keys():
                active_pollers.append(task_id[:8] + '...')
            
            deadlock_info['poller_status']['active_pollers'] = active_pollers
            
            if len(active_pollers) > 10:
                deadlock_info['possible_deadlock'] = True
                deadlock_info['recommendations'].append(f'Too many active pollers: {len(active_pollers)}')
            
        except Exception as e:
            deadlock_info['error'] = str(e)
            deadlock_info['possible_deadlock'] = True
        
        return deadlock_info


# 全局任务队列管理器实例 - 延迟初始化
_task_queue_manager = None

def get_task_queue_manager() -> TaskQueueManager:
    """获取全局任务队列管理器实例（延迟初始化）"""
    global _task_queue_manager
    if _task_queue_manager is None:
        print(f"[TaskQueue] Creating TaskQueueManager instance...")
        _task_queue_manager = TaskQueueManager()
        print(f"[TaskQueue] TaskQueueManager instance created")
    return _task_queue_manager

# 为了向后兼容，提供一个属性访问器
class TaskQueueManagerProxy:
    def __getattr__(self, name):
        return getattr(get_task_queue_manager(), name)

task_queue_manager = TaskQueueManagerProxy()
