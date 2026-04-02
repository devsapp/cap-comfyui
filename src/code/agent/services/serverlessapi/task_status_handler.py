"""
Task Status Handler
处理异步任务状态查询请求，底层调用 FC OpenAPI GetAsyncTask / ListAsyncTasks
"""
from flask import jsonify, request

from utils.logger import log
from services.fc_openapi.fc_client import (
    get_async_task,
    list_async_tasks,
    ALLOWED_STATUSES,
)


def _format_task(fc_task: dict) -> dict:
    """将 FC 返回的 task 对象转换为对外响应格式"""
    started_time = fc_task.get("startedTime")
    end_time = fc_task.get("endTime")
    duration_ms = fc_task.get("durationMs")

    if duration_ms is None and started_time and end_time:
        duration_ms = end_time - started_time

    return {
        "taskId": fc_task.get("taskId", ""),
        "status": fc_task.get("status", ""),
        "startTime": started_time,
        "endTime": end_time,
        "durationMs": duration_ms,
    }


class TaskStatusHandler:
    """处理异步任务状态查询"""

    def handle_get_task(self, task_id: str):
        """
        GET /api/serverless/task/{taskId}
        查询单个异步任务状态
        """
        if not task_id or not task_id.strip():
            return jsonify({
                "type": "error",
                "error_code": "INVALID_PARAMS",
                "error_message": "taskId is required",
            }), 400

        resp = get_async_task(task_id)

        if "error" in resp:
            log("ERROR", f"GetAsyncTask failed: task_id={task_id}, error={resp['error']}")
            return jsonify({
                "type": "error",
                "error_code": "INTERNAL_ERROR",
                "error_message": f"Failed to query task: {resp['error']}",
            }), 500

        status_code = resp.get("statusCode", 0)
        body = resp.get("body") or {}

        if status_code == 404 or not body:
            return jsonify({
                "type": "error",
                "error_code": "INVALID_PARAMS",
                "error_message": f"Task not found: {task_id}",
            }), 404

        if status_code < 200 or status_code >= 300:
            return jsonify({
                "type": "error",
                "error_code": "INTERNAL_ERROR",
                "error_message": f"FC returned HTTP {status_code}",
            }), 500

        result = _format_task(body)

        with_detail = request.args.get("withDetail", "false").lower() == "true"
        if with_detail:
            detail = {}

            detail["payload"] = body.get("taskPayload") or body.get("invocationPayload")

            from services.serverlessapi.serverless_api_service import ServerlessApiService
            service = ServerlessApiService()
            detail["messages"] = service.get_status_from_store(task_id)

            result["detail"] = detail

        return jsonify(result)

    def handle_list_tasks(self):
        """
        GET /api/serverless/tasks
        查询异步任务列表
        """
        status = request.args.get("status")
        if status is not None and status not in ALLOWED_STATUSES:
            return jsonify({
                "type": "error",
                "error_code": "INVALID_PARAMS",
                "error_message": f"Invalid status '{status}'. Allowed: {', '.join(sorted(ALLOWED_STATUSES))}",
            }), 400

        limit = request.args.get("limit", type=int)
        if limit is not None and (limit < 1 or limit > 100):
            return jsonify({
                "type": "error",
                "error_code": "INVALID_PARAMS",
                "error_message": "limit must be between 1 and 100",
            }), 400

        started_time_begin = request.args.get("startedTimeBegin", type=int)
        started_time_end = request.args.get("startedTimeEnd", type=int)
        next_token = request.args.get("nextToken")
        sort_order = request.args.get("sortOrderByTime")
        prefix = request.args.get("prefix")

        if sort_order is not None and sort_order not in ("asc", "desc"):
            return jsonify({
                "type": "error",
                "error_code": "INVALID_PARAMS",
                "error_message": "sortOrderByTime must be 'asc' or 'desc'",
            }), 400

        resp = list_async_tasks(
            status=status,
            started_time_begin=started_time_begin,
            started_time_end=started_time_end,
            limit=limit,
            next_token=next_token,
            sort_order_by_time=sort_order,
            prefix=prefix,
        )

        if "error" in resp:
            log("ERROR", f"ListAsyncTasks failed: error={resp['error']}")
            return jsonify({
                "type": "error",
                "error_code": "INTERNAL_ERROR",
                "error_message": f"Failed to list tasks: {resp['error']}",
            }), 500

        status_code = resp.get("statusCode", 0)
        body = resp.get("body") or {}

        if status_code < 200 or status_code >= 300:
            return jsonify({
                "type": "error",
                "error_code": "INTERNAL_ERROR",
                "error_message": f"FC returned HTTP {status_code}",
            }), 500

        fc_tasks = body.get("tasks") or []
        tasks = [_format_task(t) for t in fc_tasks]

        return jsonify({
            "tasks": tasks,
            "nextToken": body.get("nextToken"),
        })
