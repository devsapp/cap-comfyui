"""
任务管理器 - 核心任务管理功能
使用组合模式集成轮询和广播功能
"""
import json
import threading
import time
import traceback
import uuid
from typing import Dict, Optional, Callable, List, Tuple, Union, Any

import constants
import requests
from flask import request
from utils.logger import log

from .task import TaskStatus, Task
from .utils.task_manager_util import TaskStatusBroadcaster


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

        # 已完成的历史记录
        # {prompt_id: {prompt, outputs, status, meta}}
        self.history = {}
        
        # 已完成任务计数器（COMPLETED + FAILED）
        self._completed_task_count = 0
        
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
                    prompt: dict,
                    client_id: str,
                    task_id: Optional[str] = None,
                    callback: Optional[Callable] = None) -> str:
        if task_id is None:
            task_id = str(uuid.uuid4())
        
        task_request = Task(
            task_id=task_id,
            client_id=client_id,
            prompt=prompt,
            callback=callback
        )
        
        # 检查活跃任务数量
        with self._lock:
            active_tasks = sum(
                1 for task in self._tasks.values()
                if task.status in [TaskStatus.PENDING, TaskStatus.RUNNING]
            )
            
            if active_tasks >= self._max_active_tasks:
                raise RuntimeError(
                    f"Task queue is full. Active tasks: {active_tasks}/{self._max_active_tasks}. "
                    f"Please wait for some tasks to complete before submitting new ones."
                )
            
            self._tasks[task_id] = task_request
        
        # 启动状态轮询(监控GPU函数端的状态)
        self._start_polling(task_id)
        
        # 广播队列状态更新(任务提交后)
        TaskStatusBroadcaster.broadcast_queue_status(self.get_running_task_count)
        
        return task_id
    
    def get_all_tasks(self) -> List[Task]:
        with self._lock:
            return list(self._tasks.values())
    
    def get_running_task_count(self) -> int:
        """获取运行中任务数量(PENDING和RUNNING状态)"""
        with self._lock:
            return sum(
                1 for task in self._tasks.values()
                if task.status in [TaskStatus.PENDING, TaskStatus.RUNNING]
            )

    def get_history(self, max_items=None, offset: int = -1) -> dict[Any, Any]:
        """
        获取历史记录（从 self.history 获取）
        
        Args:
            max_items: 最大返回数量
            offset: 偏移量，-1 表示从末尾开始
            
        Returns:
            dict: 历史记录字典，格式为 {prompt_id: {prompt, outputs, status, meta}}
                  只返回已完成（status.completed == True）的历史记录
        """
        with self._lock:
            # 先过滤出已完成的历史记录
            completed_history = {}
            for prompt_id, history_item in self.history.items():
                status = history_item.get("status", {})
                if status.get("completed", False):
                    completed_history[prompt_id] = history_item
            
            # 应用 offset 和 max_items 限制
            out = {}
            i = 0
            if offset < 0 and max_items is not None:
                offset = len(completed_history) - max_items
            for k in completed_history:
                if i >= offset:
                    out[k] = completed_history[k]
                    if max_items is not None and len(out) >= max_items:
                        break
                i += 1
            return out
    
    def _extract_prompt_id(self, task: Task) -> str:
        """
        从 Task 对象中提取 prompt_id
        
        优先级：
        1. task.final_status_data.data.prompt_id
        2. task.prompt.prompt_id
        3. task.task_id (fallback)
        """
        # 优先从 final_status_data 获取
        if task.final_status_data:
            prompt_id = (task.final_status_data.get("data", {}) or {}).get("prompt_id")
            if prompt_id:
                return prompt_id
        
        # 其次从 prompt 获取
        if isinstance(task.prompt, dict):
            prompt_id = task.prompt.get("prompt_id")
            if prompt_id:
                return prompt_id
        
        # 最后使用 task_id 作为 fallback
        return task.task_id
    
    def clear_queue(self) -> int:
        """
        清空队列：删除 PENDING 任务和所有已完成任务（COMPLETED/FAILED）
        不删除 RUNNING 状态的任务（正在执行）

        Returns:
            int: 清理的任务数量
        """
        cleared_count = 0
        
        with self._lock:
            task_ids_to_remove = []
            completed_count = 0

            for task_id, task in self._tasks.items():
                # 清理 PENDING 和已完成的任务
                if task.status == TaskStatus.PENDING:
                    task_ids_to_remove.append(task_id)
                elif task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                    task_ids_to_remove.append(task_id)
                    completed_count += 1

            # 执行删除
            for task_id in task_ids_to_remove:
                self._tasks.pop(task_id, None)
                cleared_count += 1

            # 更新已完成任务计数器
            if completed_count > 0:
                self._completed_task_count = max(0, self._completed_task_count - completed_count)

        # 广播队列状态更新
        if cleared_count > 0:
            TaskStatusBroadcaster.broadcast_queue_status(self.get_running_task_count)
            log("INFO", f"[TaskManager] Cleared {cleared_count} tasks (including {completed_count} completed)")

        return cleared_count
    
    def cancel_task(self, task_id: str) -> bool:
        # 先停止状态轮询
        self._stop_polling(task_id)
        
        # 取消任务
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            
            task_status = task.status
            
            # 只能取消未开始执行或正在处理的任务
            if task_status not in [TaskStatus.PENDING, TaskStatus.RUNNING]:
                return False
            
            # 从内存中删除
            self._tasks.pop(task_id, None)
            cancelled = True
        
        # 广播队列状态更新
        if cancelled:
            TaskStatusBroadcaster.broadcast_queue_status(self.get_running_task_count)
        
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
                # 单节点任务之行结束
                # {"type": "executed", "data": {"node": "13", "display_node": "13", "output": {"images": [{"filename": "fe_edit_preview.png", "type": "temp"}]}, "prompt_id": "8fabf03e-0030-478b-b61b-8917126479bd"}}
                # {"type": "executed", "data": {"node": "33", "display_node": "33", "output": {"images": [{"filename": "ComfyUI_00462_.png", "subfolder": "", "type": "output"}]}, "prompt_id": "9c1d6ac9-3eb2-497a-b77f-3d2305e575db"}}
                data = message.get("data", {})
                task = self._tasks.get(task_id)
                if not task:
                    return
                
                prompt_id = data.get("prompt_id")
                if not prompt_id:
                    return
                
                # 获取已存在的history item（应该在 execution_start 时已初始化）
                history_item = self.history.get(prompt_id)
                if not history_item:
                    # 如果 history_item 不存在，记录警告并尝试初始化
                    log("WARNING", f"[TaskManager] History item not found for prompt_id {prompt_id} in executed message, initializing now")
                    self._init_history_item(task_id, {"type": "executed", "data": {"prompt_id": prompt_id}})
                    history_item = self.history.get(prompt_id)
                    if not history_item:
                        return

                
                node_id = data.get("node")
                if not node_id:
                    return
                
                # 构造meta
                if "meta" not in history_item:
                    history_item["meta"] = {}
                history_item["meta"][node_id] = {
                    "node_id": node_id,
                    "display_node": data.get("display_node", node_id),
                    "parent_node": None,
                    "real_node_id": node_id
                }
                
                # 构造outputs，从 output.images 中获取图片信息
                output_data = data.get("output", {})
                images = output_data.get("images", [])
                if images:
                    if "outputs" not in history_item:
                        history_item["outputs"] = {}
                    if node_id not in history_item["outputs"]:
                        history_item["outputs"][node_id] = {}
                    if "images" not in history_item["outputs"][node_id]:
                        history_item["outputs"][node_id]["images"] = []
                    
                    # 处理每个图片，确保包含所有必要字段
                    # 追加到现有列表，而不是覆盖（支持同一节点多个图片）
                    for img in images:
                        image_item = {
                            "filename": img.get("filename", ""),
                            "type": img.get("type", "output"),
                            "subfolder": img.get("subfolder", "")  # 始终包含 subfolder 字段，即使为空
                        }
                        # 避免重复添加相同的图片
                        if image_item not in history_item["outputs"][node_id]["images"]:
                            history_item["outputs"][node_id]["images"].append(image_item)
            elif status_type == 'execution_error':
                # 任务失败
                self._update_task_status(task_id, message, TaskStatus.FAILED)
                # 更新 history_item 的 status
                self._update_history_status(message, "error")

            elif status_type == 'status':
                # 忽略纯 status 消息, agent的队列代替comfyui自己的队列
                return
            self._record_task_status(task_id, message)
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
            data = message.get("data", {})
            prompt_id = data.get("prompt_id")
            if not prompt_id:
                # 如果没有 prompt_id，尝试从 task 中获取
                with self._lock:
                    task = self._tasks.get(task_id)
                    if task:
                        prompt_id = self._extract_prompt_id(task)
            
            if not prompt_id:
                log("WARNING", f"[TaskManager] Cannot initialize history_item: no prompt_id found for task {task_id}")
                return
            
            # 如果已存在，不重复初始化
            if prompt_id in self.history:
                return
            
            # 获取任务信息
            with self._lock:
                task = self._tasks.get(task_id)
                if not task:
                    log("WARNING", f"[TaskManager] Cannot initialize history_item: task {task_id} not found")
                    return
            
            # 提取 prompt 节点定义和 outputs_to_execute
            outputs_to_execute = []
            prompt_dict = task.prompt or {}
            
            # 处理 task.prompt 可能是不同格式的情况
            if isinstance(prompt_dict, dict):
                # 情况1: prompt 是包含 prompt 字段的对象，如 {prompt: {...}, outputs_to_execute: [...]}
                if "prompt" in prompt_dict and isinstance(prompt_dict.get("prompt"), dict):
                    outputs_to_execute = prompt_dict.get("outputs_to_execute", [])
                    prompt_dict = prompt_dict["prompt"]
                # 情况2: prompt 本身就是节点定义的字典（最常见的情况）
                # 这种情况下 outputs_to_execute 通常为空，由 ComfyUI 自动推断
            
            # 构造 extra_data，参考示例结构
            extra_data = {}
            if task.client_id:
                extra_data["client_id"] = task.client_id
            # extra_pnginfo 通常包含 workflow 信息，如果有的话也添加
            # 注意：extra_pnginfo 通常在保存图片时才有，执行时可能没有
            
            # 计算序号：使用历史记录数量 + 1
            # 注意：这个序号应该在整个历史记录中唯一且递增
            sequence_number = len(self.history) + 1
            
            # 提取时间戳
            msg_data = message.get("data", {})
            timestamp = msg_data.get("timestamp")
            if timestamp is None:
                timestamp = int(time.time() * 1000)
            else:
                # 标准化时间戳为毫秒
                if timestamp < 10000000000:
                    timestamp = int(timestamp * 1000)
                else:
                    timestamp = int(timestamp)
            
            # 构造 prompt 数组，格式：[number, prompt_id, prompt_dict, extra_data, outputs_to_execute]
            history_item = {
                "meta": {},
                "outputs": {},
                "prompt": [
                    sequence_number,
                    prompt_id,
                    prompt_dict,
                    extra_data,
                    outputs_to_execute
                ],
                "status": {
                    "status_str": "running",
                    "completed": False,
                    "messages": [
                        ["execution_start", {"prompt_id": prompt_id, "timestamp": timestamp}]
                    ]
                }
            }
            
            with self._lock:
                self.history[prompt_id] = history_item
            
            log("DEBUG", f"[TaskManager] Initialized history_item for prompt_id {prompt_id}")
            
        except Exception as e:
            log("ERROR", f"[TaskManager] Error initializing history_item for task {task_id}: {e}\n{traceback.format_exc()}")
    
    def _update_history_status(self, message: dict, status_str: str) -> None:
        """
        更新 history_item 的 status
        
        Args:
            message: 消息数据（execution_success、execution_error、execution_cached）
            status_str: 状态字符串（"success"、"error"、"running"）
        """
        try:
            data = message.get("data", {})
            prompt_id = data.get("prompt_id")
            if not prompt_id:
                return
            
            with self._lock:
                history_item = self.history.get(prompt_id)
                if not history_item:
                    log("WARNING", f"[TaskManager] Cannot update history status: history_item not found for prompt_id {prompt_id}")
                    return
                
                if "status" not in history_item:
                    history_item["status"] = {
                        "status_str": status_str,
                        "completed": False,
                        "messages": []
                    }
                
                status = history_item["status"]
                
                # 提取时间戳
                timestamp = data.get("timestamp")
                if timestamp is None:
                    timestamp = int(time.time() * 1000)
                else:
                    # 标准化时间戳为毫秒
                    if timestamp < 10000000000:
                        timestamp = int(timestamp * 1000)
                    else:
                        timestamp = int(timestamp)
                
                # 更新状态
                status["status_str"] = status_str
                
                # 根据状态类型添加消息
                if status_str == "success":
                    status["completed"] = True
                    # 添加 execution_success 消息（如果还没有）
                    if not any(msg[0] == "execution_success" for msg in status.get("messages", [])):
                        status.setdefault("messages", []).append(
                            ["execution_success", {"prompt_id": prompt_id, "timestamp": timestamp}]
                        )
                elif status_str == "error":
                    status["completed"] = True
                    # 添加 execution_error 消息（如果还没有）
                    if not any(msg[0] == "execution_error" for msg in status.get("messages", [])):
                        error_info = {
                            "prompt_id": prompt_id,
                            "node_id": data.get("node_id") or data.get("node", "unknown"),
                            "exception_message": data.get("exception_message", "Unknown error"),
                            "timestamp": timestamp
                        }
                        status.setdefault("messages", []).append(["execution_error", error_info])
                elif status_str == "running":
                    # execution_cached 或其他运行中状态，不改变 completed 标志
                    # 可以添加 execution_cached 消息
                    if message.get("type") == "execution_cached":
                        if not any(msg[0] == "execution_cached" for msg in status.get("messages", [])):
                            status.setdefault("messages", []).append(
                                ["execution_cached", {"prompt_id": prompt_id, "timestamp": timestamp}]
                            )
                
        except Exception as e:
            log("ERROR", f"[TaskManager] Error updating history status: {e}\n{traceback.format_exc()}")
    
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
            # 先记录状态历史
            self._record_task_status(task_id, status_data)
            
            # 执行原子更新
            with self._lock:
                task = self._tasks.get(task_id)
                if not task:
                    log("WARNING", f"[TaskManager] Task {task_id} not found in queue (status update ignored)")
                    return False
                
                if task.status == target_status:
                    return False
                
                success = task.update_status(target_status)

            if success and target_status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                # 增加已完成任务计数
                with self._lock:
                    self._completed_task_count += 1
                # 检查是否需要清理旧任务
                self._cleanup_old_completed_tasks_if_needed()
            TaskStatusBroadcaster.broadcast_queue_status(self.get_running_task_count)
            
            return success
        
        except Exception as e:
            log("ERROR", f"[TaskManager] Error updating status for task {task_id}: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _record_task_status(self, task_id: str, status_data: dict) -> bool:
        """
        记录任务状态到任务对象(用于 history 构造)
        
        Args:
            task_id: 任务ID
            status_data: 状态数据
            
        Returns:
            bool: 是否成功记录
        """
        try:
            with self._lock:
                task = self._tasks.get(task_id)
                if not task:
                    return False

                # 只存储 history 需要的消息类型
                s_type = status_data.get("type")
                if s_type in ("execution_start", "execution_cached", "serverless_api", "execution_success", "execution_error", "error"):
                    task.status_history.append(status_data)

                if s_type == "serverless_api":
                    task.final_status_data = status_data
                    data = status_data.get("data", {})
                    task.results = data.get("results")
                elif s_type in ("error", "execution_error"):
                    task.final_status_data = status_data
                
                return True
        except Exception as e:
            log("ERROR", f"[TaskManager] Error recording status for task {task_id}: {e}")
            return False

    # FIXME:@dehui.kdh, 实现更优雅的清理逻辑
    def _cleanup_old_completed_tasks_if_needed(self) -> None:
        """检查是否需要清理旧的已完成任务（基于计数器，只在超过阈值时才执行清理）"""
        # 使用计数器快速判断是否需要清理
        if self._completed_task_count <= self._max_completed_tasks:
            return
        
        try:
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
                
                # 删除旧任务
                removed_count = 0
                for task_id, _ in tasks_to_remove:
                    if self._tasks.pop(task_id, None):
                        removed_count += 1
                
                # 更新计数器
                self._completed_task_count = len(completed_tasks) - removed_count
                
                if removed_count > 0:
                    log("INFO", f"[TaskManager] Cleaned up {removed_count} old completed tasks (keeping latest {self._max_completed_tasks}, current count: {self._completed_task_count})")
        
        except Exception as e:
            log("ERROR", f"[TaskManager] Error cleaning up old completed tasks: {e}")
            import traceback
            traceback.print_exc()
    
    # ==================== GPU 转发方法 ====================
    
    def forward_to_gpu_async(self, 
                             prompt: dict, 
                             client_id: str) -> Tuple[Optional[str], Union[object, Tuple[int, str, str]]]:
        """
        GPU异步转发逻辑
        
        Args:
            prompt: 工作流定义
            client_id: 客户端ID(用于WebSocket广播)
            
        Returns:
            tuple: (task_id, response_or_error)
                   - task_id: 成功时返回任务ID，失败时返回None
                   - response_or_error: 成功时返回response对象，失败时返回(status_code, error_type, error_message)
        """
        request_id = request.headers.get('x-fc-request-id', 'unknown')

        # 检查GPU URL配置
        if not self._gpu_function_url:
            log("ERROR", f"[TaskManager][RequestId={request_id}] GPU_FUNCTION_URL not configured")
            return None, (500, "configuration_error", "GPU_FUNCTION_URL not configured for CPU mode")
        
        # 提取任务ID(如果找不到会抛出异常)
        try:
            task_id = self._extract_task_id_from_request()
        except ValueError as e:
            log("ERROR", f"[TaskManager][RequestId={request_id}] {str(e)}")
            return None, (500, "missing_task_id", str(e))

        # 将任务添加到管理器(用于跟踪和状态管理)
        try:
            self.submit_task(
                prompt=prompt,
                client_id=client_id,
                task_id=task_id
            )
        except Exception as e:
            error_msg = f"Failed to add task to queue: {e}"
            log("ERROR", f"[TaskManager][TaskId={task_id}][RequestId={request_id}] {error_msg}\n{traceback.format_exc()}")
            return None, (500, "queue_error", error_msg)
        
        # 构造GPU URL和headers
        gpu_url = f"{self._gpu_function_url.rstrip('/')}/api/serverless/run"
        
        forward_headers = {
            'x-fc-async-task-id': task_id,  # 优先使用这个作为 task_id
            'x-fc-trace-id': task_id,       # GPU的request-id与task-id一致
            'x-fc-invocation-type': 'Async' # 异步调用
        }
        
        # 复制其他 headers
        excluded_headers_lower = {'host', 'content-length', 'x-fc-async-task-id', 'x-fc-request-id'}
        for k, v in request.headers.items():
            k_lower = k.lower()
            if k_lower not in excluded_headers_lower:
                forward_headers[k] = v
        # 转发请求到GPU
        try:
            resp = requests.post(
                gpu_url,
                json=prompt,
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
            
            return None, (500, "gpu_forward_error", error_msg)
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

        # 返回response和task_id
        if resp.status_code == 202:
            return task_id, resp
        else:
            return None, (500, "async_invocation_error", f"Failed to invoke GPU function asynchronously: HTTP {resp.status_code}")

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
            log("DEBUG", f"[MessagesPoller] Error checking message completion: {e}")
            return False
        
        # 只有收到 serverless_api 时才认为任务完成
        # execution_success 和 execution_error 只是中间状态，需要等待 serverless_api
        return message_type == "serverless_api"


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