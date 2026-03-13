"""
FC OpenAPI 客户端单测
"""
import pytest
from unittest.mock import patch, MagicMock

import constants
from services.fc_openapi.fc_client import stop_async_task


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
