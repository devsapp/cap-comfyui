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


class CpuGatewayService:
    """CPU函数网关服务，负责转发请求到GPU函数"""
    
    def __init__(self):
        self.gpu_function_url = constants.GPU_FUNCTION_URL
    
    def handle_queue_get_request(self, task_queue_manager):
        """
        处理 GET /api/queue 请求
        获取队列状态（优化版本：防止卡住）
        
        Args:
            task_queue_manager: 任务队列管理器实例
            
        Returns:
            tuple: (response_data, status_code)
        """
        import time as queue_time
        import threading
        import queue as thread_queue
        from services.gateway.task_queue import TaskStatus
        
        request_start = queue_time.time()
        
        print(f"[CPU Gateway] Handling GET /api/queue request with timeout protection")
        
        try:
            # 超时保护：如果获取任务列表超过1秒，返回空队列
            result_queue = thread_queue.Queue()
            exception_queue = thread_queue.Queue()
            
            def fetch_tasks_with_timeout():
                try:
                    # 获取任务列表
                    all_tasks = task_queue_manager.get_all_tasks()
                    result_queue.put(all_tasks)
                except Exception as e:
                    exception_queue.put(e)
            
            # 在单独线程中获取任务列表
            fetch_thread = threading.Thread(target=fetch_tasks_with_timeout, daemon=True)
            fetch_thread.start()
            fetch_thread.join(timeout=1.0)  # 1秒超时
            
            # 检查是否有异常
            if not exception_queue.empty():
                raise exception_queue.get()
            
            # 检查是否获取到结果
            if result_queue.empty():
                print(f"[CPU Gateway] Queue request timed out after 1 second, returning empty queue")
                return jsonify({
                    "queue_running": [],
                    "queue_pending": [],
                    "_warning": "Request timed out, showing empty queue to prevent blocking"
                })
            
            all_tasks = result_queue.get()
            fetch_time = queue_time.time() - request_start
            
        except Exception as e:
            print(f"[CPU Gateway] Error fetching tasks for queue request: {e}")
            return jsonify({
                "queue_running": [],
                "queue_pending": [],
                "_error": "Failed to fetch queue status"
            })
        
        # 转换为ComfyUI原生的队列状态格式
        comfyui_queue_info = {
            "queue_running": [],  # 正在运行的任务列表
            "queue_pending": []   # 等待中的任务列表
        }
        
        # 优化：限制返回数量，避免大量数据导致响应慢
        MAX_TASKS_PER_STATUS = 20  # 每种状态最多显示20个任务
        running_count = 0
        pending_count = 0
        
        convert_start = queue_time.time()
        
        for task in all_tasks:
            # 超时保护：如果处理时间过长，停止处理
            if queue_time.time() - request_start > 2.0:  # 总处理超过2秒
                print(f"[CPU Gateway] Queue processing timeout, stopping after {queue_time.time() - request_start:.2f}s")
                break
            
            # 根据任务状态分类，并限制数量
            if task.status == TaskStatus.PROCESSING and running_count < MAX_TASKS_PER_STATUS:
                # 构造ComfyUI兼容的任务信息格式（简化版）
                task_info = [
                    1,  # number - 任务优先级
                    task.task_id,  # prompt_id
                    task.prompt or {},  # prompt - 避免None导致序列化失败
                    {"client_id": task.client_id} if task.client_id else {},  # extra_data
                    []  # outputs_to_execute
                ]
                comfyui_queue_info["queue_running"].append(task_info)
                running_count += 1
                
            elif task.status in [TaskStatus.PENDING, TaskStatus.SUBMITTED] and pending_count < MAX_TASKS_PER_STATUS:
                task_info = [
                    1,  # number - 任务优先级
                    task.task_id,  # prompt_id
                    task.prompt or {},  # prompt - 避免None导致序列化失败
                    {"client_id": task.client_id} if task.client_id else {},  # extra_data
                    []  # outputs_to_execute
                ]
                comfyui_queue_info["queue_pending"].append(task_info)
                pending_count += 1
            
            # 如果两种状态的任务都已达到上限，提前结束
            if running_count >= MAX_TASKS_PER_STATUS and pending_count >= MAX_TASKS_PER_STATUS:
                print(f"[CPU Gateway] Reached max tasks limit, showing top {MAX_TASKS_PER_STATUS} per status")
                break
        
        total_time = queue_time.time() - request_start
        convert_time = queue_time.time() - convert_start
        
        print(f"[CPU Gateway] Queue status: {len(comfyui_queue_info['queue_running'])} running, "
              f"{len(comfyui_queue_info['queue_pending'])} pending "
              f"(fetch: {fetch_time:.2f}s, convert: {convert_time:.2f}s, total: {total_time:.2f}s)")
        
        # 在调试模式下显示性能信息
        if request.args.get("debug") == "true":
            comfyui_queue_info["_debug"] = {
                "fetch_time_ms": round(fetch_time * 1000, 1),
                "convert_time_ms": round(convert_time * 1000, 1),
                "total_time_ms": round(total_time * 1000, 1),
                "total_tasks_processed": len(all_tasks),
                "max_tasks_per_status": MAX_TASKS_PER_STATUS
            }
        
        return jsonify(comfyui_queue_info)
    
    def handle_queue_post_request(self, task_queue_manager):
        """
        处理 POST /api/queue 请求
        队列管理（清空/删除任务）
        
        Args:
            task_queue_manager: 任务队列管理器实例
            
        Returns:
            tuple: (response, status_code)
        """
        print(f"[CPU Gateway] Handling POST /api/queue request")
        
        request_data = request.get_json() or {}
        
        if "clear" in request_data and request_data["clear"]:
            # 清空队列
            print(f"[CPU Gateway] Clearing task queue")
            
            cleared_count = task_queue_manager.clear_queue()
            print(f"[CPU Gateway] Cleared {cleared_count} tasks from queue")
            
            return Response(status=200)
        
        elif "delete" in request_data:
            # 删除指定任务
            to_delete = request_data.get("delete", [])
            print(f"[CPU Gateway] Deleting tasks: {to_delete}")
            
            deleted_count = 0
            for task_id in to_delete:
                if task_queue_manager.cancel_task(task_id):
                    deleted_count += 1
                    print(f"[CPU Gateway] Deleted task: {task_id}")
                else:
                    print(f"[CPU Gateway] Failed to delete task (not found or already completed): {task_id}")
            
            print(f"[CPU Gateway] Deleted {deleted_count} tasks from queue")
            
            return Response(status=200)
        
        else:
            # 无效的队列操作请求
            return jsonify({
                "error": {
                    "type": "invalid_request_error",
                    "message": "Invalid queue operation. Supported operations: clear, delete"
                }
            }), 400
    
    def handle_prompt_request_async(self, task_queue_manager):
        """
        处理 POST /api/prompt 请求（异步转发到GPU函数）
        
        Args:
            task_queue_manager: 任务队列管理器实例
            
        Returns:
            tuple: (response_data, status_code)
        """
        try:
            import time as _ts
            trace_id = f"cpu_prompt_{int(_ts.time()*1000)}"
            req_start = _ts.time()
            print(f"[CPU Gateway Async][{trace_id}] Processing async prompt request using FC async invocation - ENTER")
            
            if not self.gpu_function_url:
                print(f"[CPU Gateway][{trace_id}] ERROR: GPU_FUNCTION_URL not configured for CPU mode")
                return jsonify({
                    "error": {
                        "type": "configuration_error",
                        "message": "GPU_FUNCTION_URL not configured for CPU mode"
                    }
                }), 500
            
            # 获取请求数据
            request_data = request.get_json()
            if not request_data:
                print(f"[CPU Gateway][{trace_id}] ERROR: Empty or invalid JSON body")
                return jsonify({
                    "error": {
                        "type": "invalid_request_error",
                        "message": "Request body must be valid JSON"
                    }
                }), 400
            
            # 提取 prompt 数据和 client_id
            prompt = request_data.get("prompt")
            client_id = request_data.get("client_id", "")
            
            print(f"[CPU Gateway][{trace_id}] Request meta: client_id={client_id}, body_size={len(request.data) if hasattr(request, 'data') else 'unknown'} bytes, args={dict(request.args)}")
            
            if not prompt:
                print(f"[CPU Gateway][{trace_id}] ERROR: Missing 'prompt' in request body")
                return jsonify({
                    "error": {
                        "type": "invalid_request_error", 
                        "message": "Missing 'prompt' in request body"
                    }
                }), 400
            
            # 生成任务 ID 作为 prompt_id（优先使用异步调用ID保证一致性）
            async_task_id = request.headers.get("x-fc-async-task-id")
            fc_request_id = request.headers.get("x-fc-request-id")
            
            if async_task_id:
                task_id = async_task_id
                task_id_source = "x-fc-async-task-id"
            elif fc_request_id:
                task_id = fc_request_id
                task_id_source = "x-fc-request-id"
            else:
                task_id = f"prompt_{constants.INSTANCE_ID}_{int(time.time() * 1000)}"
                task_id_source = "generated"
            
            # 使用任务ID作为prompt_id，保持一致性
            prompt_id = task_id
            
            print(f"[CPU Gateway Async][{trace_id}] Generated prompt_id: {prompt_id} from {task_id_source} (async_id='{async_task_id}', request_id='{fc_request_id}'), Client ID: {client_id}")
            
            # 生命周期日志：接收任务
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [TaskLifecycle][{task_id}][RECEIVED] Task received, client_id={client_id}, nodes={len(prompt)}")
            
            # 将任务添加到队列（仅用于跟踪，实际执行在GPU函数中）
            try:
                # 获取可选参数
                output_base64 = request.args.get("output_base64", "false").lower() == "true"
                output_oss = request.args.get("output_oss", "false").lower() == "true"
                
                t_submit_start = _ts.time()
                submitted_task_id = task_queue_manager.submit_task(
                    prompt=prompt,
                    client_id=client_id,
                    task_id=task_id,
                    output_base64=output_base64,
                    output_oss=output_oss
                )
                
                print(f"[CPU Gateway][{trace_id}] Task {submitted_task_id} added to queue for tracking (enqueue_cost_ms={( _ts.time()-t_submit_start)*1000:.1f})")
                
                # 生命周期日志：任务入队
                print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [TaskLifecycle][{task_id}][QUEUED] Task queued, enqueue_time_ms={(_ts.time()-t_submit_start)*1000:.1f}")
                
                # 将任务与客户端关联，使前端能够接收到状态更新
                if client_id:
                    task_queue_manager.associate_task_with_client_id(submitted_task_id, client_id)
            except Exception as e:
                import traceback as _tb
                print(f"[CPU Gateway][{trace_id}] Warning: Failed to add task to queue: {e}\n{_tb.format_exc()}")
                # 不影响主流程，继续转发请求
            
            # 构造 GPU 函数的完整 URL - 直接转发到 serverless API
            gpu_url = f"{self.gpu_function_url.rstrip('/')}/api/serverless/run"

            forward_headers = {
                k: v for k, v in request.headers.items()
                if k.lower() not in ['host', 'content-length']
            }
            forward_headers['X-Forwarded-By'] = 'CPU-Router-Async'
            forward_headers['X-Task-ID'] = task_id  # 传递任务ID给GPU函数（调试用）
            forward_headers['x-fc-async-task-id'] = task_id  # ServerlessApiService 使用的header（正确的header名称）
            forward_headers['x-fc-request-id'] = task_id  # 覆盖request-id确保与task_id一致
            forward_headers['x-fc-trace-id'] = task_id
            forward_headers['x-fc-invocation-type'] = 'Async'  # 明确指定异步调用
            
            safe_header_keys = ['X-Forwarded-By', 'X-Task-ID', 'Content-Type', 'x-fc-async-task-id', 'x-fc-request-id', 'x-fc-invocation-type', 'x-fc-trace-id']
            logged_headers = {k: v for k, v in forward_headers.items() if k in safe_header_keys}
            print(f"[CPU Gateway Async][{trace_id}] Async forwarding to GPU: url={gpu_url}, headers={logged_headers}, args={dict(request.args)}")
            
            # 生命周期日志：开始转发GPU
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [TaskLifecycle][{task_id}][FORWARDING] Forwarding to GPU function, url={gpu_url}")
            
            # 转发请求到 GPU 函数 - 使用异步调用
            # /api/serverless/run 期望直接接收 prompt 数据
            serverless_request_data = prompt
            
            t_post_start = _ts.time()
            resp = requests.post(
                gpu_url,
                json=serverless_request_data,
                headers=forward_headers,
                params=request.args,
                timeout=30  # 异步调用的响应应该很快返回
            )
            t_post_cost = (_ts.time() - t_post_start) * 1000
            
            print(f"[CPU Gateway Async][{trace_id}] GPU async invocation responded: status={resp.status_code}, cost_ms={t_post_cost:.1f}, resp_len={len(resp.content)}")
            
            # 生命周期日志：转发完成
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [TaskLifecycle][{task_id}][FORWARDED] GPU forward completed, status={resp.status_code}, forward_time_ms={t_post_cost:.1f}")
            
            # 通过x-fc-trace-id保持requestId一致性，无需更新task_id
            if resp.status_code == 202:  # 异步调用成功接受
                print(f"[CPU Gateway Async][{trace_id}] Async invocation accepted, using consistent task_id: {task_id}")
            else:
                print(f"[CPU Gateway Async][{trace_id}] Async invocation failed with status: {resp.status_code}")
            
            # 更新任务状态（标记为已提交）
            try:
                from services.gateway.task_queue import TaskStatus
                import time as time_module
                
                task = task_queue_manager.queue.get_task(task_id)
                if task and resp.status_code == 202:  # 202 表示异步任务已接受
                    with task_queue_manager.queue._lock:
                        task.status = TaskStatus.PROCESSING
                        task.started_at = time_module.time()
                    print(f"[CPU Gateway Async] Task {task_id} marked as processing (async submission accepted)")
                elif task and resp.status_code != 202:
                    with task_queue_manager.queue._lock:
                        task.status = TaskStatus.FAILED
                    print(f"[CPU Gateway Async] Task {task_id} marked as failed (async submission rejected)")
            except Exception as e:
                import traceback as _tb
                print(f"[CPU Gateway Async][{trace_id}] Warning: Failed to update task status: {e}\n{_tb.format_exc()}")
            
            # 立即返回 ComfyUI 兼容的响应格式，不等待 GPU 处理完成
            total_cost = (_ts.time() - req_start) * 1000
            
            if resp.status_code == 202:  # 异步任务已接受
                print(f"[CPU Gateway Async][{trace_id}] RETURN to client immediately: prompt_id={prompt_id}, total_cost_ms={total_cost:.1f}")
                
                # 返回标准 ComfyUI prompt API 格式
                comfyui_response = {
                    "prompt_id": prompt_id,
                    "number": 1,
                    "node_errors": {}
                }
                
                # 在调试模式下提供额外信息
                if request.args.get("debug") == "true":
                    comfyui_response["_task_id"] = task_id
                    comfyui_response["_mode"] = "async"
                    comfyui_response["_gpu_function_url"] = self.gpu_function_url
                    comfyui_response["_async_invocation_status"] = resp.status_code
                
                return jsonify(comfyui_response)
            else:
                # 异步调用失败，返回错误
                print(f"[CPU Gateway Async][{trace_id}] Async invocation failed: status={resp.status_code}, total_cost_ms={total_cost:.1f}")
                return jsonify({
                    "error": {
                        "type": "async_invocation_error",
                        "message": f"Failed to invoke GPU function asynchronously: HTTP {resp.status_code}"
                    }
                }), 500
            
        except Exception as e:
            import traceback
            import requests as _rq
            is_timeout = isinstance(e, _rq.exceptions.Timeout)
            error_msg = f"Failed to forward request to GPU function: {str(e)} (timeout={is_timeout})"
            total_cost = (time.time() - req_start) * 1000 if 'req_start' in locals() else -1
            print(f"[CPU Gateway][{trace_id}] {error_msg}\nStacktrace:\n{traceback.format_exc()}\nElapsed_ms={total_cost:.1f}")
            
            return jsonify({
                "error": {
                    "type": "gpu_forward_error",
                    "message": error_msg
                }
            }), 500
