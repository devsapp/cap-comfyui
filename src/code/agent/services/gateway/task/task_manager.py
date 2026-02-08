"""
任务管理器 - 核心任务管理功能
使用组合模式集成轮询和广播功能
"""
import json
import threading
import time
import traceback
import uuid
from collections import defaultdict
from typing import Dict, Optional, Callable, List, Tuple, Union, Any

import constants
import requests
from flask import request, g
from utils.logger import log
from exceptions.exceptions import (
    ConfigurationError,
    InvalidRequestError,
    TaskQueueFullError,
    InternalError,
    WorkerExecutionError
)

from .task import TaskStatus, Task
from .utils.task_manager_util import TaskStatusBroadcaster
from .history_manager import HistoryManager


class TaskManager:
    """任务管理器
    """

    def __init__(self,
                 max_active_tasks: int = 10000,
                 max_completed_tasks: int = 1024,
                 gpu_function_url: Optional[str] = None):
        self._max_active_tasks = max_active_tasks
        self._max_completed_tasks = max_completed_tasks
        self._gpu_function_url = gpu_function_url or constants.GPU_FUNCTION_URL
        
        # 任务字典
        self._tasks: Dict[str, Task] = {}
        self._lock = threading.Lock()

        # 历史记录辅助器
        self._history_manager = HistoryManager()
        
        # 已完成任务计数器（COMPLETED + FAILED）
        self._completed_task_count = 0
        
        # {user_id: running_count}
        self._running_count_by_user: Dict[str, int] = defaultdict(int)
        
        # 消息轮询器管理
        self._message_pollers: Dict[str, 'MessagesPoller'] = {}
        self._poller_lock = threading.Lock()
        
        # ServerlessApiService 实例(用于轮询)
        from services.serverlessapi.serverless_api_service import ServerlessApiService
        self._serverless_service = ServerlessApiService()
    
    def start(self):
        log("INFO", "[TaskManager] TaskManager started")
    
    def stop(self):
        # 停止所有状态轮询器
        self._stop_all_pollers()
        log("INFO", "[TaskManager] TaskManager stopped")
    
    def submit_task(self, 
                    prompt_body: dict,
                    client_id: str,
                    task_id: Optional[str] = None) -> str:
        if task_id is None:
            task_id = str(uuid.uuid4())
        
        user_id = getattr(g, 'user_id', 'default')
        
        task_request = Task(
            task_id=task_id,
            client_id=client_id,
            prompt_body=prompt_body,
            user_id=user_id
        )
        
        # 检查活跃任务数量
        with self._lock:
            active_tasks = sum(
                1 for task in self._tasks.values()
                if task.status in [TaskStatus.PENDING, TaskStatus.RUNNING]
            )
            
            if active_tasks >= self._max_active_tasks:
                raise TaskQueueFullError(
                    "Task queue is full",
                    active_tasks=active_tasks,
                    max_tasks=self._max_active_tasks
                )
            
            self._tasks[task_id] = task_request
            self._running_count_by_user[user_id] += 1
        
        # 启动状态轮询(监控GPU函数端的状态)
        self._start_polling(task_id)
        
        # 广播队列状态更新(任务提交后)
        TaskStatusBroadcaster.broadcast_queue_status()
        
        return task_id
    
    def get_current_user_tasks(self) -> List[Task]:
        """获取当前用户的所有任务"""
        user_id = getattr(g, 'user_id', 'default')
        with self._lock:
            return [task for task in self._tasks.values() if task.user_id == user_id]
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """
        根据任务ID获取任务对象
        
        Args:
            task_id: 任务ID
            
        Returns:
            Task对象，如果任务不存在则返回None
        """
        with self._lock:
            return self._tasks.get(task_id)
    
    def get_running_task_count_by_user(self, user_id: str) -> int:
        """
        获取指定用户的运行中任务数量
        
        Args:
            user_id: 用户ID
            
        Returns:
            运行中任务数量（包括 PENDING 和 RUNNING 状态）
        """
        with self._lock:
            return self._running_count_by_user.get(user_id, 0)
    
    def get_history(self, max_items=None, offset: int = -1) -> dict[Any, Any]:
        """
        获取历史记录（从 history_helper 获取）
        
        Args:
            max_items: 最大返回数量
            offset: 偏移量，-1 表示从末尾开始
            
        Returns:
            dict: 历史记录字典，格式为 {prompt_id: {prompt, outputs, status, meta, user_id}}
                  只返回已完成（status.completed == True）且属于当前用户的历史记录
        """
        user_id = getattr(g, 'user_id', 'default')
        
        # HistoryManager 已经是线程安全的，不需要额外加锁
        return self._history_manager.get_history(user_id, max_items, offset)
    
    def clear_queue(self) -> int:
        """
        清空队列：删除当前用户的 PENDING 任务和所有已完成任务（COMPLETED/FAILED）
        不删除 RUNNING 状态的任务（正在执行）

        Returns:
            int: 清理的任务数量
        """
        user_id = getattr(g, 'user_id', 'default')
        tasks_to_cleanup = []  # 存储需要清理的任务信息（在锁外清理 history）
        
        # 在锁内：收集、删除任务，更新计数器
        with self._lock:
            # 获取当前用户的所有任务
            user_tasks = [task for task in self._tasks.values() if task.user_id == user_id]
            
            pending_count = 0
            completed_count = 0
            cleared_count = 0
            
            for task in user_tasks:
                # 只删除 PENDING 和已完成的任务
                if task.status == TaskStatus.PENDING:
                    if self._tasks.pop(task.task_id, None):
                        cleared_count += 1
                        pending_count += 1
                        tasks_to_cleanup.append(task.task_id)
                        
                elif task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                    if self._tasks.pop(task.task_id, None):
                        cleared_count += 1
                        completed_count += 1
                        tasks_to_cleanup.append(task.task_id)
            
            # 更新已完成任务计数器
            if completed_count > 0:
                self._completed_task_count = max(0, self._completed_task_count - completed_count)
            
            # 更新运行中任务计数（只需减去被清理的 PENDING 任务）
            if pending_count > 0:
                self._running_count_by_user[user_id] -= pending_count
        
        # 清理 history
        for task_id in tasks_to_cleanup:
            self._history_manager.remove_history_item(task_id)

        # 广播队列状态更新
        if cleared_count > 0:
            TaskStatusBroadcaster.broadcast_queue_status()
            log("INFO", f"[TaskManager] User {user_id} cleared {cleared_count} tasks (including {completed_count} completed)")

        return cleared_count
    
    def cancel_task(self, task_id: str) -> bool:
        """
        取消任务（只能取消当前用户的任务）
        
        Args:
            task_id: 要取消的任务ID
            
        Returns:
            bool: 是否成功取消（True表示成功，False表示任务不存在、不可取消或无权限）
        """
        user_id = getattr(g, 'user_id', 'default')
        
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            
            # 只允许取消自己的任务
            if task.user_id != user_id:
                log("WARNING", f"[TaskManager] User {user_id} cannot cancel task {task_id} (belongs to {task.user_id})")
                return False
            
            old_status = task.status
            
            # 只能取消未开始执行或正在处理的任务
            if old_status not in [TaskStatus.PENDING, TaskStatus.RUNNING]:
                log("DEBUG", f"[TaskManager] Cannot cancel task {task_id}: status is {old_status}")
                return False
            
            # 从内存中删除
            self._tasks.pop(task_id, None)
            
            # 减少运行中任务计数
            self._running_count_by_user[user_id] -= 1
            
            log("INFO", f"[TaskManager] User {user_id} cancelled task {task_id} (was {old_status})")
        
        # 停止轮询
        try:
            self._stop_polling(task_id)
        except Exception as e:
            log("ERROR", f"[TaskManager] Error stopping polling for cancelled task {task_id}: {e}")
        
        # 广播队列状态更新
        TaskStatusBroadcaster.broadcast_queue_status()
        
        return True
    
    
    def _start_polling(self, task_id: str) -> None:
        """
        为任务启动状态轮询
        
        Args:
            task_id: 任务ID
        """
        try:
            with self._poller_lock:
                if task_id in self._message_pollers:
                    return
                
                poll_interval = 0.5
                poller = MessagesPoller(
                    task_id=task_id,
                    poll_interval=poll_interval,
                    message_callback=self.handle_message,
                    serverless_service=self._serverless_service
                )
                
                # 启动轮询
                poller.start()
                
                # 存储轮询器
                self._message_pollers[task_id] = poller
                
                log("INFO", f"[TaskManager] Started messages polling for task {task_id} (poll_interval={poll_interval}s)")
                
        except Exception as e:
            log("ERROR", f"[TaskManager] Failed to start messages polling for task {task_id}: {e}")
    
    def _stop_polling(self, task_id: str) -> None:
        """
        停止任务的消息轮询
        
        Args:
            task_id: 任务ID
        """
        with self._poller_lock:
            if task_id not in self._message_pollers:
                return
            
            poller = self._message_pollers.pop(task_id)
            
            try:
                poller.stop()
                log("INFO", f"[TaskManager] Stopped messages polling for task {task_id}")
            except Exception as e:
                log("ERROR", f"[TaskManager] Error stopping poller for task {task_id}: {e}")
    
    def _stop_all_pollers(self) -> None:
        """停止所有消息轮询器"""
        with self._poller_lock:
            poller_ids = list(self._message_pollers.keys())
            for task_id in poller_ids:
                poller = self._message_pollers.pop(task_id)
                try:
                    poller.stop()
                except Exception as e:
                    log("ERROR", f"[TaskManager] Error stopping poller for task {task_id}: {e}")
    
    # ==================== 任务生命周期管理方法 ====================
    
    def handle_message(self, task_id: str, message: Union[dict, str]) -> None:
        """
        来自 poller 的消息回调。根据消息类型自动确定目标状态
        
        Args:
            task_id: 任务ID
            message: 消息数据（dict 或原始字符串）
        """
        try:
            status_type = message.get('type', '')
            # TODO 原生comfyui history 兜底逻辑
            if status_type == 'execution_start':
                # 任务开始执行
                self._update_task_status(task_id, message, TaskStatus.RUNNING)
                # 初始化 history_item（在 execution_start 时最合适）
                self._init_history_item(task_id, message)

            elif status_type == 'execution_success':
                # 任务完成
                self._update_task_status(task_id, message, TaskStatus.COMPLETED)
                # 更新 history_item 的 status
                self._update_history_status(message, "success")

            elif status_type == 'execution_cached':
                # 节点执行缓存（节点已缓存，跳过执行）
                # 更新 history_item 的 status
                self._update_history_status(message, "running")

            elif status_type == 'executed':
                # 单节点任务执行结束
                data = message.get("data", {})
                prompt_id = data.get("prompt_id")
                node_id = data.get("node")
                
                if not prompt_id:
                    log("WARNING", f"[TaskManager] executed message missing prompt_id for task {task_id}")
                    return
                
                if not node_id:
                    log("WARNING", f"[TaskManager] executed message missing node_id for task {task_id}")
                    return
                
                # 检查 history_item 是否存在（HistoryManager 已经是线程安全的）
                history_item = self._history_manager.get_history_item(prompt_id)
                
                # 如果 history_item 不存在，尝试延迟初始化
                if not history_item:
                    log("WARNING", f"[TaskManager] History item not found for prompt_id {prompt_id} in executed message")
                    
                    # 需要在锁内获取 task 信息
                    with self._lock:
                        task = self._tasks.get(task_id)
                        if not task:
                            log("ERROR", f"[TaskManager] Cannot process executed message: task {task_id} not found")
                            return
                        
                        # 验证 prompt_id 是否匹配
                        if task.task_id != prompt_id:
                            log("ERROR", f"[TaskManager] prompt_id mismatch: task.task_id={task.task_id}, message.prompt_id={prompt_id}")
                            return
                        
                        # 保存任务信息（在锁外调用 HistoryManager）
                        task_prompt_body = task.prompt_body
                        task_client_id = task.client_id
                        task_user_id = task.user_id
                    
                    # 延迟初始化（HistoryManager 已经是线程安全的）
                    self._history_manager.late_init_history_item(
                        task_id=task_id,
                        prompt_id=prompt_id,
                        prompt_body=task_prompt_body,
                        client_id=task_client_id,
                        user_id=task_user_id
                    )
                
                # 更新 history outputs（HistoryManager 已经是线程安全的）
                self._history_manager.update_history_outputs(message)
            elif status_type == 'execution_error':
                # 任务执行失败
                self._update_task_status(task_id, message, TaskStatus.FAILED)
                # 更新 history_item 的 status
                self._update_history_status(message, "error")

            elif status_type == 'error':
                # 各类错误（包括validate prompt失败、ComfyUI异常等）
                # 更新任务状态为FAILED
                self._update_task_status(task_id, message, TaskStatus.FAILED)
                
                log("ERROR", f"[TaskManager] Task {task_id} failed with error: {message.get('error_message', 'unknown error')}")
                
                # 将error消息转换为ComfyUI前端能识别的格式
                # 保存原始error信息
                original_error_message = message.get('error_message', 'Unknown error')
                original_error_code = message.get('error_code', 'ValidationError')
                original_raw = message.get('raw', {})
                
                # 提取node_errors（如果是validate错误，GPU会返回node_errors）
                node_errors = {}
                if isinstance(original_raw, dict):
                    node_errors = original_raw.get('node_errors', {})
                
                # 从node_errors中提取第一个失败节点的信息（如果有的话）
                error_node_id = None
                error_node_type = "validation"
                error_detail_message = original_error_message
                
                if node_errors:
                    # 获取第一个失败的节点
                    first_node_id = next(iter(node_errors))
                    node_error_info = node_errors[first_node_id]
                    error_node_id = first_node_id
                    error_node_type = node_error_info.get('class_type', 'unknown')
                    
                    # 提取该节点的详细错误信息
                    errors_list = node_error_info.get('errors', [])
                    if errors_list:
                        first_error = errors_list[0]
                        error_detail_message = f"{first_error.get('message', '')}: {first_error.get('details', '')}"
                
                # 构造execution_error格式的消息，供WebSocket广播
                message = {
                    "type": "execution_error",
                    "data": {
                        "prompt_id": task_id,
                        "node_id": error_node_id or "__validation__",  # 使用真实的node_id或特殊标识
                        "node_type": error_node_type,
                        "executed": [],  # validate失败时没有节点被执行
                        "exception_message": error_detail_message,  # 使用详细的错误信息
                        "exception_type": original_error_code,
                        "traceback": [],
                        "current_inputs": [],
                        "current_outputs": []
                    }
                }

            elif status_type == 'status':
                # 忽略纯 status 消息, agent的队列代替comfyui自己的队列
                return
        except Exception as e:
            log("DEBUG", f"[TaskManager] Error handling message for task {task_id}: {e}")


        TaskStatusBroadcaster.broadcast_task_status(task_id, message)
    
    def _init_history_item(self, task_id: str, message: dict) -> None:
        """
        初始化 history_item（在 execution_start 时调用）
        Args:
            task_id: 任务ID
            message: execution_start 消息
        """
        try:
            # 提取 prompt_id（如果消息中没有，就使用 task_id）
            data = message.get("data", {})
            prompt_id = data.get("prompt_id") or task_id
            
            # 第二步：获取任务信息
            with self._lock:
                task = self._tasks.get(task_id)
                if not task:
                    log("WARNING", f"[TaskManager] Cannot initialize history_item: task {task_id} not found")
                    return
                
                user_id = task.user_id
                prompt_body = task.prompt_body
                client_id = task.client_id
            
            # 第三步：委托给 HistoryManager 处理（在锁外）
            # HistoryManager 已经是线程安全的，不需要额外加锁
            self._history_manager.init_history_item(
                prompt_id=prompt_id,
                prompt_body=prompt_body,
                client_id=client_id,
                user_id=user_id,
                message=message
            )
                
        except Exception as e:
            log("ERROR", f"[TaskManager] Error initializing history_item for task {task_id}: {e}\n{traceback.format_exc()}")
    
    def _update_history_status(self, message: dict, status_str: str) -> None:
        self._history_manager.update_history_status(message, status_str)
    
    def _update_task_status(self, task_id: str, status_data: dict, target_status: TaskStatus) -> bool:
        """
        更新任务状态(包括记录 + 转换)
        
        Args:
            task_id: 任务ID
            status_data: 状态数据
            target_status: 目标任务状态 (RUNNING/COMPLETED/FAILED)
            
        Returns:
            bool: 是否成功更新
        """
        try:
            # 执行原子更新
            with self._lock:
                task = self._tasks.get(task_id)
                if not task:
                    log("WARNING", f"[TaskManager] Task {task_id} not found in queue (status update ignored)")
                    return False
                
                if task.status == target_status:
                    return False
                
                # 记录旧状态用于更新计数
                old_status = task.status
                success = task.update_status(target_status)
                
                # 更新运行中任务计数
                if success:
                    old_is_running = old_status in [TaskStatus.PENDING, TaskStatus.RUNNING]
                    new_is_running = target_status in [TaskStatus.PENDING, TaskStatus.RUNNING]
                    
                    if old_is_running and not new_is_running:
                        # 从运行中变为完成/失败
                        self._running_count_by_user[task.user_id] -= 1

            if success and target_status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                # 增加已完成任务计数
                with self._lock:
                    self._completed_task_count += 1
                # 检查是否需要清理旧任务
                self._cleanup_old_completed_tasks_if_needed()
            TaskStatusBroadcaster.broadcast_queue_status()
            
            return success
        
        except Exception as e:
            log("ERROR", f"[TaskManager] Error updating status for task {task_id}: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    # FIXME:@dehui.kdh, 实现更优雅的清理逻辑
    def _cleanup_old_completed_tasks_if_needed(self) -> None:
        """检查是否需要清理旧的已完成任务（基于计数器，只在超过阈值时才执行清理）"""
        # 使用计数器快速判断是否需要清理
        if self._completed_task_count <= self._max_completed_tasks:
            return
        
        try:
            # 收集需要删除的任务（在锁内）
            tasks_to_remove = []
            
            with self._lock:
                # 再次检查（双重检查锁定）
                if self._completed_task_count <= self._max_completed_tasks:
                    return
                
                # 收集所有已完成的任务
                completed_tasks = [
                    (task_id, task) for task_id, task in self._tasks.items()
                    if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
                ]
                
                # 按完成时间排序（最新的在前）
                completed_tasks.sort(key=lambda x: x[1].completed_at or 0, reverse=True)
                
                # 获取需要删除的任务（保留最新的 max_completed_tasks 个）
                tasks_to_remove = completed_tasks[self._max_completed_tasks:]
                
                # 删除任务（但先不删除 history）
                removed_count = 0
                for task_id, task in tasks_to_remove:
                    if self._tasks.pop(task_id, None):
                        removed_count += 1
                
                # 更新计数器
                self._completed_task_count = len(completed_tasks) - removed_count
            
            # 在锁外删除 history（避免长时间持锁）
            removed_history_count = 0
            for task_id, task in tasks_to_remove:
                # 防御性检查：确保 history 的 user_id 与 task 一致
                # （使用 HistoryManager 的线程安全方法）
                history_item = self._history_manager.get_history_item(task.task_id)
                if history_item and history_item.get('user_id') == task.user_id:
                    if self._history_manager.remove_history_item(task.task_id):
                        removed_history_count += 1
            
            if removed_count > 0:
                log("INFO", f"[TaskManager] Cleaned up {removed_count} old tasks and {removed_history_count} history items (keeping latest {self._max_completed_tasks}, current count: {self._completed_task_count})")
        
        except Exception as e:
            log("ERROR", f"[TaskManager] Error cleaning up old completed tasks: {e}")
            import traceback
            traceback.print_exc()
    
    # ==================== GPU 转发方法 ====================
    
    def forward_to_gpu_async(self, 
                             request_body: dict, 
                             client_id: str) -> Tuple[str, object]:
        """
        GPU异步转发逻辑
        
        Args:
            request_body: comfyui prompt请求
            client_id: 客户端ID(用于WebSocket广播)
            
        Returns:
            tuple: (task_id, response) - 成功时返回任务ID和响应对象
            
        Raises:
            ConfigurationError: GPU URL未配置
            InvalidRequestError: 缺少任务ID
            TaskQueueFullError: 队列已满
            WorkerExecutionError: GPU转发失败或异步调用失败
        """
        request_id = request.headers.get('x-fc-request-id', 'unknown')

        # 检查GPU URL配置
        if not self._gpu_function_url:
            log("ERROR", f"[TaskManager][RequestId={request_id}] GPU_FUNCTION_URL not configured")
            raise ConfigurationError("GPU_FUNCTION_URL not configured for CPU mode")
        
        # 提取任务ID
        try:
            task_id = self._extract_task_id_from_request()
        except ValueError as e:
            log("ERROR", f"[TaskManager][RequestId={request_id}] {str(e)}")
            raise InvalidRequestError(str(e), error_code="missing_task_id")

        # 将任务添加到管理器
        try:
            self.submit_task(
                prompt_body=request_body,
                client_id=client_id,
                task_id=task_id
            )
        except (InvalidRequestError, TaskQueueFullError):
            raise
        except Exception as e:
            # 其他未预期的内部错误
            error_msg = f"Failed to add task to queue: {e}"
            log("ERROR", f"[TaskManager][TaskId={task_id}][RequestId={request_id}] {error_msg}\n{traceback.format_exc()}")
            raise InternalError(error_msg) from e
        
        # 构造GPU URL和headers
        gpu_url = f"{self._gpu_function_url.rstrip('/')}/api/serverless/run"
        
        forward_headers = {
            'x-fc-async-task-id': task_id,
            'x-fc-trace-id': task_id,
            'x-fc-invocation-type': 'Async'
        }
        
        # 复制客户端的其他 headers
        # 跳过我们已经设置的 headers，避免被覆盖
        # 透传host会导致请求在cpu函数上循环调用，透传content-length会导致下游读取payload截断
        skip_headers = {'x-fc-async-task-id', 'x-fc-trace-id', 'x-fc-invocation-type', 'host', 'content-length'}
        for k, v in request.headers.items():
            if k.lower() not in skip_headers:
                forward_headers[k] = v
        
        # 转发请求到GPU
        try:
            resp = requests.post(
                gpu_url,
                json=request_body,
                headers=forward_headers,
                params=request.args,
                timeout=30
            )
        except Exception as e:
            # 处理转发GPU失败的情况
            error_msg = f"Failed to send request to GPU: {str(e)}"
            log("ERROR", f"[TaskManager][TaskId={task_id}][RequestId={request_id}] {error_msg}\nStacktrace:\n{traceback.format_exc()}")
            
            # 更新任务状态为 FAILED
            try:
                self._update_task_status(task_id, {
                    'type': 'execution_error',
                    'timestamp': int(time.time() * 1000),
                    'data': {'error': error_msg}
                }, TaskStatus.FAILED)
            except Exception as status_error:
                log("WARNING", f"[TaskManager][TaskId={task_id}] Failed to update task status to FAILED: {status_error}")
            
            raise WorkerExecutionError(error_msg, error_code="worker_forward_error")
            
        # 检查 GPU 响应状态
        if resp.status_code != 202:
            # GPU 拒绝了请求，更新为 FAILED
            try:
                self._update_task_status(task_id, {
                    'type': 'execution_error',
                    'timestamp': int(time.time() * 1000),
                    'data': {'error': f'GPU returned HTTP {resp.status_code}'}
                }, TaskStatus.FAILED)
            except Exception as e:
                log("WARNING", f"[TaskId={task_id}] Failed to update task status to FAILED: {e}\n{traceback.format_exc()}")
            
            raise WorkerExecutionError(
                f"Failed to invoke GPU function asynchronously: HTTP {resp.status_code}",
                status_code=resp.status_code,
                error_code="async_invocation_error"
            )

        # 返回task_id和response
        return task_id, resp

    def forward_to_gpu_sync(self, request_body: dict) -> Tuple[dict, int]:
        """
        GPU同步转发逻辑（等待GPU处理完成并返回结果）
        
        Args:
            request_body: 完整的请求体
            
        Returns:
            tuple: (response_dict, status_code) - GPU返回的原始响应
            
        Raises:
            ConfigurationError: GPU URL未配置
            InvalidRequestError: 缺少任务ID
            WorkerExecutionError: GPU转发失败或返回非2xx状态码
        """
        request_id = request.headers.get('x-fc-request-id', 'unknown')

        # 检查GPU URL配置
        if not self._gpu_function_url:
            log("ERROR", f"[TaskManager][RequestId={request_id}] GPU_FUNCTION_URL not configured")
            raise ConfigurationError("GPU_FUNCTION_URL not configured for CPU mode")
        
        # 提取任务ID
        try:
            task_id = self._extract_task_id_from_request()
        except ValueError as e:
            log("ERROR", f"[TaskManager][RequestId={request_id}] {str(e)}")
            raise InvalidRequestError(str(e), error_code="missing_task_id")

        # 构造GPU URL和headers
        gpu_url = f"{self._gpu_function_url.rstrip('/')}/api/serverless/run"
        
        forward_headers = {
            'x-fc-request-id': task_id,  
            'x-fc-trace-id': task_id,    
        }
        
        # 复制客户端的其他 headers
        # 跳过我们已经设置的 headers，避免被覆盖
        # 透传host会导致请求在cpu函数上循环调用，透传content-length会导致下游读取payload截断
        skip_headers = {'x-fc-request-id', 'x-fc-trace-id', 'host', 'content-length'}
        for k, v in request.headers.items():
            if k.lower() not in skip_headers:
                forward_headers[k] = v
        
        # 转发请求到GPU（同步调用，等待GPU处理完成）
        try:
            log("INFO", f"[TaskManager][TaskId={task_id}][RequestId={request_id}] Forwarding sync request to GPU")
            resp = requests.post(
                gpu_url,
                json=request_body,
                headers=forward_headers,
                params=request.args,
                timeout=600
            )
        except Exception as e:
            # 处理网络错误、超时等
            error_msg = f"Failed to send sync request to GPU: {str(e)}"
            log("ERROR", f"[TaskManager][TaskId={task_id}][RequestId={request_id}] {error_msg}\nStacktrace:\n{traceback.format_exc()}")
            raise WorkerExecutionError(error_msg, error_code="worker_forward_error")
        
        # 检查响应状态码
        if resp.status_code == 200:
            log("INFO", f"[TaskManager][TaskId={task_id}][RequestId={request_id}] Sync request completed successfully")
            return resp.json(), 200
        else:
            error_msg = f"Worker returned HTTP {resp.status_code}"
            log("ERROR", f"[TaskManager][TaskId={task_id}][RequestId={request_id}] Sync request failed: {error_msg}")
            
            # 尝试获取 Worker 的错误响应
            try:
                original_response = resp.json()
            except Exception:
                # Worker 返回的不是 JSON（可能是 HTML 错误页等）
                original_response = None
            
            raise WorkerExecutionError(
                error_msg,
                status_code=resp.status_code,
                original_response=original_response
            )

    @staticmethod
    def _extract_task_id_from_request() -> str:
        """
        从请求头中提取任务ID

        Returns:
            str: task_id

        Raises:
            ValueError: 如果所有header中都没有找到task_id
        """
        async_task_id = request.headers.get('x-fc-async-task-id')
        if async_task_id:
            log("DEBUG", f"[TaskManager] Extracted task_id from x-fc-async-task-id: {async_task_id}")
            return async_task_id
        
        fc_request_id = request.headers.get('x-fc-request-id')
        if fc_request_id:
            log("DEBUG", f"[TaskManager] Extracted task_id from x-fc-request-id: {fc_request_id}")
            return fc_request_id
        raise ValueError("Task ID not found in x-fc-async-task-id or x-fc-request-id")


class MessagesPoller:
    """
    任务消息轮询器
    用于定期从存储中轮询工作流执行状态消息
    """
    
    def __init__(self, 
                 task_id: str, 
                 poll_interval: float,
                 message_callback: Callable[[str, dict], None],
                 serverless_service):
        """
        初始化轮询器
        
        Args:
            task_id: 要轮询的任务ID
            poll_interval: 轮询间隔，单位秒
            message_callback: 消息回调函数
            serverless_service: ServerlessApiService 实例
        """
        self.task_id = task_id
        self.poll_interval = poll_interval
        self.message_callback = message_callback
        self.service = serverless_service
        self.is_running = False
        self.thread: Optional[threading.Thread] = None
        self.last_message_count = 0
    
    def start(self):
        """启动轮询线程"""
        if self.is_running:
            log("DEBUG", f"[MessagesPoller] Task {self.task_id} poller is already running")
            return
            
        self.is_running = True
        self.thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.thread.start()
        log("INFO", f"[MessagesPoller] Started messages polling for task {self.task_id}")
    
    def stop(self):
        """停止轮询线程"""
        if not self.is_running:
            return
            
        self.is_running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5.0)
        log("INFO", f"[MessagesPoller] Stopped polling for task {self.task_id}")
    
    def _poll_loop(self):
        """轮询循环逻辑(通过serverless_api接口查询消息)"""
        task_completed = False
        
        while self.is_running and not task_completed:
            try:
                all_messages = self.service.get_status_from_store(self.task_id)
                
                # 只处理新增的消息
                new_messages = all_messages[self.last_message_count:]
                
                if new_messages:
                    for message in new_messages:
                        if self.message_callback:
                            self.message_callback(self.task_id, message)
                        else:
                            log("DEBUG", f"[MessagesPoller] {self.task_id} message: {json.dumps(message, ensure_ascii=False)}")
                        
                        self.last_message_count += 1
                        
                        # 检查是否完成
                        if self._is_message_completed(message):
                            task_completed = True
                            break
            except Exception as e:
                log("ERROR", f"[MessagesPoller] Error polling task {self.task_id}: {e}")
                import traceback
                traceback.print_exc()
            
            # 等待下次轮询
            if not task_completed:
                time.sleep(self.poll_interval)
        
        self.is_running = False
        log("DEBUG", f"[MessagesPoller] Polling stopped for task {self.task_id}, processed {self.last_message_count} messages")
    
    @staticmethod
    def _is_message_completed(message: Union[dict, str]) -> bool:
        """
        检查单个消息是否表示任务完成
        
        Args:
            message: 消息数据（dict 或 JSON 字符串）
        
        Returns:
            True if message indicates task completion, False otherwise
        """
        try:
            message_type = message.get("type", "")
        except Exception as e:
            return False
        
        # 任务完成包括成功和失败两种终态：
        # - serverless_api: 正常完成
        # - error: 各类错误（包括validate prompt失败）
        # - execution_error: ComfyUI执行过程中的错误
        return message_type in ("serverless_api", "error", "execution_error")


# 全局任务管理器实例 - 延迟初始化
_task_manager = None

def get_task_manager() -> TaskManager:
    """获取全局任务管理器实例"""
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
        # 启动任务管理器
        _task_manager.start()
    return _task_manager