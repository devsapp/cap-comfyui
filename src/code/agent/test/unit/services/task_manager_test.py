import pytest
from unittest.mock import Mock, patch
from flask import Flask
import requests

from services.gateway.task.task_manager import TaskManager
from exceptions.exceptions import ConfigurationError, InvalidRequestError, WorkerExecutionError


# ==================== Fixtures ====================

@pytest.fixture
def app():
    app = Flask(__name__)
    return app


@pytest.fixture
def task_manager():
    with patch('services.serverlessapi.serverless_api_service.ServerlessApiService') as mock_service:
        mock_service.return_value = Mock()
        manager = TaskManager(gpu_function_url="http://gpu-service")
        yield manager


# ==================== 测试类 ====================

class TestForwardToGpuSync:
    """测试 forward_to_gpu_sync 方法"""

    # ==================== 一、配置验证测试 ====================

    def test_gpu_url_not_configured(self, app):
        """测试用例 1.1: GPU URL 未配置"""
        with patch('services.serverlessapi.serverless_api_service.ServerlessApiService') as mock_service:
            mock_service.return_value = Mock()
            manager = TaskManager(gpu_function_url=None)
        
        with app.test_request_context(headers={'x-fc-request-id': 'req-123'}):
            with pytest.raises(ConfigurationError) as exc_info:
                manager.forward_to_gpu_sync(request_body={})
            
            assert exc_info.value.code == 500
            assert 'GPU_FUNCTION_URL not configured' in str(exc_info.value)

    # ==================== 二、Task ID 提取测试 ====================

    def test_extract_task_id_from_request_id(self, task_manager, app):
        """测试用例 2.1: 成功从 x-fc-request-id 提取 Task ID"""
        with app.test_request_context(headers={'x-fc-request-id': 'req-123'}):
            with patch('requests.post') as mock_post:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.json.return_value = {'result': 'success'}
                mock_post.return_value = mock_response
                
                response, status = task_manager.forward_to_gpu_sync(request_body={})
                
                # 验证 task_id 被正确使用
                call_args = mock_post.call_args
                headers = call_args.kwargs['headers']
                assert headers['x-fc-request-id'] == 'req-123'
                assert headers['x-fc-trace-id'] == 'req-123'

    def test_extract_task_id_missing(self, task_manager, app):
        """测试用例 2.2: Task ID 提取失败"""
        with app.test_request_context():  # 没有任何 headers
            with pytest.raises(InvalidRequestError) as exc_info:
                task_manager.forward_to_gpu_sync(request_body={})
            
            assert exc_info.value.code == 400
            assert 'Task ID not found' in str(exc_info.value)

    # ==================== 三、Headers 转发测试 ====================

    def test_forward_headers_correctly(self, task_manager, app):
        """测试用例 3.1: 正确构造同步调用的转发 headers"""
        with app.test_request_context(
            headers={
                'X-Fc-Request-Id': 'req-456',
                'Content-Type': 'application/json',
                'Authorization': 'Bearer my-token',
            }
        ):
            with patch('requests.post') as mock_post:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.json.return_value = {}
                mock_post.return_value = mock_response
                
                task_manager.forward_to_gpu_sync(request_body={})
                
                # 验证转发的 headers
                headers = mock_post.call_args.kwargs['headers']
                
                assert headers['x-fc-request-id'] == 'req-456'
                assert headers['x-fc-trace-id'] == 'req-456'

                header_keys_lower = {k.lower(): v for k, v in headers.items()}
                if 'content-type' in header_keys_lower:
                    assert header_keys_lower['content-type'] == 'application/json'
                if 'authorization' in header_keys_lower:
                    assert header_keys_lower['authorization'] == 'Bearer my-token'

    # ==================== 四、请求转发测试 ====================

    def test_gpu_url_construction(self, task_manager, app):
        """测试用例 4.1: GPU URL 正确构造"""
        with app.test_request_context(headers={'x-fc-request-id': 'req-123'}):
            with patch('requests.post') as mock_post:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.json.return_value = {}
                mock_post.return_value = mock_response
                
                task_manager.forward_to_gpu_sync(request_body={})
                
                # 验证 URL
                call_url = mock_post.call_args.args[0]
                assert call_url == 'http://gpu-service/api/serverless/run'

    def test_request_body_forwarded(self, task_manager, app):
        """测试用例 4.2: 请求体正确转发"""
        with app.test_request_context(headers={'x-fc-request-id': 'req-123'}):
            request_body = {
                'prompt': {'1': {'class_type': 'CheckpointLoaderSimple'}},
                'extra_data': {'client_id': 'test-client'}
            }
            
            with patch('requests.post') as mock_post:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.json.return_value = {}
                mock_post.return_value = mock_response
                
                task_manager.forward_to_gpu_sync(request_body=request_body)
                
                # 验证请求体
                call_kwargs = mock_post.call_args.kwargs
                assert call_kwargs['json'] == request_body

    # ==================== 五、成功响应测试 ====================

    def test_gpu_success_response(self, task_manager, app):
        """测试用例 5.1: GPU 返回 200 成功响应"""
        with app.test_request_context(headers={'x-fc-request-id': 'req-123'}):
            expected_response = {
                'status': 'success',
                'outputs': {'images': ['image1.png']},
                'prompt_id': 'prompt-123'
            }
            
            with patch('requests.post') as mock_post:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.json.return_value = expected_response
                mock_post.return_value = mock_response
                
                response, status = task_manager.forward_to_gpu_sync(request_body={})
                
                assert status == 200
                assert response == expected_response

    # ==================== 六、错误响应测试 ====================

    def test_gpu_error_response_with_json(self, task_manager, app):
        """测试用例 6.1: GPU 返回非 200 状态码"""
        with app.test_request_context(headers={'x-fc-request-id': 'req-123'}):
            error_response = {
                'type': 'error',
                'error_code': 'invalid_prompt',
                'error_message': 'Prompt validation failed'
            }
            
            with patch('requests.post') as mock_post:
                mock_response = Mock()
                mock_response.status_code = 400
                mock_response.json.return_value = error_response
                mock_post.return_value = mock_response
                
                with pytest.raises(WorkerExecutionError) as exc_info:
                    task_manager.forward_to_gpu_sync(request_body={})
                
                assert exc_info.value.code == 400
                assert 'Worker returned HTTP 400' in str(exc_info.value)

    # ==================== 七、超时异常测试 ====================

    def test_request_timeout(self, task_manager, app):
        """测试用例 7.1: 请求超时"""
        with app.test_request_context(headers={'x-fc-request-id': 'req-123'}):
            with patch('requests.post') as mock_post:
                mock_post.side_effect = requests.exceptions.Timeout("Connection timeout")
                
                with pytest.raises(WorkerExecutionError) as exc_info:
                    task_manager.forward_to_gpu_sync(request_body={})
                
                assert exc_info.value.code == 500
                assert 'Failed to send sync request to GPU' in str(exc_info.value)

    # ==================== 八、网络异常测试 ====================

    def test_connection_error(self, task_manager, app):
        """测试用例 8.1: 连接失败（ConnectionError）"""
        with app.test_request_context(headers={'x-fc-request-id': 'req-123'}):
            with patch('requests.post') as mock_post:
                mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")
                
                with pytest.raises(WorkerExecutionError) as exc_info:
                    task_manager.forward_to_gpu_sync(request_body={})
                
                assert exc_info.value.code == 500
                assert 'Failed to send sync request to GPU' in str(exc_info.value)

    def test_other_request_exception(self, task_manager, app):
        """测试用例 8.2: 其他请求异常"""
        with app.test_request_context(headers={'x-fc-request-id': 'req-123'}):
            with patch('requests.post') as mock_post:
                mock_post.side_effect = requests.exceptions.RequestException("DNS lookup failed")
                
                with pytest.raises(WorkerExecutionError) as exc_info:
                    task_manager.forward_to_gpu_sync(request_body={})
                
                assert exc_info.value.code == 500
                assert 'Failed to send sync request to GPU' in str(exc_info.value)
