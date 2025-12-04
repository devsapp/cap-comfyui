"""
GPU Forwarder
处理向GPU函数转发请求的逻辑
"""
import json
import time
import traceback

import requests
from flask import request, jsonify, Response

import constants
from utils.logger import log


class GpuForwarder:
    """处理向GPU函数转发请求"""
    
    def __init__(self, gpu_function_url, task_queue):
        self.gpu_function_url = gpu_function_url
        self.task_queue = task_queue
    
    def _get_request_id(self) -> str:
        """
        从请求头中获取 requestId（用于早期日志追踪）
        
        Returns:
            str: requestId，如果不存在则返回 "unknown"
        """
        return request.headers.get('x-fc-request-id', 'unknown')
    
    def _extract_task_id(self, task_id_headers: list) -> tuple:
        """
        从请求头中提取任务ID
        
        Args:
            task_id_headers
            
        Returns:
            tuple: (task_id, task_id_source)
            
        Raises:
            ValueError: 如果所有header中都没有找到task_id
        """
        async_task_id = request.headers.get('x-fc-async-task-id')
        if async_task_id:
            log("DEBUG", f"[GpuForwarder] Extracted task_id from x-fc-async-task-id: {async_task_id}")
            return async_task_id, "x-fc-async-task-id"
        
        fc_request_id = request.headers.get('x-fc-request-id')
        if fc_request_id:
            log("DEBUG", f"[GpuForwarder] Extracted task_id from x-fc-request-id: {fc_request_id}")
            return fc_request_id, "x-fc-request-id"
        raise ValueError("Task ID not found in x-fc-async-task-id or x-fc-request-id")
    
    def forward_async(self, 
                      api_type: str,
                      prompt: dict, 
                      client_id: str,
                      task_id_headers: list,
                      forward_by_name: str):
        """
        GPU异步转发逻辑
        
        Args:
            api_type: API类型 ('prompt' 需要WebSocket广播, 'serverless' 不需要)
            prompt: 工作流定义
            client_id: 客户端ID（仅用于 'prompt' 类型的WebSocket广播）
            task_id_headers: 优先检查的header列表
            forward_by_name: 转发来源名称
            
        Returns:
            tuple: (task_id, response_or_error)
                   - task_id: 成功时返回任务ID，失败时返回None
                   - response_or_error: 成功时返回response对象，失败时返回(status_code, error_type, error_message)
        """
        req_start = time.time()
        request_id = self._get_request_id()
        task_id = None
        task_added_to_queue = False
        
        try:
            # 检查GPU URL配置
            if not self.gpu_function_url:
                log("ERROR", f"[RequestId={request_id}] GPU_FUNCTION_URL not configured")
                return None, (500, "configuration_error", "GPU_FUNCTION_URL not configured for CPU mode")
            
            # 提取任务ID（如果找不到会抛出异常）
            try:
                task_id, _ = self._extract_task_id(task_id_headers)
            except ValueError as e:
                log("ERROR", f"[RequestId={request_id}] {str(e)}")
                return None, (500, "missing_task_id", str(e))
            
            log("INFO", f"[TaskLifecycle][{task_id}][RECEIVED] Task received (api_type={api_type}, client_id={client_id}, forward_by={forward_by_name})")
            
            # 将任务添加到队列（用于跟踪和状态管理）
            # 如果添加到队列失败，不继续转发给GPU，避免状态不一致
            try:
                t_submit_start = time.time()
                submitted_task_id = self.task_queue.submit_task(
                    prompt=prompt,
                    client_id=client_id,
                    task_id=task_id
                )
                submit_time = (time.time() - t_submit_start) * 1000
                                
                # 只有 prompt 类型的请求需要关联 client_id 用于 WebSocket 广播
                if api_type == "prompt" and client_id:
                    self.task_queue.associate_task_with_client_id(submitted_task_id, client_id)
                
                task_added_to_queue = True
                log("INFO", f"[TaskLifecycle][{task_id}][QUEUED] Task added to queue (submit_time_ms={submit_time:.1f})")
            except Exception as e:
                error_msg = f"Failed to add task to queue: {e}"
                log("ERROR", f"[TaskId={task_id}][RequestId={request_id}] {error_msg}\n{traceback.format_exc()}")
                return None, (500, "queue_error", error_msg)
            
            # 构造GPU URL和headers
            gpu_url = f"{self.gpu_function_url.rstrip('/')}/api/serverless/run"
            
            forward_headers = {
                constants.HEADER_FORWARDED_BY: forward_by_name,
                'x-fc-async-task-id': task_id,  # 优先使用这个作为
                'x-fc-trace-id': task_id,       # 使GPU的request-id与task-id一致
                constants.HEADER_FC_INVOCATION_TYPE: 'Async'
            }
            
            # 复制其他 headers
            excluded_headers_lower = {'host', 'content-length', 'x-fc-async-task-id', 'x-fc-request-id'}
            for k, v in request.headers.items():
                k_lower = k.lower()
                if k_lower not in excluded_headers_lower:
                    forward_headers[k] = v
            
            log("INFO", f"[TaskLifecycle][{task_id}][FORWARDING] Forwarding to GPU function (url={gpu_url}, timeout=30s)")
            
            # 转发请求到GPU
            t_post_start = time.time()
            try:
                resp = requests.post(
                    gpu_url,
                    json=prompt,
                    headers=forward_headers,
                    params=request.args,
                    timeout=30
                )
            except Exception as e:
                log("ERROR", f"[TaskId={task_id}] Failed to send request to GPU: {e}")
                raise
            t_post_cost = (time.time() - t_post_start) * 1000
            total_time = (time.time() - req_start) * 1000
            
            log("INFO", f"[TaskLifecycle][{task_id}][FORWARDED] GPU forward completed (status={resp.status_code}, forward_time_ms={t_post_cost:.1f}, total_time_ms={total_time:.1f})")
            
            # 更新任务状态
            try:
                from services.gateway.queue.task_models import TaskStatus
                
                if resp.status_code == 202:
                    self.task_queue.update_task_status(task_id, TaskStatus.PROCESSING)
                    log("INFO", f"[TaskStatus] Task {task_id} marked as PROCESSING (GPU accepted async request)")
                else:
                    self.task_queue.update_task_status(task_id, TaskStatus.FAILED)
                    log("INFO", f"[TaskStatus] Task {task_id} marked as FAILED (GPU returned status={resp.status_code})")
            except Exception as e:
                log("WARNING", f"[TaskId={task_id}] Failed to update task status: {e}\n{traceback.format_exc()}")
            
            # 返回response和task_id
            if resp.status_code == 202:
                return task_id, resp
            else:
                # FIXME log
                # FIXME 任务提交失败
                return None, (500, "async_invocation_error", f"Failed to invoke GPU function asynchronously: HTTP {resp.status_code}")
                
        except Exception as e:
            is_timeout = isinstance(e, requests.exceptions.Timeout)
            error_msg = f"Failed to forward request to GPU function: {str(e)} (timeout={is_timeout})"
            total_cost = (time.time() - req_start) * 1000 if 'req_start' in locals() else -1
            log("ERROR", f"[TaskId={task_id}][RequestId={request_id}] {error_msg}\nStacktrace:\n{traceback.format_exc()}\nElapsed_ms={total_cost:.1f}")
            
            # 如果任务已添加到队列，需要更新状态为 FAILED
            if task_added_to_queue and task_id:
                try:
                    from services.gateway.queue.task_models import TaskStatus
                    self.task_queue.update_task_status(task_id, TaskStatus.FAILED)
                    log("INFO", f"[TaskStatus] Task {task_id} marked as FAILED due to forward error (error_type={type(e).__name__}, timeout={is_timeout})")
                except Exception as status_error:
                    log("WARNING", f"[TaskId={task_id}] Failed to update task status to FAILED: {status_error}")
            
            return None, (500, "gpu_forward_error", error_msg)
    
    def forward_sync(self, request_body: dict):
        """
        GPU同步转发逻辑
        
        Args:
            request_body: 请求体（ComfyUI工作流定义）
            
        Returns:
            Flask response
        """
        req_start = time.time()
        request_id = self._get_request_id()
        task_id = None
        
        log("DEBUG", f"[RequestId={request_id}] Processing sync serverless/run request - ENTER")
        
        try:
            if not self.gpu_function_url:
                log("ERROR", f"[RequestId={request_id}] GPU_FUNCTION_URL not configured")
                return jsonify({
                    "type": "error",
                    "error_code": "configuration_error",
                    "error_message": "GPU_FUNCTION_URL not configured for CPU mode"
                }), 500
            
            # 查询参数会通过 params=request.args 原样转发给 GPU 函数
            log("DEBUG", f"[RequestId={request_id}] Request params: {dict(request.args)}")
            
            # 构造 GPU 函数的完整 URL
            gpu_url = f"{self.gpu_function_url.rstrip('/')}/api/serverless/run"
            
            # 转发请求头（同步调用）
            forward_headers = {
                k: v for k, v in request.headers.items()
                if k.lower() not in ['host', 'content-length']
            }
            forward_headers[constants.HEADER_FORWARDED_BY] = 'CPU-Router-Sync'
            
            # 提取 task_id（如果找不到会抛出异常）
            task_id_headers = ["x-fc-async-task-id", "x-fc-request-id"]
            try:
                task_id, task_id_source = self._extract_task_id(task_id_headers)
            except ValueError as e:
                log("ERROR", f"[RequestId={request_id}] {str(e)}")
                return jsonify({
                    "type": "error",
                    "error_code": "missing_task_id",
                    "error_message": str(e)
                }), 400
            
            log("DEBUG", f"[TaskId={task_id}][RequestId={request_id}] Sync forwarding to GPU: url={gpu_url} (from {task_id_source})")
            
            # 生命周期日志
            log("INFO", f"[TaskLifecycle][{task_id}][SYNC_FORWARDING] Synchronously forwarding to GPU, url={gpu_url}")
            
            # 同步转发请求到 GPU 函数
            t_post_start = time.time()
            resp = requests.post(
                gpu_url,
                json=request_body,
                headers=forward_headers,
                params=request.args,
                timeout=300  # 同步调用设置较长超时时间（5分钟）
            )
            t_post_cost = (time.time() - t_post_start) * 1000
            
            log("DEBUG", f"[TaskId={task_id}][RequestId={request_id}] GPU sync response received: "
                  f"status={resp.status_code}, cost_ms={t_post_cost:.1f}, resp_len={len(resp.content)}")
            
            # 生命周期日志
            log("INFO", f"[TaskLifecycle][{task_id}][SYNC_COMPLETED] Sync call completed, "
                  f"status={resp.status_code}, total_time_ms={t_post_cost:.1f}")
            
            total_cost = (time.time() - req_start) * 1000
            log("DEBUG", f"[TaskId={task_id}][RequestId={request_id}] RETURN to client: status={resp.status_code}, total_cost_ms={total_cost:.1f}")
            
            # 直接返回 GPU 函数的响应
            try:
                response_data = resp.json()
                return jsonify(response_data), resp.status_code
            except (ValueError, json.JSONDecodeError):
                # 如果响应不是 JSON，直接返回原始内容
                return Response(
                    resp.content,
                    status=resp.status_code,
                    content_type=resp.headers.get('Content-Type', 'application/octet-stream')
                )
        
        except requests.exceptions.Timeout:
            total_cost = (time.time() - req_start) * 1000
            error_msg = f"GPU function request timed out after {total_cost:.1f}ms"
            task_id_str = f"TaskId={task_id}" if task_id else "TaskId=unknown"
            log("ERROR", f"[{task_id_str}][RequestId={request_id}] {error_msg}")
            
            return jsonify({
                "type": "error",
                "error_code": "timeout_error",
                "error_message": error_msg
            }), 504
        
        except Exception as e:
            total_cost = (time.time() - req_start) * 1000 if 'req_start' in locals() else -1
            error_msg = f"Failed to forward sync request to GPU function: {str(e)}"
            task_id_str = f"TaskId={task_id}" if task_id else "TaskId=unknown"
            log("ERROR", f"[{task_id_str}][RequestId={request_id}] {error_msg}\nStacktrace:\n{traceback.format_exc()}\nElapsed_ms={total_cost:.1f}")
            
            return jsonify({
                "type": "error",
                "error_code": "gpu_forward_error",
                "error_message": error_msg
            }), 500

