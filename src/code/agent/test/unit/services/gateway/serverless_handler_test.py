"""
ServerlessHandler 单元测试
测试 CPU 模式下 serverless API 转发功能
"""
import pytest
from unittest.mock import Mock, patch, MagicMock, call
from flask import Flask
import requests

import constants
from services.gateway.handlers.serverless_handler import ServerlessHandler


# ==================== Fixtures ====================

@pytest.fixture
def app():
    """创建 Flask 应用用于测试请求上下文"""
    app = Flask(__name__)
    return app


@pytest.fixture
def handler():
    """创建 ServerlessHandler 实例"""
    return ServerlessHandler()


@pytest.fixture
def mock_constants():
    """Mock constants"""
    with patch('services.gateway.handlers.serverless_handler.constants') as mock_const:
        mock_const.GPU_FUNCTION_URL = 'http://gpu-function:8080'
        mock_const.ERROR_CODE = constants.ERROR_CODE
        mock_const.HEADER_FC_INVOCATION_TYPE = 'X-Fc-Invocation-Type'
        mock_const.HEADER_FC_ASYNC_TASK_ID = 'x-fc-async-task-id'
        mock_const.HEADER_FC_REQUEST_ID = 'x-fc-request-id'
        yield mock_const


# ==================== 测试配置验证 ====================

def test_gpu_url_not_configured(handler, app):
    """测试：GPU URL 未配置时返回错误"""
    with patch('services.gateway.handlers.serverless_handler.constants') as mock_const:
        mock_const.GPU_FUNCTION_URL = None
        mock_const.ERROR_CODE = constants.ERROR_CODE
        
        with app.test_request_context(json={'test': 'data'}):
            response, status_code = handler.handle_post_request()
            
            assert status_code == 500
            # response 是 jsonify() 的返回对象，需要调用 get_json()
            json_data = response.get_json()
            assert json_data['type'] == 'error'
            assert json_data['error_code'] == constants.ERROR_CODE.CONFIGURATION_ERROR.value
            assert 'GPU_FUNCTION_URL not configured' in json_data['error_message']


# ==================== 测试同步转发 ====================

def test_sync_forward_success(handler, app, mock_constants):
    """测试：同步模式转发成功"""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        'type': 'serverless_api',
        'data': {
            'prompt_id': 'test-123',
            'results': []
        }
    }
    
    with patch('services.gateway.handlers.serverless_handler.requests.post', return_value=mock_response) as mock_post:
        with app.test_request_context(
            json={'prompt': {'test': 'workflow'}},
            headers={'x-fc-request-id': 'req-123'}
        ):
            response, status_code = handler.handle_post_request()
            
            # 验证返回结果
            assert status_code == 200
            # response 直接就是字典（resp.json() 的返回值）
            assert response['type'] == 'serverless_api'
            assert response['data']['prompt_id'] == 'test-123'
            
            # 验证请求参数
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[1]['json'] == {'prompt': {'test': 'workflow'}}
            assert call_args[1]['timeout'] == 600  # 同步模式超时时间


def test_sync_forward_with_query_params(handler, app, mock_constants):
    """测试：同步模式转发时正确透传查询参数"""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {'type': 'serverless_api', 'data': {}}
    
    with patch('services.gateway.handlers.serverless_handler.requests.post', return_value=mock_response) as mock_post:
        with app.test_request_context(
            json={'test': 'data'},
            query_string='output_base64=true&output_oss=true',
            headers={'x-fc-request-id': 'req-123'}
        ):
            response_data, status_code = handler.handle_post_request()
            
            # 验证查询参数被透传
            call_args = mock_post.call_args
            assert 'params' in call_args[1]


# ==================== 测试异步转发 ====================

def test_async_forward_success(handler, app, mock_constants):
    """测试：异步模式转发成功"""
    mock_response = Mock()
    mock_response.status_code = 202
    mock_response.json.return_value = {
        'task_id': 'async-task-123',
        'status': 'pending'
    }
    
    with patch('services.gateway.handlers.serverless_handler.requests.post', return_value=mock_response) as mock_post:
        with app.test_request_context(
            json={'prompt': {'test': 'workflow'}},
            headers={
                'x-fc-request-id': 'req-123',
                'X-Fc-Invocation-Type': 'Async'
            }
        ):
            response, status_code = handler.handle_post_request()
            
            # 验证返回结果 - 直接透传 GPU 的响应
            assert status_code == 202
            assert response['task_id'] == 'async-task-123'
            assert response['status'] == 'pending'
            
            # 验证请求参数
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[1]['timeout'] == 30  # 异步模式超时时间


def test_async_forward_unexpected_status(handler, app, mock_constants):
    """测试：异步模式 GPU 返回非 202 状态码 - 验证透传行为"""
    mock_response = Mock()
    mock_response.status_code = 500
    # GPU 可能返回任何格式的错误，这里只是一个例子
    gpu_error_response = {
        'type': 'error',
        'error_code': 'internal_error',
        'error_message': 'GPU internal error'
    }
    mock_response.json.return_value = gpu_error_response
    
    with patch('services.gateway.handlers.serverless_handler.requests.post', return_value=mock_response):
        with app.test_request_context(
            json={'test': 'data'},
            headers={
                'x-fc-request-id': 'req-123',
                'X-Fc-Invocation-Type': 'Async'
            }
        ):
            response, status_code = handler.handle_post_request()
            
            # 验证透传行为：原样返回 GPU 的响应
            assert status_code == 500
            assert response == gpu_error_response  # 完全相等，不修改


# ==================== 测试 Headers 透传 ====================

def test_headers_forwarding(handler, app, mock_constants):
    """测试：正确透传客户端 headers"""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {'type': 'serverless_api', 'data': {}}
    
    with patch('services.gateway.handlers.serverless_handler.requests.post', return_value=mock_response) as mock_post:
        with app.test_request_context(
            json={'test': 'data'},
            headers={
                'x-fc-request-id': 'req-123',
                'x-fc-access-key-id': 'test-ak',
                'x-fc-access-key-secret': 'test-sk',
                'x-fc-security-token': 'test-sts',
                'Content-Type': 'application/json',
                'Host': 'cpu-function:8080',  # 应该被过滤
                'Content-Length': '100'  # 应该被过滤
            }
        ):
            handler.handle_post_request()
            
            # 验证 headers
            call_args = mock_post.call_args
            headers = call_args[1]['headers']
            
            # 将所有 header key 转为小写进行比较（因为 Flask 会规范化 header 名称）
            headers_lower = {k.lower(): v for k, v in headers.items()}
            
            # 应该透传的 headers
            assert 'x-fc-request-id' in headers_lower
            assert 'x-fc-access-key-id' in headers_lower
            assert 'x-fc-access-key-secret' in headers_lower
            assert 'x-fc-security-token' in headers_lower
            assert 'content-type' in headers_lower
            
            # 不应该透传的 headers
            assert 'host' not in headers_lower
            assert 'content-length' not in headers_lower


def test_task_id_extraction_priority(handler, app, mock_constants):
    """测试：task_id 提取优先级（x-fc-async-task-id > x-fc-request-id）"""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {'type': 'serverless_api', 'data': {}}
    
    with patch('services.gateway.handlers.serverless_handler.requests.post', return_value=mock_response):
        with patch('services.gateway.handlers.serverless_handler.log') as mock_log:
            # 同时提供两个 header
            with app.test_request_context(
                json={'test': 'data'},
                headers={
                    'x-fc-async-task-id': 'async-123',
                    'x-fc-request-id': 'req-456'
                }
            ):
                handler.handle_post_request()
                
                # 验证使用了 async-task-id（优先级更高）
                assert call("INFO", "[ServerlessHandler][async-123] Forwarding sync request") in mock_log.call_args_list


# ==================== 测试错误处理 ====================

def test_timeout_error(handler, app, mock_constants):
    """测试：请求超时错误处理（合并到 internal_error）"""
    with patch('services.gateway.handlers.serverless_handler.requests.post', side_effect=requests.exceptions.Timeout):
        with app.test_request_context(
            json={'test': 'data'},
            headers={'x-fc-request-id': 'req-123'}
        ):
            response, status_code = handler.handle_post_request()
            
            assert status_code == 500
            json_data = response.get_json()
            assert json_data['type'] == 'error'
            assert json_data['error_code'] == constants.ERROR_CODE.INTERNAL_ERROR.value


def test_request_exception(handler, app, mock_constants):
    """测试：网络请求错误处理（合并到 internal_error）"""
    with patch('services.gateway.handlers.serverless_handler.requests.post', 
               side_effect=requests.exceptions.RequestException('Connection failed')):
        with app.test_request_context(
            json={'test': 'data'},
            headers={'x-fc-request-id': 'req-123'}
        ):
            response, status_code = handler.handle_post_request()
            
            assert status_code == 500
            json_data = response.get_json()
            assert json_data['type'] == 'error'
            assert json_data['error_code'] == constants.ERROR_CODE.INTERNAL_ERROR.value
            assert 'Connection failed' in json_data['error_message']


def test_unexpected_exception(handler, app, mock_constants):
    """测试：未预期的异常处理"""
    with patch('services.gateway.handlers.serverless_handler.requests.post', 
               side_effect=Exception('Unexpected error')):
        with app.test_request_context(
            json={'test': 'data'},
            headers={'x-fc-request-id': 'req-123'}
        ):
            response, status_code = handler.handle_post_request()
            
            assert status_code == 500
            # response 是 jsonify() 的返回对象
            json_data = response.get_json()
            assert json_data['type'] == 'error'
            assert json_data['error_code'] == constants.ERROR_CODE.INTERNAL_ERROR.value


# ==================== 测试日志输出 ====================

def test_logging_async_request(handler, app, mock_constants):
    """测试：异步请求日志输出"""
    mock_response = Mock()
    mock_response.status_code = 202
    mock_response.json.return_value = {'task_id': 'test', 'status': 'pending'}
    
    with patch('services.gateway.handlers.serverless_handler.requests.post', return_value=mock_response):
        with patch('services.gateway.handlers.serverless_handler.log') as mock_log:
            with app.test_request_context(
                json={'test': 'data'},
                headers={
                    'x-fc-request-id': 'req-123',
                    'X-Fc-Invocation-Type': 'Async'
                }
            ):
                handler.handle_post_request()
                
                # 验证日志调用
                assert mock_log.call_count >= 1
                assert call("INFO", "[ServerlessHandler][req-123] Forwarding async request") in mock_log.call_args_list


def test_logging_sync_request(handler, app, mock_constants):
    """测试：同步请求日志输出"""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {'type': 'serverless_api', 'data': {}}
    
    with patch('services.gateway.handlers.serverless_handler.requests.post', return_value=mock_response):
        with patch('services.gateway.handlers.serverless_handler.log') as mock_log:
            with app.test_request_context(
                json={'test': 'data'},
                headers={'x-fc-request-id': 'req-123'}
            ):
                handler.handle_post_request()
                
                # 验证日志调用
                assert mock_log.call_count >= 1
                assert call("INFO", "[ServerlessHandler][req-123] Forwarding sync request") in mock_log.call_args_list


# ==================== 测试 GPU URL 构造 ====================

def test_gpu_url_construction(handler, app, mock_constants):
    """测试：正确构造 GPU URL"""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {'type': 'serverless_api', 'data': {}}
    
    with patch('services.gateway.handlers.serverless_handler.requests.post', return_value=mock_response) as mock_post:
        with app.test_request_context(
            json={'test': 'data'},
            headers={'x-fc-request-id': 'req-123'}
        ):
            handler.handle_post_request()
            
            # 验证 URL
            call_args = mock_post.call_args
            url = call_args[0][0]
            assert url == 'http://gpu-function:8080/api/serverless/run'


def test_gpu_url_with_trailing_slash(handler, app):
    """测试：GPU URL 带尾部斜杠时正确处理"""
    with patch('services.gateway.handlers.serverless_handler.constants') as mock_const:
        mock_const.GPU_FUNCTION_URL = 'http://gpu-function:8080/'
        
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'type': 'serverless_api', 'data': {}}
        
        with patch('services.gateway.handlers.serverless_handler.requests.post', return_value=mock_response) as mock_post:
            with app.test_request_context(
                json={'test': 'data'},
                headers={'x-fc-request-id': 'req-123'}
            ):
                handler.handle_post_request()
                
                # 验证 URL（不应该有双斜杠）
                call_args = mock_post.call_args
                url = call_args[0][0]
                assert url == 'http://gpu-function:8080/api/serverless/run'
                assert '//' not in url.replace('http://', '')
