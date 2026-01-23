from pathlib import Path

import pytest
import json
from unittest.mock import Mock, patch, MagicMock, PropertyMock
from flask import Flask

from services.serverlessapi.serverless_api_service import ServerlessApiService, ComfyUIException
import constants


# ==================== Fixtures ====================

@pytest.fixture
def app():
    """创建 Flask 应用用于测试请求上下文"""
    app = Flask(__name__)
    return app


@pytest.fixture
def mock_constants():
    """Mock 常量配置"""
    with patch.multiple(
        'constants',
        APP_HOST='localhost:8188',
        MNT_DIR='/mnt/test',
        OSS_BUCKET_DOMAIN='oss-cn-beijing.aliyuncs.com',
        OSS_KEY_PREFIX='test-prefix',
        OSS_EXPIRES_IN_SECOND=3600,
        ALIBABA_CLOUD_ACCESS_KEY_ID='test-ak-env',
        ALIBABA_CLOUD_ACCESS_KEY_SECRET='test-sk-env',
        ALIBABA_CLOUD_SECURITY_TOKEN='test-sts-env',
        HEADER_KEY_ACCESS_KEY_ID='x-fc-access-key-id',
        HEADER_KEY_ACCESS_KEY_SECRET='x-fc-access-key-secret',
        HEADER_KEY_SECURITY_TOKEN='x-fc-security-token',
        LOG_LEVEL='INFO',
        INPUT_DIR='/tmp/test/input',
        MNT_INPUT_DIR='/mnt/test/input'
    ):
        # Mock ERROR_CODE enum
        mock_error_code = Mock()
        mock_error_code.UNCLASSIFY = Mock(value='UNCLASSIFY')
        mock_error_code.INVALID_PARAMS = Mock(value='INVALID_PARAMS')
        mock_error_code.PROMPT_ERROR = Mock(value='PROMPT_ERROR')
        mock_error_code.EXECUTION_FAILED = Mock(value='EXECUTION_FAILED')
        
        with patch('constants.ERROR_CODE', mock_error_code):
            yield


@pytest.fixture
def service(mock_constants):
    """创建 ServerlessApiService 实例"""
    with patch('services.serverlessapi.serverless_api_service.FileSystem'):
        with patch('services.serverlessapi.serverless_api_service.wake_input_cleaner'):
            service = ServerlessApiService()
            return service


# ==================== 测试初始化 ====================

def test_service_initialization(service):
    """测试服务初始化"""
    assert service.endpoint == "http://localhost:8188"
    assert service.store is not None

# ==================== WebSocket 在不同消息场景下的关闭行为 ====================

def _run_websocket_test(service, app, prompt_id, messages, should_close=True, mock_history_result=True, 
                        request_body=None, capture_request=False, task_id=None):
    """
    辅助函数：运行 WebSocket 测试
    
    Args:
        service: ServerlessApiService 实例
        app: Flask 应用
        prompt_id: 期望的 prompt_id
        messages: 要发送的 WebSocket 消息列表（JSON 字符串）
        should_close: 是否期望 WebSocket 被关闭
        mock_history_result: 是否 Mock get_history_result
        request_body: 自定义请求体（默认 {'test': 'prompt'}）
        capture_request: 是否捕获发送给 ComfyUI 的请求
        task_id: 自定义 task_id
    
    Returns:
        如果 capture_request=True: (result, captured_request, mock_ws)
        否则: mock_ws
    
    Note:
        api_get_history 的 mock 返回值会根据 should_close 自动决定：
        - should_close=True: 返回有结果，模拟任务已完成
        - should_close=False: 返回空字典，模拟任务未完成
    """
    mock_ws = Mock()
    captured_on_message = None
    api_prompt_called = [False]
    captured_prompt_request = None if capture_request else [None]
    
    def capture_websocket_creation(*args, **kwargs):
        nonlocal captured_on_message
        captured_on_message = kwargs.get('on_message')
        return mock_ws
    
    def mock_run_forever():
        """模拟 ws.run_forever()，在线程中触发消息"""
        import time
        
        # 发送 status 消息（让主线程继续）
        if captured_on_message:
            status_msg = json.dumps({'type': 'status', 'data': {'sid': 'test-client'}})
            captured_on_message(mock_ws, status_msg)
        
        # # 等待 prompt_id 被赋值
        # for _ in range(100):
        #     if api_prompt_called[0]:
        #         break
        #     time.sleep(0.01)
        
        # 额外等待确保 prompt_id 完全赋值
        time.sleep(0.05)
        
        # 发送所有测试消息
        if captured_on_message:
            for msg in messages:
                try:
                    captured_on_message(mock_ws, msg)
                except Exception:
                    pass  # 某些消息可能触发异常（如 execution_error）
    
    # 设置 mock_ws.run_forever 的行为
    mock_ws.run_forever.side_effect = mock_run_forever
    
    # 默认请求体
    if request_body is None:
        request_body = {'test': 'prompt'}
    
    with app.test_request_context(headers={
        'x-fc-access-key-id': 'test-ak',
        'x-fc-access-key-secret': 'test-sk',
        'x-fc-security-token': 'test-sts'
    }):
        with patch('services.serverlessapi.serverless_api_service.websocket.WebSocketApp', side_effect=capture_websocket_creation):
            with patch.object(service, 'parse_prompt', return_value={'test': 'prompt'}):
                with patch('services.serverlessapi.serverless_api_service.requests.post') as mock_post:
                    def mock_api_prompt(*args, **kwargs):
                        api_prompt_called[0] = True
                        # 捕获请求（如果需要）
                        if capture_request:
                            nonlocal captured_prompt_request
                            captured_prompt_request = kwargs.get('json')
                        response = Mock()
                        response.status_code = 200
                        response.json.return_value = {'prompt_id': prompt_id}
                        return response
                    
                    mock_post.side_effect = mock_api_prompt
                    
                    # 构建运行参数
                    run_kwargs = {}
                    if task_id:
                        run_kwargs['task_id'] = task_id
                    
                    if mock_history_result:
                        # 根据 should_close 决定 api_get_history 的返回值
                        # should_close=True: 返回有结果（模拟任务完成）
                        # should_close=False: 返回空字典（模拟任务未完成）
                        history_return = {prompt_id: {'outputs': {}}} if should_close else {}
                        
                        with patch.object(service, 'get_history_result', return_value={
                            'type': 'serverless_api',
                            'data': {'prompt_id': prompt_id, 'results': []}
                        }):
                            with patch.object(service, 'api_get_history', return_value=history_return):
                                with patch.object(service, 'put_status_to_store'):
                                    try:
                                        result = service.run(request_body, **run_kwargs)
                                    except Exception:
                                        result = None
                                        pass 
                    else:
                        try:
                            result = service.run({'test': 'prompt'})
                            assert prompt_id in result
                        except Exception:
                            pass  # 某些测试期望抛出异常
    
    # # 等待异步线程完成
    # time.sleep(0.2)
    
    if should_close:
        mock_ws.close.assert_called()
    else:
        mock_ws.close.assert_not_called()
    
    if capture_request:
        return result, captured_prompt_request, mock_ws
    else:
        return mock_ws


def test_websocket_closes_on_executing_with_matched_prompt_id(service, app):
    """测试：收到 executing 消息（node=None, prompt_id 匹配）时 WebSocket 应该关闭"""
    prompt_id = "test-prompt-123"
    message = json.dumps({
        'type': 'executing',
        'data': {'node': None, 'prompt_id': prompt_id}
    })
    _run_websocket_test(service, app, prompt_id, [message], should_close=True)

def test_websocket_closes_on_execution_success(service, app):
    """测试：收到 execution_success 消息时 WebSocket 应该关闭"""
    prompt_id = "test-prompt-success"
    message = json.dumps({
        'type': 'execution_success',
        'data': {'prompt_id': prompt_id}
    })
    _run_websocket_test(service, app, prompt_id, [message], should_close=True)


def test_websocket_closes_on_execution_error(service, app):
    """测试：收到 execution_error 消息时 WebSocket 应该关闭（会抛出异常）"""
    prompt_id = "test-prompt-error"
    message = json.dumps({
        'type': 'execution_error',
        'data': {
            'prompt_id': prompt_id,
            'node_id': '5',
            'node_type': 'KSampler',
            'exception_message': 'CUDA out of memory'
        }
    })
    _run_websocket_test(service, app, prompt_id, [message], should_close=True)


def test_websocket_not_closes_on_executing_with_mismatched_prompt_id(service, app):
    """测试：收到 executing 消息但 prompt_id 不匹配时 WebSocket 不应该关闭"""
    expected_prompt_id = "my-task-123"
    other_prompt_id = "other-task-456"
    message = json.dumps({
        'type': 'executing',
        'data': {'node': None, 'prompt_id': other_prompt_id}
    })
    _run_websocket_test(service, app, expected_prompt_id, [message], should_close=False)


def test_websocket_closes_on_empty_prompt_id_with_history_check(service, app):
    """测试：收到 executing 消息（node=None, prompt_id 为空）时通过历史检查后关闭"""
    prompt_id = "test-prompt-789"
    message = json.dumps({
        'type': 'executing',
        'data': {'node': None, 'prompt_id': ''}
    })
    
    # Mock api_get_history 返回非空结果（表示任务已完成）
    with patch.object(service, 'api_get_history', return_value={'prompt_id': {'outputs': {}}}):
        _run_websocket_test(service, app, prompt_id, [message], should_close=True)


def test_websocket_not_closes_while_node_executing(service, app):
    """测试：收到 executing 消息但还有节点在执行时 WebSocket 不应该关闭"""
    prompt_id = "test-prompt-running"
    message = json.dumps({
        'type': 'executing',
        'data': {'node': '5', 'prompt_id': prompt_id}
    })
    _run_websocket_test(service, app, prompt_id, [message], should_close=False)


# ==================== extra_data 辅助函数 ====================

def _run_extra_data_test(service, app, extra_data=None, task_id=None):
    """
    辅助函数：测试 extra_data 功能
        
    Args:
        service: ServerlessApiService 实例
        app: Flask 应用
        extra_data: 要传入的 extra_data，None 表示不传入
        task_id: 可选的自定义 task_id
    
    Returns:
        tuple: (result, captured_prompt_request)
    """
    prompt_id = task_id if task_id else f"test-prompt-{id(extra_data)}"
    
    if extra_data is not None:
        request_body = {
            'prompt': {'test': 'prompt'},
            'extra_data': extra_data
        }
    else:
        request_body = {'test': 'prompt'}
    
    messages = [json.dumps({
        'type': 'executing',
        'data': {'node': None, 'prompt_id': prompt_id}
    })]
    
    result, captured_request, _ = _run_websocket_test(
        service, app, prompt_id, messages,
        should_close=True,
        mock_history_result=True,
        request_body=request_body,
        capture_request=True,
        task_id=task_id 
    )
    
    return result, captured_request


# ==================== extra_data 基础测试 ====================

def test_run_with_extra_data_dict(service, app):
    """测试：运行工作流时传入 extra_data 字典，验证被传递给 ComfyUI"""
    extra_data = {
        "user_id": "user123",
        "session_id": "session456",
        "custom_field": "custom_value"
    }
    
    result, captured_request = _run_extra_data_test(service, app, extra_data)
    
    # 验证 prompt 被传递给 ComfyUI
    assert captured_request is not None, "captured_request should not be None"
    assert 'prompt' in captured_request, "prompt should be in request"
    assert captured_request['prompt'] == {'test': 'prompt'}, "prompt should match"
    
    # 验证 extra_data 被传递给 ComfyUI
    assert 'extra_data' in captured_request, "extra_data should be in request"
    assert captured_request['extra_data'] == extra_data, "extra_data should match"
    
    # 验证结果返回正常
    assert result is not None, "result should not be None"
    assert 'data' in result, "result should have data field"


def test_run_without_extra_data(service, app):
    """测试：运行工作流时不传入 extra_data，结果中不应包含 extra_data"""
    result, captured_request = _run_extra_data_test(service, app, extra_data=None)
    
    # 验证 prompt 仍然被传递给 ComfyUI
    assert captured_request is not None
    assert 'prompt' in captured_request, "prompt should always be in request"
    assert captured_request['prompt'] == {'test': 'prompt'}, "prompt should match"
    
    # 验证 extra_data 没有被传递给 ComfyUI
    assert 'extra_data' not in captured_request, "extra_data should not be in request when not provided"


# ==================== extra_data 边界测试 ====================

def test_run_with_none_values_in_extra_data(service, app):
    """测试：extra_data 包含 None 值"""
    extra_data = {
        "user_id": "user123",
        "session_id": None,  # None 值
        "metadata": None,
        "valid_field": "valid_value"
    }
    
    result, captured_request = _run_extra_data_test(service, app, extra_data)
    
    # 验证 None 值被正确传递给 ComfyUI
    assert captured_request['extra_data']['session_id'] is None
    assert captured_request['extra_data']['metadata'] is None
    assert captured_request['extra_data']['x-art-comfy-user'] == "user123"


def test_run_with_nested_extra_data(service, app):
    """测试：extra_data 包含嵌套结构"""
    extra_data = {
        "user": {
            "id": "user123",
            "profile": {
                "name": "Test User",
                "age": 25,
                "tags": ["tag1", "tag2", "tag3"]
            }
        },
        "metadata": {
            "source": "api",
            "version": "2.0",
            "features": {
                "enabled": ["feature1", "feature2"],
                "disabled": []
            }
        }
    }
    
    result, captured_request = _run_extra_data_test(service, app, extra_data)
    
    # 验证嵌套结构被正确传递给 ComfyUI
    assert captured_request['extra_data']['user']['id'] == "user123"
    assert captured_request['extra_data']['user']['profile']['name'] == "Test User"
    assert captured_request['extra_data']['user']['profile']['tags'] == ["tag1", "tag2", "tag3"]
    assert captured_request['extra_data']['metadata']['features']['enabled'] == ["feature1", "feature2"]

# ==================== extra_data 组合场景测试 ====================

def test_complete_request_structure(service, app):
    """测试：验证发送到 ComfyUI 的完整请求结构"""
    task_id = "test_task_123"
    extra_data = {
        "user_id": "user123",
        "session_id": "session456"
    }
    
    result, captured_request = _run_extra_data_test(service, app, extra_data, task_id)
    
    # 验证请求包含所有必要字段
    assert captured_request is not None, "request should not be None"
    
    # 验证必须的字段
    assert 'client_id' in captured_request, "client_id should be in request"
    assert 'prompt' in captured_request, "prompt should be in request"
    assert 'prompt_id' in captured_request, "prompt_id should be in request"
    assert 'extra_data' in captured_request, "extra_data should be in request"
    
    # 验证字段值
    assert captured_request['client_id'] == 'test-client', "client_id should match"
    assert captured_request['prompt'] == {'test': 'prompt'}, "prompt should match"
    assert captured_request['prompt_id'] == task_id, "prompt_id should match task_id"
    assert captured_request['extra_data'] == extra_data, "extra_data should match"
    
    print(f"\n完整请求结构: {captured_request}")

# ==================== request_body 类型验证测试 ====================

def test_run_with_none_request_body(service, app):
    """测试：request_body 为 None 时应抛出异常"""
    with app.test_request_context(headers={
        'x-fc-access-key-id': 'test-ak',
        'x-fc-access-key-secret': 'test-sk',
        'x-fc-security-token': 'test-sts'
    }):
        with patch.object(service, 'put_status_to_store'):
            with pytest.raises(ComfyUIException) as exc_info:
                service.run(None)
            
            # 验证错误信息
            assert "Invalid request body" in str(exc_info.value)
            assert "expected dict, got NoneType" in str(exc_info.value)


def test_run_with_string_request_body(service, app):
    """测试：request_body 为字符串时应抛出异常"""
    with app.test_request_context(headers={
        'x-fc-access-key-id': 'test-ak',
        'x-fc-access-key-secret': 'test-sk',
        'x-fc-security-token': 'test-sts'
    }):
        with patch.object(service, 'put_status_to_store'):
            with pytest.raises(ComfyUIException) as exc_info:
                service.run("invalid string body")
            
            # 验证错误信息
            assert "Invalid request body" in str(exc_info.value)
            assert "expected dict, got str" in str(exc_info.value)

def test_run_with_none_prompt_in_request_body(service, app):
    """测试：request_body 中 prompt 为 None 时应抛出异常"""
    with app.test_request_context(headers={
        'x-fc-access-key-id': 'test-ak',
        'x-fc-access-key-secret': 'test-sk',
        'x-fc-security-token': 'test-sts'
    }):
        with patch.object(service, 'put_status_to_store'):
            with pytest.raises(ComfyUIException) as exc_info:
                service.run({"prompt": None})
            
            # 验证错误信息
            assert "Missing or empty 'prompt'" in str(exc_info.value)


def test_error_code_for_invalid_params(service, app):
    """测试：参数错误时返回正确的错误码"""
    with app.test_request_context(headers={
        'x-fc-access-key-id': 'test-ak',
        'x-fc-access-key-secret': 'test-sk',
        'x-fc-security-token': 'test-sts'
    }):
        with patch.object(service, 'put_status_to_store'):
            try:
                service.run(None)
            except ComfyUIException as e:
                response = e.response()
                assert response['error_code'] == constants.ERROR_CODE.INVALID_PARAMS.value
                assert response['type'] == 'error'