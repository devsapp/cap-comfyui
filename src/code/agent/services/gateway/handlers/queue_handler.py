"""
Queue Handler
处理队列相关的请求逻辑
"""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed

from flask import Response, copy_current_request_context, jsonify, request

from utils.logger import log
from utils.fc_openapi.fc_client import stop_async_task
from services.gateway.task.utils.prompt_utils import parse_prompt_body

# 单次 clear 最多对多少个 PENDING 调 StopAsyncTask，避免请求阻塞过久；其余仍由 clear_queue 本地清除
MAX_PENDING_STOP_ON_CLEAR = 50
# 并行 stop 的最大线程数
MAX_STOP_WORKERS = 10
# 等待所有 stop 调用的总超时（秒），超时后仍会执行 clear_queue
STOP_BATCH_TIMEOUT_SEC = 10


class QueueHandler:
    """处理队列相关的请求"""
    
    def __init__(self, task_manager):
        self.task_manager = task_manager
    
    def handle_get_request(self):
        """
        处理 GET /api/queue 请求 获取队列状态
        
        Returns:
            Flask response
        """
        from services.gateway.task.task import TaskStatus
        
        try:
            # 获取任务列表
            all_tasks = self.task_manager.get_current_user_tasks()
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
        
        # 构造任务信息的辅助函数（与 history 的 prompt 数组格式一致：含 outputs_to_execute）
        def _build_task_info(task):
            """构造ComfyUI兼容的任务信息格式"""
            prompt_dict, outputs_to_execute, extra_data = parse_prompt_body(task.prompt_body or {})
            return [
                1,  # number - 任务优先级
                task.task_id,  # prompt_id
                prompt_dict or {},  # prompt - 避免None导致序列化失败
                extra_data or {},  # extra_data
                outputs_to_execute,
            ]

        for task in all_tasks:
            # 根据任务状态分类
            if task.status == TaskStatus.RUNNING:
                comfyui_queue_info["queue_running"].append(_build_task_info(task))
            elif task.status == TaskStatus.PENDING:
                comfyui_queue_info["queue_pending"].append(_build_task_info(task))
        
        return jsonify(comfyui_queue_info)
    
    def handle_post_request(self):
        """
        处理 POST /api/queue 请求
        队列管理（清空/删除任务）
        
        Returns:
            Flask response
        """
        request_data = request.get_json() or {}
        
        if "clear" in request_data and request_data["clear"]:
            # 清空队列：先对当前用户 PENDING 任务并行调 StopAsyncTask（数量上限 + 总超时），再清本地 PENDING（与 ComfyUI 只清 pending 对齐，不停 RUNNING）
            log("INFO", f"Clearing task queue")
            pending_ids = self.task_manager.get_current_user_pending_task_ids()
            ids_to_stop = pending_ids[:MAX_PENDING_STOP_ON_CLEAR]
            workers = min(MAX_STOP_WORKERS, len(ids_to_stop) or 1)

            @copy_current_request_context
            def stop_in_context(task_id):
                return stop_async_task(task_id)

            stopped = 0
            failed_ids = []

            if ids_to_stop:
                ex = ThreadPoolExecutor(max_workers=workers)
                timed_out = False
                try:
                    futs = {ex.submit(stop_in_context, tid): tid for tid in ids_to_stop}
                    try:
                        for fut in as_completed(futs, timeout=STOP_BATCH_TIMEOUT_SEC):
                            tid = futs[fut]
                            try:
                                ok = fut.result()
                                if ok:
                                    stopped += 1
                                else:
                                    failed_ids.append(tid)
                            except Exception as e:
                                log("WARNING", f"StopAsyncTask exception: task_id={tid}, error={e}")
                                failed_ids.append(tid)
                    except FuturesTimeoutError:
                        timed_out = True
                        # 取消尚未开始的 future，已在运行的计入失败
                        timed_out_ids = []
                        for fut, tid in futs.items():
                            if not fut.done():
                                fut.cancel()
                                timed_out_ids.append(tid)
                                failed_ids.append(tid)
                        log("WARNING", f"StopAsyncTask batch timed out after {STOP_BATCH_TIMEOUT_SEC}s; timed-out tasks: {sorted(timed_out_ids)}")
                finally:
                    # 超时时 wait=False，不阻塞等待仍在运行的 stop 调用
                    ex.shutdown(wait=not timed_out)

            if failed_ids:
                sample = failed_ids[:10]
                log(
                    "WARNING",
                    f"StopAsyncTask failed for {len(failed_ids)}/{len(ids_to_stop)} tasks "
                    f"(GPU may still be running). Failed ids (up to 10): {sample}",
                )

            cleared_count = self.task_manager.clear_queue()
            skipped = len(pending_ids) - len(ids_to_stop)
            log(
                "INFO",
                f"Cleared {cleared_count} tasks from queue; "
                f"StopAsyncTask stopped={stopped} failed={len(failed_ids)}"
                + (f" skipped(over limit)={skipped}" if skipped > 0 else ""),
            )
            return Response(status=200)
        
        elif "delete" in request_data:
            # 删除指定任务，停止对应的异步任务
            to_delete = request_data.get("delete", [])
            log("INFO", f"Deleting tasks: {to_delete}")
            
            deleted_count = 0
            for task_id in to_delete:
                cancel_result = self.task_manager.cancel_task(task_id)
                if cancel_result:
                    deleted_count += 1
                    log("DEBUG", f"Deleted task: {task_id}")
                else:
                    log("WARNING", f"Failed to delete task (not found or cannot be cancelled): {task_id}")
            
            log("INFO", f"Deleted {deleted_count} tasks from queue")
            
            return Response(status=200)
        
        else:
            # 无效的队列操作请求
            return jsonify({
                "error": {
                    "type": "invalid_request_error",
                    "message": "Invalid queue operation. Supported operations: clear, delete"
                }
            }), 400

