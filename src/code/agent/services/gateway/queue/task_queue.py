"""
任务队列 - 核心任务管理功能
使用组合模式集成存储、轮询和广播功能
"""
import time
import threading
import uuid
import os
import traceback
import requests
from typing import Dict, Optional, Callable, List

import constants
from .task_models import TaskStatus, TaskRequest
from .task_storage_manager import TaskStorageManager
from .task_status_poller_manager import TaskStatusPollerManager
from .task_status_broadcaster import TaskStatusBroadcaster
from utils.logger import log


class TaskQueue:
    """任务队列 - 核心任务跟踪和管理功能"""
    
    _instance = None
    _instance_lock = threading.Lock()
    
    def __new__(cls, max_active_tasks: int = 999999, max_total_tasks: int = 999999):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    instance._max_active_tasks = max_active_tasks
                    instance._max_total_tasks = max_total_tasks
                    cls._instance = instance
        return cls._instance
    
    def __init__(self, max_active_tasks: int = 999999, max_total_tasks: int = 999999):
        # 只初始化一次
        if self._initialized:
            return
        
        self._tasks: Dict[str, TaskRequest] = {}  # 存储任务信息
        self._lock = threading.Lock()  # 实例级别的锁，保护任务字典
        
        # 初始化子模块
        self._storage_manager = TaskStorageManager()
        self._storage_manager.set_callbacks(
            get_task_fn=self._get_task_internal,
            add_task_to_memory_fn=self._add_task_to_memory,
            start_polling_fn=self._start_polling_internal
        )
        
        self._broadcaster = TaskStatusBroadcaster(
            get_pending_task_count_fn=self.get_running_task_count
        )
        
        self._poller_manager = TaskStatusPollerManager(
            update_task_to_terminal_status_fn=self._update_task_to_terminal_status,
            broadcast_task_status_fn=self._broadcaster.broadcast_task_status,
            broadcast_queue_status_fn=self._broadcast_queue_status_internal,
            schedule_task_cleanup_fn=self._schedule_task_cleanup
        )
        
        self._initialized = True
        storage_type = 'nas' if self._storage_manager.has_storage else 'memory'
        log("INFO", f"TaskQueue initialized (max_active_tasks={self._max_active_tasks}, max_total_tasks={self._max_total_tasks}, storage={storage_type})")
    
    def start(self):
        # 从 NAS 恢复任务（如果启用）
        restored_tasks = self._storage_manager.restore_tasks_from_nas()
        for task in restored_tasks:
            self._poller_manager.start_polling(task.task_id, self._poller_manager.on_status_update)
        log("INFO", f"[TaskQueue] TaskQueue started (restored_tasks={len(restored_tasks)}, storage_enabled={self._storage_manager.has_storage})")
    
    def stop(self):
        # 停止所有状态轮询器
        self._poller_manager.stop_all_pollers()
        log("INFO", "TaskQueue stopped")
    
    def submit_task(self, 
                    prompt: dict,
                    client_id: str,
                    task_id: Optional[str] = None,
                    callback: Optional[Callable] = None) -> str:
        if task_id is None:
            task_id = str(uuid.uuid4())
        
        task_request = TaskRequest(
            task_id=task_id,
            client_id=client_id,
            prompt=prompt,
            callback=callback
        )
        
        # 检查活跃任务数量 / 总任务数量
        if self._storage_manager.has_storage:
            active_tasks = self._storage_manager.get_active_task_count()
            total_tasks = active_tasks
        else:
            with self._lock:
                active_tasks = sum(
                    1 for task in self._tasks.values()
                    if task.status in [TaskStatus.PENDING, TaskStatus.PROCESSING]
                )
                total_tasks = len(self._tasks)
        
        with self._lock:
            if active_tasks >= self._max_active_tasks:
                raise RuntimeError(
                    f"Task queue is full. Active tasks: {active_tasks}/{self._max_active_tasks}. "
                    f"Please wait for some tasks to complete before submitting new ones."
                )
            
            if total_tasks >= self._max_total_tasks:
                raise RuntimeError(
                    f"Task storage is full. Total tasks: {total_tasks}/{self._max_total_tasks}. "
                    f"Please wait for some tasks to complete before submitting new ones."
                )
            
            self._tasks[task_id] = task_request
        
        # 持久化到 NAS（pending）
        self._storage_manager.save_task(task_request)
        
        # 提取 prompt_id 用于日志
        prompt_id = prompt.get('prompt_id', 'unknown') if isinstance(prompt, dict) else 'unknown'
        log("INFO", f"[TaskSubmit] Task {task_id} registered (prompt_id={prompt_id}, client_id={client_id}, queue_status={active_tasks}/{self._max_active_tasks} active, {total_tasks} total)")
        
        # 启动状态轮询（监控GPU函数端的状态）
        self._poller_manager.start_polling(task_id, self._poller_manager.on_status_update)
        
        # 广播队列状态更新（任务提交后）
        self._broadcast_queue_status()
        
        return task_id
    
    def get_all_tasks(self) -> List[TaskRequest]:
        with self._lock:
            # 快速创建浅拷贝，减少持锁时间
            return list(self._tasks.values())
    
    def get_running_task_count(self) -> int:
        """获取运行中任务数量（PENDING和PROCESSING状态）"""
        with self._lock:
            return sum(
                1 for task in self._tasks.values()
                if task.status in [TaskStatus.PENDING, TaskStatus.PROCESSING]
            )
    
    def clear_queue(self) -> int:
        """清空等待中的任务（仅清理 pending 状态）"""
        cleared_count = 0
        
        with self._lock:
            task_ids_to_remove = []
            for task_id, task in self._tasks.items():
                if task.status == TaskStatus.PENDING:
                    task_ids_to_remove.append(task_id)
            
            for task_id in task_ids_to_remove:
                self._tasks.pop(task_id, None)
                cleared_count += 1
        
        # 广播队列状态更新
        if cleared_count > 0:
            self._broadcast_queue_status()
        
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
                # 计算任务在旧状态的停留时间
                task_age = task.get_age()
                log("INFO", f"[TaskStatus] Task {task_id} status updated: {old_status.value} -> {new_status.value} (age={task_age:.1f}s)")
            else:
                log("WARNING", f"[TaskStatus] Failed to update task {task_id} status from {old_status.value} to {new_status.value} (invalid transition)")
            
        # 同步到 NAS（缩短内存锁持有时间）
        if success:
            self._storage_manager.sync_task_status(task_id, old_status, new_status)
        
        if success and old_status == TaskStatus.PENDING and new_status == TaskStatus.PROCESSING:
            self._broadcast_queue_status()
        
        return success
    
    def cancel_task(self, task_id: str) -> bool:
        # 先停止状态轮询
        self._poller_manager.stop_polling(task_id)
        
        # 取消任务
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            
            task_status = task.status
            
            # 如果任务正在处理中，需要调用函数计算的 StopAsyncTask API
            if task_status == TaskStatus.PROCESSING:
                self._stop_async_task(task_id)
            
            # 只能取消未开始执行或正在处理的任务
            if task_status not in [TaskStatus.PENDING, TaskStatus.PROCESSING]:
                return False
            
            # 从内存中删除
            self._tasks.pop(task_id, None)
            cancelled = True
        
        # 广播队列状态更新
        if cancelled:
            self._broadcast_queue_status()
        
        # 从 NAS 删除并更新索引
        self._storage_manager.delete_task(task_id)
        
        return True
    
    def associate_task_with_client_id(self, task_id: str, client_id: str):
        """
        将任务与指定的ComfyUI客户端关联，使前端能够接收到任务状态更新
        
        Args:
            task_id: 任务ID
            client_id: ComfyUI客户端ID
        """
        self._broadcaster.associate_task_with_client_id(task_id, client_id)
    
    # ========== 内部方法 ==========
    
    def _get_task_internal(self, task_id: str) -> Optional[TaskRequest]:
        """内部方法：获取任务（供存储管理器使用）"""
        with self._lock:
            return self._tasks.get(task_id)
    
    def _add_task_to_memory(self, task_id: str, task: TaskRequest):
        """内部方法：添加任务到内存（供存储管理器使用）"""
        with self._lock:
            self._tasks[task_id] = task
    
    def _start_polling_internal(self, task_id: str):
        """内部方法：启动状态轮询（供存储管理器使用）"""
        self._poller_manager.start_polling(task_id, self._poller_manager.on_status_update)
    
    def _update_task_to_terminal_status(self, task_id: str, target_status: TaskStatus, status_name: str) -> bool:
        """原子性地更新任务到终态（完成或失败）
        
        Args:
            task_id: 任务ID
            target_status: 目标状态（COMPLETED 或 FAILED）
            status_name: 状态名称（用于日志）
            
        Returns:
            bool: 是否成功更新（如果任务不存在或已是终态，返回False）
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                log("WARNING", f"Task {task_id} not found in queue ({status_name} update ignored)")
                return False
            
            # 如果已经是目标状态，可能是重复的状态更新
            if task.status == target_status:
                return False
            
            # 尝试更新状态
            if task.update_status(target_status):
                task_age = task.get_age()
                elapsed = task.get_elapsed_time()
                elapsed_str = f"{elapsed:.1f}s" if elapsed else "N/A"
                log("INFO", f"[TaskStatus] Task {task_id} marked as {target_status.value} (current_status={task.status.value}, age={task_age:.1f}s, elapsed={elapsed_str}, reason={status_name})")
                return True
            else:
                log("WARNING", f"Failed to update task {task_id} to {target_status.value} (current status: {task.status.value}, invalid transition)")
                return False
    
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
                
                # 从 NAS 删除任务文件并更新索引
                self._storage_manager.delete_task(task_id)
                
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
    
    def _broadcast_queue_status(self):
        """广播当前队列状态给所有连接（类似 ComfyUI 的 queue_updated）"""
        # 获取调用栈，用于追踪谁调用了广播
        import traceback as tb
        caller_stack = tb.extract_stack()
        caller_info = "unknown"
        if len(caller_stack) >= 2:
            caller_frame = caller_stack[-2]
            caller_info = f"{caller_frame.filename.split('/')[-1]}:{caller_frame.lineno} in {caller_frame.name}"
        
        self._broadcast_queue_status_internal(caller_info)
    
    def _broadcast_queue_status_internal(self, caller_info: str = "unknown"):
        """内部方法：广播队列状态（供轮询管理器使用）"""
        self._broadcaster.broadcast_queue_status(caller_info)
    
    def _stop_async_task(self, task_id: str):
        """
        调用函数计算的 StopAsyncTask API 停止异步任务
        
        Args:
            task_id: 任务ID
        """
        try:
            # 从环境变量获取函数计算信息
            fc_function_name = os.getenv("FC_FUNCTION_NAME", "")
            fc_endpoint = os.getenv("FC_ENDPOINT", "")
            fc_account_id = os.getenv("FC_ACCOUNT_ID", "")
            
            if not all([fc_function_name, fc_endpoint, fc_account_id]):
                log("WARNING", f"[StopAsyncTask] Missing FC configuration, cannot stop task {task_id}")
                return
            
            # 构造停止异步任务的 API URL (2023版本，不需要serviceName)
            # 格式: https://{account_id}.{endpoint}/2023-03-30/functions/{function}/async-invocations/{task_id}
            stop_url = f"https://{fc_account_id}.{fc_endpoint}/2023-03-30/functions/{fc_function_name}/async-invocations/{task_id}"
            
            # 获取临时凭证
            access_key_id = constants.ALIBABA_CLOUD_ACCESS_KEY_ID or os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "")
            access_key_secret = constants.ALIBABA_CLOUD_ACCESS_KEY_SECRET or os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "")
            security_token = constants.ALIBABA_CLOUD_SECURITY_TOKEN or os.getenv("ALIBABA_CLOUD_SECURITY_TOKEN", "")
            
            headers = {
                "Content-Type": "application/json"
            }
            
            if access_key_id and access_key_secret:
                # 使用临时凭证签名（简化版本，实际应该使用阿里云 SDK 进行签名）
                # 这里先使用基本认证，如果需要完整签名可以使用 aliyun-python-sdk-fc2
                headers["Authorization"] = f"FC {access_key_id}:{access_key_secret}"
                if security_token:
                    headers["x-fc-security-token"] = security_token
            
            # 调用停止异步任务 API
            resp = requests.put(stop_url, headers=headers, timeout=10)
            
            if resp.status_code == 204:
                log("INFO", f"[StopAsyncTask] Successfully stopped task {task_id}")
            else:
                log("WARNING", f"[StopAsyncTask] Failed to stop task {task_id}, status={resp.status_code}, response={resp.text}")
                
        except Exception as e:
            log("ERROR", f"[StopAsyncTask] Error stopping task {task_id}: {e}\n{traceback.format_exc()}")


# 全局任务队列实例 - 延迟初始化
_task_queue = None

def get_task_queue() -> TaskQueue:
    """获取全局任务队列实例"""
    global _task_queue
    if _task_queue is None:
        _task_queue = TaskQueue()
        # 启动队列状态广播线程
        _task_queue.start()
    return _task_queue
