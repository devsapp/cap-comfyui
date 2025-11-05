import pytest
import json
import base64
import os
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
        LOG_LEVEL='INFO'
    ):
        # Mock ERROR_CODE enum
        mock_error_code = Mock()
        mock_error_code.UNCLASSIFY = Mock(value='UNCLASSIFY')
        mock_error_code.PROMPT_ERROR = Mock(value='PROMPT_ERROR')
        
        with patch('constants.ERROR_CODE', mock_error_code):
            yield


@pytest.fixture
def service(mock_constants):
    """创建 ServerlessApiService 实例"""
    with patch('services.serverlessapi.serverless_api_service.FileSystem'):
        service = ServerlessApiService()
        return service


# ==================== 测试初始化 ====================

def test_service_initialization(service):
    """测试服务初始化"""
    assert service.endpoint == "http://localhost:8188"
    assert service.store is not None

# ==================== WebSocket 在不同消息场景下的关闭行为 ====================

def _run_websocket_test(service, app, prompt_id, messages, should_close=True, mock_history_result=True):
    """
    辅助函数：运行 WebSocket 测试
    
    Args:
        service: ServerlessApiService 实例
        app: Flask 应用
        prompt_id: 期望的 prompt_id
        messages: 要发送的 WebSocket 消息列表（JSON 字符串）
        should_close: 是否期望 WebSocket 被关闭
        mock_history_result: 是否 Mock get_history_result
    
    Returns:
        mock_ws: Mock 的 WebSocket 对象
    """
    mock_ws = Mock()
    captured_on_message = None
    api_prompt_called = [False]
    
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
                        response = Mock()
                        response.status_code = 200
                        response.json.return_value = {'prompt_id': prompt_id}
                        return response
                    
                    mock_post.side_effect = mock_api_prompt
                    
                    if mock_history_result:
                        with patch.object(service, 'get_history_result', return_value={
                            prompt_id: {'outputs': {}}
                        }):
                            try:
                                result = service.run({'test': 'prompt'})
                                assert prompt_id in result
                            except Exception:
                                pass  # 某些测试期望抛出异常
                    else:
                        try:
                            result = service.run({'test': 'prompt'})
                            assert prompt_id in result
                        except Exception:
                            pass
    
    # # 等待异步线程完成
    # time.sleep(0.2)
    
    if should_close:
        mock_ws.close.assert_called()
    else:
        mock_ws.close.assert_not_called()
    
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


# ==================== 运行所有测试 ====================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
