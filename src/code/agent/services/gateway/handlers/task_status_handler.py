"""
Task Status Handler
处理异步任务状态查询请求，底层调用 FC OpenAPI GetAsyncTask / ListAsyncTasks
"""
from flask import jsonify, request

from utils.error_handler import ErrorResponse
from utils.logger import log
from utils.fc_openapi.fc_client import (
    FCClientException,
    get_async_task,
    list_async_tasks,
    ALLOWED_STATUSES,
)
from services.serverlessapi.serverless_api_service import ServerlessApiService


def _format_task(fc_task: dict) -> dict:
    """将 FC 返回的 task 对象转换为对外响应格式"""
    started_time = fc_task.get("startedTime")
    end_time = fc_task.get("endTime")
    duration_ms = fc_task.get("durationMs")

    if duration_ms is None and started_time and end_time:
        log("WARNING", f"FC task missing durationMs, startedTime={started_time}, endTime={end_time}")

    return {
        "taskId": fc_task.get("taskId", ""),
        "status": fc_task.get("status", ""),
        "startTime": started_time,
        "endTime": end_time,
        "durationMs": duration_ms,
    }


class TaskStatusHandler:
    """处理异步任务状态查询"""

    def __init__(self, serverless_api_service: ServerlessApiService):
        self._serverless_api_service = serverless_api_service

    def handle_get_task(self, task_id: str):
        """
        GET /api/serverless/task/{taskId}
        查询单个异步任务状态
        """
        if not task_id or not task_id.strip():
            return ErrorResponse.create(
                error_type="invalid_request_error",
                message="taskId is required",
                status_code=400,
            )

        try:
            resp = get_async_task(task_id)
        except FCClientException as e:
            if e.status_code == 404:
                return ErrorResponse.create(
                    error_type="not_found",
                    message=f"Task not found: {task_id}",
                    status_code=404,
                )
            log(
                "ERROR",
                f"GetAsyncTask failed: task_id={task_id}, status_code={e.status_code}, error={e}",
            )
            return ErrorResponse.create(
                error_type="internal_error",
                message="Failed to query task status",
                status_code=500,
            )

        body = resp.get("body") or {}
        result = _format_task(body)

        with_detail = request.args.get("withDetail", "false").lower() == "true"
        if with_detail:
            detail = {}
            detail["payload"] = body.get("taskPayload")
            detail["messages"] = self._serverless_api_service.get_status_from_store(task_id)
            result["detail"] = detail

        return jsonify(result)

    def handle_list_tasks(self):
        """
        GET /api/serverless/tasks
        查询异步任务列表
        """
        status = request.args.get("status")
        if status is not None and status not in ALLOWED_STATUSES:
            return ErrorResponse.create(
                error_type="invalid_request_error",
                message=(
                    f"Invalid status '{status}'. Allowed: "
                    f"{', '.join(sorted(ALLOWED_STATUSES))}"
                ),
                status_code=400,
            )

        limit = request.args.get("limit", type=int)
        if limit is not None and (limit < 1 or limit > 100):
            return ErrorResponse.create(
                error_type="invalid_request_error",
                message="limit must be between 1 and 100",
                status_code=400,
            )

        started_time_begin = request.args.get("startedTimeBegin", type=int)
        started_time_end = request.args.get("startedTimeEnd", type=int)
        next_token = request.args.get("nextToken")
        sort_order = request.args.get("sortOrderByTime")
        prefix = request.args.get("prefix")

        if sort_order is not None and sort_order not in ("asc", "desc"):
            return ErrorResponse.create(
                error_type="invalid_request_error",
                message="sortOrderByTime must be 'asc' or 'desc'",
                status_code=400,
            )

        try:
            resp = list_async_tasks(
                status=status,
                started_time_begin=started_time_begin,
                started_time_end=started_time_end,
                limit=limit,
                next_token=next_token,
                sort_order_by_time=sort_order,
                prefix=prefix,
            )
        except FCClientException as e:
            log(
                "ERROR",
                f"ListAsyncTasks failed: status_code={e.status_code}, error={e}",
            )
            return ErrorResponse.create(
                error_type="internal_error",
                message="Failed to list tasks",
                status_code=500,
            )

        body = resp.get("body") or {}
        fc_tasks = body.get("tasks") or []
        tasks = [_format_task(t) for t in fc_tasks]

        return jsonify({
            "tasks": tasks,
            "nextToken": body.get("nextToken"),
        })
