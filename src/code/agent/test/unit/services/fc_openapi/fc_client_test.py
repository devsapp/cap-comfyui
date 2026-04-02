"""
FC OpenAPI 客户端单测
"""
import pytest
from unittest.mock import patch, MagicMock

import constants
from services.fc_openapi.fc_client import stop_async_task, get_async_task, list_async_tasks


class TestStopAsyncTaskConfig:
    """配置缺失时不应发请求"""

    def test_returns_false_when_fc_account_id_empty(self):
        with patch.object(constants, "FC_ACCOUNT_ID", ""), \
             patch.object(constants, "FC_FUNCTION_NAME", "my-func-gw"), \
             patch("services.fc_openapi.fc_client.OpenApiClient") as mock_client:
            result = stop_async_task("task-123")
            assert result is False
            mock_client.assert_not_called()

    def test_returns_false_when_fc_function_name_empty(self):
        with patch.object(constants, "FC_ACCOUNT_ID", "123456"), \
             patch.object(constants, "FC_FUNCTION_NAME", ""), \
             patch("services.fc_openapi.fc_client.OpenApiClient") as mock_client:
            result = stop_async_task("task-123")
            assert result is False
            mock_client.assert_not_called()

    def test_returns_false_when_no_credentials(self):
        with patch.object(constants, "FC_ACCOUNT_ID", "123456"), \
             patch.object(constants, "FC_FUNCTION_NAME", "my-func-gw"), \
             patch("services.fc_openapi.fc_client._get_credentials", return_value=("", "", "")), \
             patch("services.fc_openapi.fc_client.OpenApiClient") as mock_client:
            result = stop_async_task("task-123")
            assert result is False
            mock_client.assert_not_called()


class TestStopAsyncTaskRequest:
    """配置与凭证齐全时调用 OpenAPI 且 path/query 正确"""

    @pytest.fixture(autouse=True)
    def set_config(self):
        with patch.object(constants, "FC_ACCOUNT_ID", "1338904783509062"), \
             patch.object(constants, "FC_REGION", "cn-hangzhou"), \
             patch.object(constants, "FC_FUNCTION_NAME", "art-speed-test-mpbx-gw-prod"), \
             patch("services.fc_openapi.fc_client._get_credentials", return_value=("ak", "sk", "sts")):
            yield

    def test_put_url_and_qualifier(self, set_config):
        mock_client_instance = MagicMock()
        mock_client_instance.call_api.return_value = {"statusCode": 200}
        with patch("services.fc_openapi.fc_client.OpenApiClient", return_value=mock_client_instance):
            result = stop_async_task("task-123")

        assert result is True
        mock_client_instance.call_api.assert_called_once()
        call_args = mock_client_instance.call_api.call_args
        params = call_args[0][0]
        req = call_args[0][1]
        assert "2023-03-30/functions/art-speed-test-mpbx-prod/async-tasks/task-123/stop" in (params.pathname or "")
        assert getattr(req, "query", {}).get("qualifier") == "LATEST"

    def test_gpu_function_name_strips_gw(self, set_config):
        mock_client_instance = MagicMock()
        mock_client_instance.call_api.return_value = {"statusCode": 200}
        with patch("services.fc_openapi.fc_client.OpenApiClient", return_value=mock_client_instance):
            stop_async_task("tid")
        params = mock_client_instance.call_api.call_args[0][0]
        pathname = params.pathname or ""
        assert "art-speed-test-mpbx-prod" in pathname
        assert "art-speed-test-mpbx-gw-prod" not in pathname or "/functions/art-speed-test-mpbx-prod/" in pathname


# ==================== GetAsyncTask ====================

class TestGetAsyncTaskConfig:
    """配置缺失时返回 error dict"""

    def test_returns_error_when_fc_account_id_empty(self):
        with patch.object(constants, "FC_ACCOUNT_ID", ""), \
             patch.object(constants, "FC_FUNCTION_NAME", "my-func-gw"):
            result = get_async_task("task-1")
            assert "error" in result

    def test_returns_error_when_fc_function_name_empty(self):
        with patch.object(constants, "FC_ACCOUNT_ID", "123456"), \
             patch.object(constants, "FC_FUNCTION_NAME", ""):
            result = get_async_task("task-1")
            assert "error" in result

    def test_returns_error_when_no_credentials(self):
        with patch.object(constants, "FC_ACCOUNT_ID", "123456"), \
             patch.object(constants, "FC_FUNCTION_NAME", "my-func-gw"), \
             patch("services.fc_openapi.fc_client._get_credentials", return_value=("", "", "")):
            result = get_async_task("task-1")
            assert "error" in result


class TestGetAsyncTaskRequest:
    """正常调用 GetAsyncTask"""

    @pytest.fixture(autouse=True)
    def set_config(self):
        with patch.object(constants, "FC_ACCOUNT_ID", "1338904783509062"), \
             patch.object(constants, "FC_REGION", "cn-hangzhou"), \
             patch.object(constants, "FC_FUNCTION_NAME", "art-speed-test-mpbx-gw-prod"), \
             patch("services.fc_openapi.fc_client._get_credentials", return_value=("ak", "sk", "sts")):
            yield

    def test_returns_resp_on_success(self):
        mock_client = MagicMock()
        mock_client.call_api.return_value = {
            "statusCode": 200,
            "body": {"taskId": "task-1", "status": "Running"},
        }
        with patch("services.fc_openapi.fc_client.OpenApiClient", return_value=mock_client):
            result = get_async_task("task-1")

        assert result["statusCode"] == 200
        assert result["body"]["taskId"] == "task-1"

    def test_pathname_contains_task_id(self):
        mock_client = MagicMock()
        mock_client.call_api.return_value = {"statusCode": 200, "body": {}}
        with patch("services.fc_openapi.fc_client.OpenApiClient", return_value=mock_client):
            get_async_task("my-task-id")

        params = mock_client.call_api.call_args[0][0]
        assert "/async-tasks/my-task-id" in params.pathname
        assert params.method == "GET"

    def test_returns_error_on_exception(self):
        mock_client = MagicMock()
        mock_client.call_api.side_effect = Exception("network timeout")
        with patch("services.fc_openapi.fc_client.OpenApiClient", return_value=mock_client):
            result = get_async_task("task-1")

        assert "error" in result
        assert "network timeout" in result["error"]


# ==================== ListAsyncTasks ====================

class TestListAsyncTasksConfig:
    """配置缺失时返回 error dict"""

    def test_returns_error_when_fc_account_id_empty(self):
        with patch.object(constants, "FC_ACCOUNT_ID", ""), \
             patch.object(constants, "FC_FUNCTION_NAME", "my-func-gw"):
            result = list_async_tasks()
            assert "error" in result

    def test_returns_error_when_fc_function_name_empty(self):
        with patch.object(constants, "FC_ACCOUNT_ID", "123456"), \
             patch.object(constants, "FC_FUNCTION_NAME", ""):
            result = list_async_tasks()
            assert "error" in result

    def test_returns_error_when_no_credentials(self):
        with patch.object(constants, "FC_ACCOUNT_ID", "123456"), \
             patch.object(constants, "FC_FUNCTION_NAME", "my-func-gw"), \
             patch("services.fc_openapi.fc_client._get_credentials", return_value=("", "", "")):
            result = list_async_tasks()
            assert "error" in result


class TestListAsyncTasksRequest:
    """正常调用 ListAsyncTasks"""

    @pytest.fixture(autouse=True)
    def set_config(self):
        with patch.object(constants, "FC_ACCOUNT_ID", "1338904783509062"), \
             patch.object(constants, "FC_REGION", "cn-hangzhou"), \
             patch.object(constants, "FC_FUNCTION_NAME", "art-speed-test-mpbx-gw-prod"), \
             patch("services.fc_openapi.fc_client._get_credentials", return_value=("ak", "sk", "sts")):
            yield

    def test_returns_tasks_on_success(self):
        mock_client = MagicMock()
        mock_client.call_api.return_value = {
            "statusCode": 200,
            "body": {
                "tasks": [
                    {"taskId": "t1", "status": "Running"},
                    {"taskId": "t2", "status": "Succeeded"},
                ],
                "nextToken": "abc",
            },
        }
        with patch("services.fc_openapi.fc_client.OpenApiClient", return_value=mock_client):
            result = list_async_tasks()

        assert result["statusCode"] == 200
        assert len(result["body"]["tasks"]) == 2

    def test_query_params_forwarded(self):
        mock_client = MagicMock()
        mock_client.call_api.return_value = {"statusCode": 200, "body": {"tasks": []}}
        with patch("services.fc_openapi.fc_client.OpenApiClient", return_value=mock_client):
            list_async_tasks(
                status="Running",
                started_time_begin=1000,
                started_time_end=2000,
                limit=10,
                next_token="tok",
                sort_order_by_time="desc",
                prefix="p-",
            )

        req = mock_client.call_api.call_args[0][1]
        query = getattr(req, "query", {})
        assert query["qualifier"] == "LATEST"
        assert query["status"] == "Running"
        assert query["startedTimeBegin"] == 1000
        assert query["startedTimeEnd"] == 2000
        assert query["limit"] == 10
        assert query["nextToken"] == "tok"
        assert query["sortOrderByTime"] == "desc"
        assert query["prefix"] == "p-"

    def test_optional_params_not_included_when_none(self):
        mock_client = MagicMock()
        mock_client.call_api.return_value = {"statusCode": 200, "body": {"tasks": []}}
        with patch("services.fc_openapi.fc_client.OpenApiClient", return_value=mock_client):
            list_async_tasks()

        req = mock_client.call_api.call_args[0][1]
        query = getattr(req, "query", {})
        assert query == {"qualifier": "LATEST"}

    def test_pathname_ends_with_async_tasks(self):
        mock_client = MagicMock()
        mock_client.call_api.return_value = {"statusCode": 200, "body": {"tasks": []}}
        with patch("services.fc_openapi.fc_client.OpenApiClient", return_value=mock_client):
            list_async_tasks()

        params = mock_client.call_api.call_args[0][0]
        assert params.pathname.endswith("/async-tasks")
        assert params.method == "GET"

    def test_returns_error_on_exception(self):
        mock_client = MagicMock()
        mock_client.call_api.side_effect = Exception("connection refused")
        with patch("services.fc_openapi.fc_client.OpenApiClient", return_value=mock_client):
            result = list_async_tasks()

        assert "error" in result
        assert "connection refused" in result["error"]
