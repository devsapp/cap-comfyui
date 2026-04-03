"""
FC OpenAPI 客户端单测
"""
import pytest
from unittest.mock import patch, MagicMock

import constants
from utils.fc_openapi.fc_client import (
    FCClientException,
    stop_async_task,
    get_async_task,
    list_async_tasks,
)


class TestStopAsyncTaskConfig:
    """配置缺失时不应发请求，静默返回 False"""

    def test_returns_false_when_fc_account_id_empty(self):
        with patch.object(constants, "FC_ACCOUNT_ID", ""), \
             patch.object(constants, "FC_FUNCTION_NAME", "my-func-gw"), \
             patch("utils.fc_openapi.fc_client.OpenApiClient") as mock_client:
            assert stop_async_task("task-123") is False
            mock_client.assert_not_called()

    def test_returns_false_when_fc_function_name_empty(self):
        with patch.object(constants, "FC_ACCOUNT_ID", "123456"), \
             patch.object(constants, "FC_FUNCTION_NAME", ""), \
             patch("utils.fc_openapi.fc_client.OpenApiClient") as mock_client:
            assert stop_async_task("task-123") is False
            mock_client.assert_not_called()

    def test_returns_false_when_no_credentials(self):
        with patch.object(constants, "FC_ACCOUNT_ID", "123456"), \
             patch.object(constants, "FC_FUNCTION_NAME", "my-func-gw"), \
             patch("utils.fc_openapi.fc_client._get_credentials", return_value=("", "", "")), \
             patch("utils.fc_openapi.fc_client.OpenApiClient") as mock_client:
            assert stop_async_task("task-123") is False
            mock_client.assert_not_called()


class TestStopAsyncTaskRequest:
    """配置与凭证齐全时调用 OpenAPI 且 path/query 正确"""

    @pytest.fixture(autouse=True)
    def set_config(self):
        with patch.object(constants, "FC_ACCOUNT_ID", "1338904783509062"), \
             patch.object(constants, "FC_REGION", "cn-hangzhou"), \
             patch.object(constants, "FC_FUNCTION_NAME", "art-speed-test-mpbx-gw-prod"), \
             patch("utils.fc_openapi.fc_client._get_credentials", return_value=("ak", "sk", "sts")):
            yield

    def test_put_url_and_qualifier(self, set_config):
        mock_client_instance = MagicMock()
        mock_client_instance.call_api.return_value = {"statusCode": 200}
        with patch("utils.fc_openapi.fc_client.OpenApiClient", return_value=mock_client_instance):
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
        with patch("utils.fc_openapi.fc_client.OpenApiClient", return_value=mock_client_instance):
            stop_async_task("tid")
        params = mock_client_instance.call_api.call_args[0][0]
        pathname = params.pathname or ""
        assert "art-speed-test-mpbx-prod" in pathname
        assert "art-speed-test-mpbx-gw-prod" not in pathname or "/functions/art-speed-test-mpbx-prod/" in pathname

    def test_gpu_function_name_uses_explicit_env_var_when_set(self, set_config):
        """GPU_FC_FUNCTION_NAME 显式配置时优先使用，不依赖 FC_FUNCTION_NAME 推导。"""
        mock_client_instance = MagicMock()
        mock_client_instance.call_api.return_value = {"statusCode": 200}
        with patch.object(constants, "GPU_FUNCTION_NAME", "my-explicit-gpu-func"), \
             patch("utils.fc_openapi.fc_client.OpenApiClient", return_value=mock_client_instance):
            stop_async_task("tid")
        params = mock_client_instance.call_api.call_args[0][0]
        assert "my-explicit-gpu-func" in (params.pathname or "")

    def test_returns_false_on_non_2xx(self, set_config):
        mock_client_instance = MagicMock()
        mock_client_instance.call_api.return_value = {"statusCode": 404, "body": "not found"}
        with patch("utils.fc_openapi.fc_client.OpenApiClient", return_value=mock_client_instance):
            assert stop_async_task("task-123") is False

    def test_returns_false_on_sdk_exception(self, set_config):
        mock_client_instance = MagicMock()
        mock_client_instance.call_api.side_effect = Exception("connection refused")
        with patch("utils.fc_openapi.fc_client.OpenApiClient", return_value=mock_client_instance):
            assert stop_async_task("task-123") is False


# ==================== GetAsyncTask ====================

class TestGetAsyncTaskConfig:
    """配置缺失时 raise FCClientException，不发请求"""

    def test_raises_when_fc_account_id_empty(self):
        with patch.object(constants, "FC_ACCOUNT_ID", ""), \
             patch.object(constants, "FC_FUNCTION_NAME", "my-func-gw"):
            with pytest.raises(FCClientException):
                get_async_task("task-1")

    def test_raises_when_fc_function_name_empty(self):
        with patch.object(constants, "FC_ACCOUNT_ID", "123456"), \
             patch.object(constants, "FC_FUNCTION_NAME", ""):
            with pytest.raises(FCClientException):
                get_async_task("task-1")

    def test_raises_when_no_credentials(self):
        with patch.object(constants, "FC_ACCOUNT_ID", "123456"), \
             patch.object(constants, "FC_FUNCTION_NAME", "my-func-gw"), \
             patch("utils.fc_openapi.fc_client._get_credentials", return_value=("", "", "")):
            with pytest.raises(FCClientException):
                get_async_task("task-1")


class TestGetAsyncTaskRequest:
    """正常调用 GetAsyncTask"""

    @pytest.fixture(autouse=True)
    def set_config(self):
        with patch.object(constants, "FC_ACCOUNT_ID", "1338904783509062"), \
             patch.object(constants, "FC_REGION", "cn-hangzhou"), \
             patch.object(constants, "FC_FUNCTION_NAME", "art-speed-test-mpbx-gw-prod"), \
             patch("utils.fc_openapi.fc_client._get_credentials", return_value=("ak", "sk", "sts")):
            yield

    def test_returns_resp_on_success(self):
        mock_client = MagicMock()
        mock_client.call_api.return_value = {
            "statusCode": 200,
            "body": {"taskId": "task-1", "status": "Running"},
        }
        with patch("utils.fc_openapi.fc_client.OpenApiClient", return_value=mock_client):
            result = get_async_task("task-1")

        assert result["statusCode"] == 200
        assert result["body"]["taskId"] == "task-1"

    def test_pathname_contains_task_id(self):
        mock_client = MagicMock()
        mock_client.call_api.return_value = {"statusCode": 200, "body": {}}
        with patch("utils.fc_openapi.fc_client.OpenApiClient", return_value=mock_client):
            get_async_task("my-task-id")

        params = mock_client.call_api.call_args[0][0]
        assert "/async-tasks/my-task-id" in params.pathname
        assert params.method == "GET"

    def test_raises_fc_client_exception_on_sdk_error(self):
        mock_client = MagicMock()
        mock_client.call_api.side_effect = Exception("network timeout")
        with patch("utils.fc_openapi.fc_client.OpenApiClient", return_value=mock_client):
            with pytest.raises(FCClientException, match="network timeout"):
                get_async_task("task-1")


# ==================== ListAsyncTasks ====================

class TestListAsyncTasksConfig:
    """配置缺失时 raise FCClientException，不发请求"""

    def test_raises_when_fc_account_id_empty(self):
        with patch.object(constants, "FC_ACCOUNT_ID", ""), \
             patch.object(constants, "FC_FUNCTION_NAME", "my-func-gw"):
            with pytest.raises(FCClientException):
                list_async_tasks()

    def test_raises_when_fc_function_name_empty(self):
        with patch.object(constants, "FC_ACCOUNT_ID", "123456"), \
             patch.object(constants, "FC_FUNCTION_NAME", ""):
            with pytest.raises(FCClientException):
                list_async_tasks()

    def test_raises_when_no_credentials(self):
        with patch.object(constants, "FC_ACCOUNT_ID", "123456"), \
             patch.object(constants, "FC_FUNCTION_NAME", "my-func-gw"), \
             patch("utils.fc_openapi.fc_client._get_credentials", return_value=("", "", "")):
            with pytest.raises(FCClientException):
                list_async_tasks()


class TestListAsyncTasksRequest:
    """正常调用 ListAsyncTasks"""

    @pytest.fixture(autouse=True)
    def set_config(self):
        with patch.object(constants, "FC_ACCOUNT_ID", "1338904783509062"), \
             patch.object(constants, "FC_REGION", "cn-hangzhou"), \
             patch.object(constants, "FC_FUNCTION_NAME", "art-speed-test-mpbx-gw-prod"), \
             patch("utils.fc_openapi.fc_client._get_credentials", return_value=("ak", "sk", "sts")):
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
        with patch("utils.fc_openapi.fc_client.OpenApiClient", return_value=mock_client):
            result = list_async_tasks()

        assert result["statusCode"] == 200
        assert len(result["body"]["tasks"]) == 2

    def test_query_params_forwarded(self):
        mock_client = MagicMock()
        mock_client.call_api.return_value = {"statusCode": 200, "body": {"tasks": []}}
        with patch("utils.fc_openapi.fc_client.OpenApiClient", return_value=mock_client):
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
        assert query["startedTimeBegin"] == "1000"
        assert query["startedTimeEnd"] == "2000"
        assert query["limit"] == "10"
        assert query["nextToken"] == "tok"
        assert query["sortOrderByTime"] == "desc"
        assert query["prefix"] == "p-"

    def test_optional_params_not_included_when_none(self):
        mock_client = MagicMock()
        mock_client.call_api.return_value = {"statusCode": 200, "body": {"tasks": []}}
        with patch("utils.fc_openapi.fc_client.OpenApiClient", return_value=mock_client):
            list_async_tasks()

        req = mock_client.call_api.call_args[0][1]
        query = getattr(req, "query", {})
        assert query == {"qualifier": "LATEST"}

    def test_pathname_ends_with_async_tasks(self):
        mock_client = MagicMock()
        mock_client.call_api.return_value = {"statusCode": 200, "body": {"tasks": []}}
        with patch("utils.fc_openapi.fc_client.OpenApiClient", return_value=mock_client):
            list_async_tasks()

        params = mock_client.call_api.call_args[0][0]
        assert params.pathname.endswith("/async-tasks")
        assert params.method == "GET"

    def test_raises_fc_client_exception_on_sdk_error(self):
        mock_client = MagicMock()
        mock_client.call_api.side_effect = Exception("connection refused")
        with patch("utils.fc_openapi.fc_client.OpenApiClient", return_value=mock_client):
            with pytest.raises(FCClientException, match="connection refused"):
                list_async_tasks()
