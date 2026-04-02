"""
TaskStatusHandler 单测（GetAsyncTask / ListAsyncTasks 封装）
"""
import pytest
from unittest.mock import patch, MagicMock
from flask import Flask

from services.serverlessapi.task_status_handler import TaskStatusHandler, _format_task


def _unwrap(resp):
    """成功路径可能只返回 Response；错误路径为 (Response, status)。"""
    if isinstance(resp, tuple):
        return resp[0], resp[1]
    return resp, resp.status_code


@pytest.fixture
def app():
    return Flask(__name__)


@pytest.fixture
def handler():
    return TaskStatusHandler()


class TestFormatTask:
    def test_maps_fc_fields(self):
        out = _format_task({
            "taskId": "t1",
            "status": "Running",
            "startedTime": 100,
            "endTime": 200,
            "durationMs": 50,
        })
        assert out["taskId"] == "t1"
        assert out["status"] == "Running"
        assert out["startTime"] == 100
        assert out["endTime"] == 200
        assert out["durationMs"] == 50

    def test_duration_from_end_minus_start_when_duration_ms_missing(self):
        out = _format_task({
            "taskId": "t1",
            "status": "Succeeded",
            "startedTime": 1000,
            "endTime": 1500,
        })
        assert out["durationMs"] == 500

    def test_empty_dict_returns_defaults(self):
        out = _format_task({})
        assert out["taskId"] == ""
        assert out["status"] == ""
        assert out["startTime"] is None
        assert out["endTime"] is None
        assert out["durationMs"] is None

    def test_started_time_without_end_time_leaves_duration_none(self):
        out = _format_task({
            "taskId": "t1",
            "status": "Running",
            "startedTime": 1000,
        })
        assert out["startTime"] == 1000
        assert out["endTime"] is None
        assert out["durationMs"] is None


class TestHandleGetTask:
    def test_empty_task_id_returns_400(self, app, handler):
        with app.test_request_context("/api/serverless/task/"):
            resp, code = handler.handle_get_task("   ")
            assert code == 400
            assert resp.get_json()["error_code"] == "INVALID_PARAMS"

    @patch("services.serverlessapi.task_status_handler.get_async_task")
    def test_fc_error_returns_500(self, mock_get, app, handler):
        mock_get.return_value = {"error": "no creds"}
        with app.test_request_context("/api/serverless/task/t1"):
            resp, code = handler.handle_get_task("t1")
            assert code == 500
            assert "Failed to query task" in resp.get_json()["error_message"]

    @patch("services.serverlessapi.task_status_handler.get_async_task")
    def test_404_returns_404(self, mock_get, app, handler):
        mock_get.return_value = {"statusCode": 404, "body": {}}
        with app.test_request_context("/api/serverless/task/t1"):
            resp, code = handler.handle_get_task("t1")
            assert code == 404
            assert "Task not found" in resp.get_json()["error_message"]

    @patch("services.serverlessapi.task_status_handler.get_async_task")
    def test_empty_body_returns_404(self, mock_get, app, handler):
        mock_get.return_value = {"statusCode": 200, "body": {}}
        with app.test_request_context("/api/serverless/task/t1"):
            resp, code = handler.handle_get_task("t1")
            assert code == 404

    @patch("services.serverlessapi.task_status_handler.get_async_task")
    def test_non_2xx_returns_500(self, mock_get, app, handler):
        mock_get.return_value = {
            "statusCode": 500,
            "body": {"taskId": "t1"},
        }
        with app.test_request_context("/api/serverless/task/t1"):
            resp, code = handler.handle_get_task("t1")
            assert code == 500
            assert "FC returned HTTP 500" in resp.get_json()["error_message"]

    @patch("services.serverlessapi.task_status_handler.get_async_task")
    def test_success_returns_formatted_task(self, mock_get, app, handler):
        mock_get.return_value = {
            "statusCode": 200,
            "body": {
                "taskId": "tid-1",
                "status": "Running",
                "startedTime": 10,
                "endTime": None,
            },
        }
        with app.test_request_context("/api/serverless/task/tid-1"):
            resp, code = _unwrap(handler.handle_get_task("tid-1"))
            assert code == 200
            data = resp.get_json()
            assert data["taskId"] == "tid-1"
            assert data["status"] == "Running"
            assert data["startTime"] == 10
            assert "detail" not in data

    @patch("services.serverlessapi.serverless_api_service.ServerlessApiService")
    @patch("services.serverlessapi.task_status_handler.get_async_task")
    def test_with_detail_includes_payload_and_messages(self, mock_get, mock_svc_cls, app, handler):
        mock_get.return_value = {
            "statusCode": 200,
            "body": {
                "taskId": "tid-1",
                "status": "Running",
                "taskPayload": {"foo": 1},
            },
        }
        mock_instance = MagicMock()
        mock_instance.get_status_from_store.return_value = ["m1", "m2"]
        mock_svc_cls.return_value = mock_instance

        with app.test_request_context("/api/serverless/task/tid-1?withDetail=true"):
            resp, code = _unwrap(handler.handle_get_task("tid-1"))
            assert code == 200
            data = resp.get_json()
            assert data["detail"]["payload"] == {"foo": 1}
            assert data["detail"]["messages"] == ["m1", "m2"]
            mock_instance.get_status_from_store.assert_called_once_with("tid-1")

    @patch("services.serverlessapi.serverless_api_service.ServerlessApiService")
    @patch("services.serverlessapi.task_status_handler.get_async_task")
    def test_with_detail_falls_back_to_invocation_payload(self, mock_get, mock_svc_cls, app, handler):
        mock_get.return_value = {
            "statusCode": 200,
            "body": {
                "taskId": "tid-2",
                "status": "Succeeded",
                "invocationPayload": {"bar": 2},
            },
        }
        mock_instance = MagicMock()
        mock_instance.get_status_from_store.return_value = []
        mock_svc_cls.return_value = mock_instance

        with app.test_request_context("/api/serverless/task/tid-2?withDetail=true"):
            resp, code = _unwrap(handler.handle_get_task("tid-2"))
            assert code == 200
            data = resp.get_json()
            assert data["detail"]["payload"] == {"bar": 2}
            assert data["detail"]["messages"] == []


class TestHandleListTasks:
    @patch("services.serverlessapi.task_status_handler.list_async_tasks")
    def test_invalid_status_400(self, mock_list, app, handler):
        with app.test_request_context("/api/serverless/tasks?status=Stopped"):
            resp, code = handler.handle_list_tasks()
            assert code == 400
            assert "Invalid status" in resp.get_json()["error_message"]
        mock_list.assert_not_called()

    @patch("services.serverlessapi.task_status_handler.list_async_tasks")
    def test_limit_out_of_range_400(self, mock_list, app, handler):
        with app.test_request_context("/api/serverless/tasks?limit=0"):
            resp, code = handler.handle_list_tasks()
            assert code == 400
        with app.test_request_context("/api/serverless/tasks?limit=101"):
            resp, code = handler.handle_list_tasks()
            assert code == 400
        mock_list.assert_not_called()

    @patch("services.serverlessapi.task_status_handler.list_async_tasks")
    def test_sort_order_invalid_400(self, mock_list, app, handler):
        with app.test_request_context("/api/serverless/tasks?sortOrderByTime=invalid"):
            resp, code = handler.handle_list_tasks()
            assert code == 400
        mock_list.assert_not_called()

    @patch("services.serverlessapi.task_status_handler.list_async_tasks")
    def test_fc_error_500(self, mock_list, app, handler):
        mock_list.return_value = {"error": "timeout"}
        with app.test_request_context("/api/serverless/tasks"):
            resp, code = handler.handle_list_tasks()
            assert code == 500
            assert "Failed to list tasks" in resp.get_json()["error_message"]

    @patch("services.serverlessapi.task_status_handler.list_async_tasks")
    def test_non_2xx_500(self, mock_list, app, handler):
        mock_list.return_value = {"statusCode": 503, "body": {}}
        with app.test_request_context("/api/serverless/tasks"):
            resp, code = handler.handle_list_tasks()
            assert code == 500

    @patch("services.serverlessapi.task_status_handler.list_async_tasks")
    def test_success_calls_list_with_params(self, mock_list, app, handler):
        mock_list.return_value = {
            "statusCode": 200,
            "body": {
                "tasks": [
                    {"taskId": "a", "status": "Succeeded", "startedTime": 1, "endTime": 2},
                ],
                "nextToken": "next",
            },
        }
        with app.test_request_context(
            "/api/serverless/tasks?status=Succeeded&limit=5&startedTimeBegin=1&startedTimeEnd=9"
            "&nextToken=tok&sortOrderByTime=asc&prefix=p-"
        ):
            resp, code = _unwrap(handler.handle_list_tasks())
            assert code == 200
            data = resp.get_json()
            assert len(data["tasks"]) == 1
            assert data["tasks"][0]["taskId"] == "a"
            assert data["nextToken"] == "next"

        mock_list.assert_called_once_with(
            status="Succeeded",
            started_time_begin=1,
            started_time_end=9,
            limit=5,
            next_token="tok",
            sort_order_by_time="asc",
            prefix="p-",
        )

    @patch("services.serverlessapi.task_status_handler.list_async_tasks")
    def test_empty_tasks_returns_empty_list_and_null_token(self, mock_list, app, handler):
        mock_list.return_value = {
            "statusCode": 200,
            "body": {"tasks": [], "nextToken": None},
        }
        with app.test_request_context("/api/serverless/tasks"):
            resp, code = _unwrap(handler.handle_list_tasks())
            assert code == 200
            data = resp.get_json()
            assert data["tasks"] == []
            assert data["nextToken"] is None
