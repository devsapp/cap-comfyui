"""
CPU Gateway Service
处理 CPU 函数作为网关转发请求到 GPU 函数的逻辑
"""
import json
import time
import requests
from datetime import datetime
from flask import request, jsonify, Response

import constants
from utils.logger import log


class CpuGatewayService:
    """CPU函数网关服务，负责转发请求到GPU函数"""
    
    def __init__(self):
        self.gpu_function_url = constants.GPU_FUNCTION_URL
        # 获取任务队列单例
        from services.gateway import get_task_queue
        self.task_queue = get_task_queue()
    
    def handle_queue_get_request(self):
        """
        处理 GET /api/queue 请求 获取队列状态
        
        Returns:
            Flask response
        """
        import time as queue_time
        import threading
        import queue as thread_queue
        from services.gateway.queue.task_models import TaskStatus
        
        request_start = queue_time.time()
        
        log("DEBUG", f"Handling GET /api/queue request with timeout protection")
        
        try:
            # 超时保护：如果获取任务列表超过1秒，返回空队列
            result_queue = thread_queue.Queue()
            exception_queue = thread_queue.Queue()
            
            def fetch_tasks_with_timeout():
                try:
                    # 获取任务列表
                    all_tasks = self.task_queue.get_all_tasks()
                    result_queue.put(all_tasks)
                except Exception as e:
                    exception_queue.put(e)
            
            fetch_thread = threading.Thread(target=fetch_tasks_with_timeout, daemon=True)
            fetch_thread.start()
            fetch_thread.join(timeout=1.0)  # 1秒超时
            
            if not exception_queue.empty():
                raise exception_queue.get()
            
            if result_queue.empty():
                log("WARNING", f"Queue request timed out after 1 second, returning empty queue")
                return jsonify({
                    "queue_running": [],
                    "queue_pending": [],
                    "_warning": "Request timed out, showing empty queue to prevent blocking"
                })
            
            all_tasks = result_queue.get()
            fetch_time = queue_time.time() - request_start
            
        except Exception as e:
            log("ERROR", f"Error fetching tasks for queue request: {e}")
            return jsonify({
                "queue_running": [],
                "queue_pending": [],
                "_error": "Failed to fetch queue status"
            })
        
        comfyui_queue_info = {
            "queue_running": [],  # 正在运行的任务列表
            "queue_pending": []   # 等待中的任务列表
        }
        
        convert_start = queue_time.time()
        
        for task in all_tasks:
            # 超时保护：如果处理时间过长，停止处理
            if queue_time.time() - request_start > 2.0:  # 总处理超过2秒
                log("WARNING", f"Queue processing timeout, stopping after {queue_time.time() - request_start:.2f}s")
                comfyui_queue_info["_truncated"] = True
                break
            
            # 根据任务状态分类
            if task.status == TaskStatus.PROCESSING:
                # 构造ComfyUI兼容的任务信息格式（简化版）
                task_info = [
                    1,  # number - 任务优先级
                    task.task_id,  # prompt_id
                    task.prompt or {},  # prompt - 避免None导致序列化失败
                    {"client_id": task.client_id} if task.client_id else {},  # extra_data
                    []  # outputs_to_execute
                ]
                comfyui_queue_info["queue_running"].append(task_info)
                
            elif task.status in [TaskStatus.PENDING, TaskStatus.SUBMITTED]:
                task_info = [
                    1,  # number - 任务优先级
                    task.task_id,  # prompt_id
                    task.prompt or {},  # prompt - 避免None导致序列化失败
                    {"client_id": task.client_id} if task.client_id else {},  # extra_data
                    []  # outputs_to_execute
                ]
                comfyui_queue_info["queue_pending"].append(task_info)
        
        total_time = queue_time.time() - request_start
        convert_time = queue_time.time() - convert_start
        
        log("DEBUG", f"Queue status: {len(comfyui_queue_info['queue_running'])} running, "
              f"{len(comfyui_queue_info['queue_pending'])} pending "
              f"(fetch: {fetch_time:.2f}s, convert: {convert_time:.2f}s, total: {total_time:.2f}s)")
        
        return jsonify(comfyui_queue_info)
    
    def handle_queue_post_request(self):
        """
        处理 POST /api/queue 请求
        队列管理（清空/删除任务）
        
        Returns:
            Flask response
        """
        log("DEBUG", f"Handling POST /api/queue request")
        
        request_data = request.get_json() or {}
        
        if "clear" in request_data and request_data["clear"]:
            # 清空队列
            log("INFO", f"Clearing task queue")
            
            cleared_count = self.task_queue.clear_queue()
            log("INFO", f"Cleared {cleared_count} tasks from queue")
            
            return Response(status=200)
        
        elif "delete" in request_data:
            # 删除指定任务
            # 注意：由于函数计算异步调用无法真正取消已在GPU执行的任务，
            # 这里只能删除 PENDING/SUBMITTED 状态的任务，
            # PROCESSING 状态的任务无法取消，会继续执行直到完成。
            to_delete = request_data.get("delete", [])
            log("INFO", f"Deleting tasks: {to_delete}")
            
            deleted_count = 0
            failed_tasks = []
            for task_id in to_delete:
                cancel_result = self.task_queue.cancel_task(task_id)
                if cancel_result:
                    deleted_count += 1
                    log("DEBUG", f"Deleted task: {task_id}")
                else:
                    failed_tasks.append(task_id)
                    log("WARNING", f"Failed to delete task (not found or already running): {task_id}")
            
            log("INFO", f"Deleted {deleted_count} tasks from queue")
            
            if failed_tasks:
                log("WARNING", f"{len(failed_tasks)} tasks could not be cancelled (already running on GPU): {failed_tasks}")
            
            return Response(status=200)
        
        else:
            # 无效的队列操作请求
            return jsonify({
                "error": {
                    "type": "invalid_request_error",
                    "message": "Invalid queue operation. Supported operations: clear, delete"
                }
            }), 400
    
    def _forward_to_gpu_async(self, 
                               api_type: str,
                               prompt: dict, 
                               client_id: str,
                               task_id_prefix: str,
                               task_id_headers: list,
                               forward_by_name: str,
                               trace_prefix: str):
        """
        通用的GPU异步转发逻辑
        
        Args:
            api_type: API类型 ('prompt' 或 'serverless')
            prompt: 工作流定义
            client_id: 客户端ID
            task_id_prefix: 任务ID前缀 ('prompt_' 或 'serverless_')
            task_id_headers: 优先检查的header列表
            forward_by_name: 转发来源名称
            trace_prefix: trace ID前缀
            
        Returns:
            tuple: (task_id, response_or_error)
                   - task_id: 成功时返回任务ID，失败时返回None
                   - response_or_error: 成功时返回response对象，失败时返回(jsonify(...), status_code)
        """
        import time as _ts
        trace_id = f"{trace_prefix}_{int(_ts.time()*1000)}"
        req_start = _ts.time()
        
        try:
            # 检查GPU URL配置
            if not self.gpu_function_url:
                log("ERROR", f"[{trace_prefix}][{trace_id}] GPU_FUNCTION_URL not configured")
                return None, (500, "configuration_error", "GPU_FUNCTION_URL not configured for CPU mode")
            
            # 生成任务ID
            task_id = None
            task_id_source = "generated"
            
            for header_name in task_id_headers:
                header_value = request.headers.get(header_name)
                if header_value:
                    task_id = header_value
                    task_id_source = header_name
                    break
            
            if not task_id:
                task_id = f"{task_id_prefix}{constants.INSTANCE_ID}_{int(_ts.time() * 1000)}"
            
            log("DEBUG", f"[{trace_prefix}][{trace_id}] Generated task_id: {task_id} from {task_id_source}, client_id={client_id}")
            
            # 生命周期日志：接收任务
            nodes_count = len(prompt) if isinstance(prompt, dict) else 'unknown'
            log("INFO", f"[TaskLifecycle][{task_id}][RECEIVED] Task received, client_id={client_id}, nodes={nodes_count}")
            
            # 将任务添加到队列（仅用于跟踪）
            try:
                output_base64 = request.args.get("output_base64", "false").lower() == "true"
                output_oss = request.args.get("output_oss", "false").lower() == "true"
                
                t_submit_start = _ts.time()
                submitted_task_id = self.task_queue.submit_task(
                    prompt=prompt,
                    client_id=client_id,
                    task_id=task_id,
                    output_base64=output_base64,
                    output_oss=output_oss
                )
                
                log("DEBUG", f"[{trace_prefix}][{trace_id}] Task {submitted_task_id} added to queue (enqueue_cost_ms={(_ts.time()-t_submit_start)*1000:.1f})")
                log("INFO", f"[TaskLifecycle][{task_id}][QUEUED] Task queued, enqueue_time_ms={(_ts.time()-t_submit_start)*1000:.1f}")
                
                if client_id:
                    self.task_queue.associate_task_with_client_id(submitted_task_id, client_id)
            except Exception as e:
                import traceback as _tb
                log("WARNING", f"[{trace_prefix}][{trace_id}] Failed to add task to queue: {e}\n{_tb.format_exc()}")
            
            # 构造GPU URL和headers
            gpu_url = f"{self.gpu_function_url.rstrip('/')}/api/serverless/run"
            
            forward_headers = {
                k: v for k, v in request.headers.items()
                if k.lower() not in ['host', 'content-length']
            }
            forward_headers['X-Forwarded-By'] = forward_by_name
            forward_headers['X-Task-ID'] = task_id
            forward_headers['x-fc-async-task-id'] = task_id
            forward_headers['x-fc-request-id'] = task_id
            forward_headers['x-fc-trace-id'] = task_id
            forward_headers['x-fc-invocation-type'] = 'Async'
            
            log("DEBUG", f"[{trace_prefix}][{trace_id}] Async forwarding to GPU: url={gpu_url}, task_id={task_id}")
            log("INFO", f"[TaskLifecycle][{task_id}][FORWARDING] Forwarding to GPU function")
            
            # 转发请求到GPU
            t_post_start = _ts.time()
            resp = requests.post(
                gpu_url,
                json=prompt,
                headers=forward_headers,
                params=request.args,
                timeout=30
            )
            t_post_cost = (_ts.time() - t_post_start) * 1000
            
            log("DEBUG", f"[{trace_prefix}][{trace_id}] GPU responded: status={resp.status_code}, cost_ms={t_post_cost:.1f}")
            log("INFO", f"[TaskLifecycle][{task_id}][FORWARDED] GPU forward completed, status={resp.status_code}, forward_time_ms={t_post_cost:.1f}")
            
            # 更新任务状态
            try:
                from services.gateway.queue.task_models import TaskStatus
                
                if resp.status_code == 202:
                    self.task_queue.update_task_status(task_id, TaskStatus.PROCESSING)
                    log("DEBUG", f"[{trace_prefix}] Task {task_id} marked as processing")
                else:
                    self.task_queue.update_task_status(task_id, TaskStatus.FAILED)
                    log("WARNING", f"[{trace_prefix}] Task {task_id} marked as failed")
            except Exception as e:
                import traceback as _tb
                log("WARNING", f"[{trace_prefix}][{trace_id}] Failed to update task status: {e}\n{_tb.format_exc()}")
            
            total_cost = (_ts.time() - req_start) * 1000
            log("DEBUG", f"[{trace_prefix}][{trace_id}] Total cost: {total_cost:.1f}ms")
            
            # 返回response和task_id
            if resp.status_code == 202:
                return task_id, resp
            else:
                return None, (500, "async_invocation_error", f"Failed to invoke GPU function asynchronously: HTTP {resp.status_code}")
                
        except Exception as e:
            import traceback
            import requests as _rq
            is_timeout = isinstance(e, _rq.exceptions.Timeout)
            error_msg = f"Failed to forward request to GPU function: {str(e)} (timeout={is_timeout})"
            total_cost = (_ts.time() - req_start) * 1000 if 'req_start' in locals() else -1
            log("ERROR", f"[{trace_prefix}][{trace_id}] {error_msg}\nStacktrace:\n{traceback.format_exc()}\nElapsed_ms={total_cost:.1f}")
            return None, (500, "gpu_forward_error", error_msg)
    
    def handle_prompt_request_async(self):
        """
        处理 POST /api/prompt 请求（异步转发到GPU函数）
        
        Returns:
            tuple: (response_data, status_code)
        """
        # 获取请求数据
        request_data = request.get_json()
        if not request_data:
            return jsonify({
                "error": {
                    "type": "invalid_request_error",
                    "message": "Request body must be valid JSON"
                }
            }), 400
        
        # 提取 prompt 数据和 client_id
        prompt = request_data.get("prompt")
        client_id = request_data.get("client_id", "")
        
        if not prompt:
            return jsonify({
                "error": {
                    "type": "invalid_request_error", 
                    "message": "Missing 'prompt' in request body"
                }
            }), 400
        
        # 调用通用转发逻辑
        task_id, result = self._forward_to_gpu_async(
            api_type="prompt",
            prompt=prompt,
            client_id=client_id,
            task_id_prefix="prompt_",
            task_id_headers=["x-fc-async-task-id", "x-fc-request-id"],
            forward_by_name="CPU-Router-Async",
            trace_prefix="cpu_prompt"
        )
        
        # 处理结果
        if task_id:
            # 成功：返回ComfyUI格式
            return jsonify({
                "prompt_id": task_id,
                "number": 1,
                "node_errors": {}
            })
        else:
            # 失败：result 是 (status_code, error_type, error_message)
            status_code, error_type, error_message = result
            return jsonify({
                "error": {
                    "type": error_type,
                    "message": error_message
                }
            }), status_code
    
    def handle_serverless_run_async(self):
        """
        处理 POST /api/serverless/run 请求（异步转发到GPU函数）
        
        Returns:
            tuple: (response_data, status_code)
        """
        # 获取请求数据 - /serverless/run 的请求体直接是 prompt
        prompt = request.get_json(force=True, silent=True)
        if prompt is None:
            return jsonify({
                "type": "error",
                "error_code": "invalid_request_error",
                "error_message": "Request body must be valid JSON containing ComfyUI workflow definition"
            }), 400
        
        # 检查 prompt 是否为空
        if not isinstance(prompt, dict) or len(prompt) == 0:
            return jsonify({
                "type": "error",
                "error_code": "invalid_request_error",
                "error_message": "Prompt (workflow definition) cannot be empty. Please provide a valid ComfyUI workflow."
            }), 400
        
        # serverless API 不需要 client_id，GPU 端会从 WebSocket 自动获取
        client_id = ""
        
        # 调用通用转发逻辑
        task_id, result = self._forward_to_gpu_async(
            api_type="serverless",
            prompt=prompt,
            client_id=client_id,
            task_id_prefix="serverless_",
            task_id_headers=["x-fc-async-task-id", "x-fc-request-id"],
            forward_by_name="CPU-Router-Serverless-Async",
            trace_prefix="cpu_serverless_async"
        )
        
        # 处理结果
        if task_id:
            # 成功：返回Serverless格式
            return jsonify({
                "task_id": task_id,
                "status": "pending"
            }), 202
        else:
            # 失败：result 是 (status_code, error_type, error_message)
            status_code, error_type, error_message = result
            return jsonify({
                "type": "error",
                "error_code": error_type,
                "error_message": error_message
            }), status_code
    
    def handle_serverless_run_sync(self):
        """
        处理 POST /api/serverless/run 请求（同步转发到GPU函数）
        
        与 handle_prompt_request_async 不同:
        - 不使用任务队列
        - 同步等待 GPU 函数返回结果
        - 直接返回结果给客户端
        
        Returns:
            response: GPU函数的响应
        """
        import time as _ts
        import requests
        
        trace_id = f"cpu_serverless_sync_{int(_ts.time()*1000)}"
        req_start = _ts.time()
        
        log("DEBUG", f"[CPU Gateway Sync][{trace_id}] Processing sync serverless/run request - ENTER")
        
        try:
            if not self.gpu_function_url:
                log("ERROR", f"[CPU Gateway Sync][{trace_id}] GPU_FUNCTION_URL not configured")
                return jsonify({
                    "type": "error",
                    "error_code": "configuration_error",
                    "error_message": "GPU_FUNCTION_URL not configured for CPU mode"
                }), 500
            
            # 获取请求数据 - /serverless/run 的请求体直接是 prompt（ComfyUI 工作流定义）
            request_body = request.get_json(force=True, silent=True)
            if request_body is None:
                log("ERROR", f"[CPU Gateway Sync][{trace_id}] Empty or invalid JSON body")
                return jsonify({
                    "type": "error",
                    "error_code": "invalid_request_error",
                    "error_message": "Request body must be valid JSON containing ComfyUI workflow definition"
                }), 400
            
            # 检查 prompt 是否为空对象或无效
            if not isinstance(request_body, dict) or len(request_body) == 0:
                log("ERROR", f"[CPU Gateway Sync][{trace_id}] Empty prompt (workflow definition is required)")
                return jsonify({
                    "type": "error",
                    "error_code": "invalid_request_error",
                    "error_message": "Prompt (workflow definition) cannot be empty. Please provide a valid ComfyUI workflow."
                }), 400
            
            # 获取查询参数
            stream = request.args.get("stream", "false").lower() == "true"
            output_base64 = request.args.get("output_base64", "false").lower() == "true"
            output_oss = request.args.get("output_oss", "false").lower() == "true"
            
            log("DEBUG", f"[CPU Gateway Sync][{trace_id}] Request params: stream={stream}, output_base64={output_base64}, output_oss={output_oss}")
            
            # 构造 GPU 函数的完整 URL
            gpu_url = f"{self.gpu_function_url.rstrip('/')}/api/serverless/run"
            
            # 转发请求头（同步调用）
            forward_headers = {
                k: v for k, v in request.headers.items()
                if k.lower() not in ['host', 'content-length']
            }
            forward_headers['X-Forwarded-By'] = 'CPU-Router-Sync'
            
            # 生成或提取 task_id
            async_task_id = request.headers.get("x-fc-async-task-id")
            fc_request_id = request.headers.get("x-fc-request-id")
            x_task_id = request.headers.get("x-serverless-api-task-id")
            
            if x_task_id:
                task_id = x_task_id
                task_id_source = "x-serverless-api-task-id"
            elif async_task_id:
                task_id = async_task_id
                task_id_source = "x-fc-async-task-id"
            elif fc_request_id:
                task_id = fc_request_id
                task_id_source = "x-fc-request-id"
            else:
                task_id = f"sync_{constants.INSTANCE_ID}_{int(_ts.time() * 1000)}"
                task_id_source = "generated"
            
            # 传递 task_id 给 GPU 函数
            if task_id:
                forward_headers['x-serverless-api-task-id'] = task_id
            
            log("DEBUG", f"[CPU Gateway Sync][{trace_id}] Sync forwarding to GPU: url={gpu_url}, task_id={task_id} (from {task_id_source})")
            
            # 生命周期日志
            log("INFO", f"[TaskLifecycle][{task_id}][SYNC_FORWARDING] Synchronously forwarding to GPU, url={gpu_url}")
            
            # 同步转发请求到 GPU 函数
            t_post_start = _ts.time()
            resp = requests.post(
                gpu_url,
                json=request_body,
                headers=forward_headers,
                params=request.args,
                timeout=300  # 同步调用设置较长超时时间（5分钟）
            )
            t_post_cost = (_ts.time() - t_post_start) * 1000
            
            log("DEBUG", f"[CPU Gateway Sync][{trace_id}] GPU sync response received: "
                  f"status={resp.status_code}, cost_ms={t_post_cost:.1f}, resp_len={len(resp.content)}")
            
            # 生命周期日志
            log("INFO", f"[TaskLifecycle][{task_id}][SYNC_COMPLETED] Sync call completed, "
                  f"status={resp.status_code}, total_time_ms={t_post_cost:.1f}")
            
            total_cost = (_ts.time() - req_start) * 1000
            log("DEBUG", f"[CPU Gateway Sync][{trace_id}] RETURN to client: status={resp.status_code}, total_cost_ms={total_cost:.1f}")
            
            # 直接返回 GPU 函数的响应
            try:
                response_data = resp.json()
                return jsonify(response_data), resp.status_code
            except:
                # 如果响应不是 JSON，直接返回原始内容
                return Response(
                    resp.content,
                    status=resp.status_code,
                    content_type=resp.headers.get('Content-Type', 'application/octet-stream')
                )
        
        except requests.exceptions.Timeout:
            total_cost = (_ts.time() - req_start) * 1000
            error_msg = f"GPU function request timed out after {total_cost:.1f}ms"
            log("ERROR", f"[CPU Gateway Sync][{trace_id}] {error_msg}")
            
            return jsonify({
                "type": "error",
                "error_code": "timeout_error",
                "error_message": error_msg
            }), 504
        
        except Exception as e:
            import traceback
            total_cost = (_ts.time() - req_start) * 1000 if 'req_start' in locals() else -1
            error_msg = f"Failed to forward sync request to GPU function: {str(e)}"
            log("ERROR", f"[CPU Gateway Sync][{trace_id}] {error_msg}\nStacktrace:\n{traceback.format_exc()}\nElapsed_ms={total_cost:.1f}")
            
            return jsonify({
                "type": "error",
                "error_code": "gpu_forward_error",
                "error_message": error_msg
            }), 500

