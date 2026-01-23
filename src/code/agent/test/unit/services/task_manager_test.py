import pytest
import time
from unittest.mock import Mock, patch
from flask import Flask, g
from collections import defaultdict
import requests

from services.gateway.task.task_manager import TaskManager
from services.gateway.task.task import Task, TaskStatus
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
        manager = TaskManager(
            max_active_tasks=100,
            max_completed_tasks=50,
            gpu_function_url="http://gpu-service"
        )
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
class TestRunningTaskCount:
    """测试任务计数"""
    
    def test_running_count_by_user_initialization(self, task_manager):
        """_running_count_by_user 初始化"""
        assert hasattr(task_manager, '_running_count_by_user')
        assert isinstance(task_manager._running_count_by_user, defaultdict)
    
    def test_get_running_task_count_by_user_empty(self, task_manager, app):
        """空队列的运行计数"""
        with app.test_request_context():
            g.user_id = 'user-test'
            count = task_manager.get_running_task_count_by_user(g.user_id)
            assert count == 0
    
    def test_submit_task_increases_running_count(self, task_manager, app):
        """提交任务增加运行计数"""
        with app.test_request_context():
            g.user_id = 'user-test'
            
            with patch.object(task_manager, '_start_polling'), \
                 patch('services.gateway.task.utils.task_manager_util.TaskStatusBroadcaster'):
                
                prompt_body = {
                    "prompt": {"1": {"class_type": "Test"}},
                    "extra_data": {"client_id": "test-client"}
                }
                
                task_manager.submit_task(prompt_body, "client-123")
                
                count = task_manager.get_running_task_count_by_user(g.user_id)
                assert count == 1


class TestUserAuthentication:
    """测试用户认证相关功能（问题 1.1 修复验证）"""
    
    def test_multi_user_isolation_with_auth(self, task_manager, app):
        """验证多用户隔离（修复后不再使用 'default'）"""
        with patch.object(task_manager, '_start_polling'), \
             patch('services.gateway.task.utils.task_manager_util.TaskStatusBroadcaster'):
            
            prompt_body = {
                "prompt": {"1": {"class_type": "Test"}},
                "extra_data": {"client_id": "test-client"}
            }
            
            # 用户1提交任务
            with app.test_request_context():
                g.user_id = 'user-alice'
                task_id_1 = task_manager.submit_task(prompt_body, "client-1")
                count_alice = task_manager.get_running_task_count_by_user(g.user_id)
            
            # 用户2提交任务
            with app.test_request_context():
                g.user_id = 'user-bob'
                task_id_2 = task_manager.submit_task(prompt_body, "client-2")
                count_bob = task_manager.get_running_task_count_by_user(g.user_id)
            
            # 验证每个用户只能看到自己的任务
            assert count_alice == 1
            assert count_bob == 1
            
            # 用户1再次查询，应该还是1
            with app.test_request_context():
                g.user_id = 'user-alice'
                count_alice_again = task_manager.get_running_task_count_by_user(g.user_id)
                assert count_alice_again == 1


class TestCancelTaskRaceCondition:
    """测试取消任务的竞态条件修复（问题 1.2）"""
    
    def test_cancel_task_updates_count_correctly(self, task_manager, app):
        """取消任务时正确更新计数器"""
        with app.test_request_context():
            g.user_id = 'user-test'
            
            with patch.object(task_manager, '_start_polling'), \
                 patch('services.gateway.task.utils.task_manager_util.TaskStatusBroadcaster'):
                
                prompt_body = {
                    "prompt": {"1": {"class_type": "Test"}},
                    "extra_data": {"client_id": "test-client"}
                }
                
                # 提交任务
                task_id = task_manager.submit_task(prompt_body, "client-123")
                
                # 验证计数增加
                count_before = task_manager.get_running_task_count_by_user(g.user_id)
                assert count_before == 1
                
                # 取消任务
                with patch.object(task_manager, '_stop_polling'):
                    cancelled = task_manager.cancel_task(task_id)
                
                assert cancelled is True
                
                # 验证计数减少
                count_after = task_manager.get_running_task_count_by_user(g.user_id)
                assert count_after == 0
    
    def test_cancel_completed_task_fails(self, task_manager, app):
        """无法取消已完成的任务"""
        with app.test_request_context():
            g.user_id = 'user-test'
            
            with patch.object(task_manager, '_start_polling'), \
                 patch('services.gateway.task.utils.task_manager_util.TaskStatusBroadcaster'):
                
                prompt_body = {
                    "prompt": {"1": {"class_type": "Test"}},
                    "extra_data": {"client_id": "test-client"}
                }
                
                # 提交任务
                task_id = task_manager.submit_task(prompt_body, "client-123")
                
                # 模拟任务完成
                task = task_manager.get_task(task_id)
                task.update_status(TaskStatus.RUNNING)
                task.update_status(TaskStatus.COMPLETED)
                
                # 尝试取消已完成的任务
                with patch.object(task_manager, '_stop_polling'):
                    cancelled = task_manager.cancel_task(task_id)
                
                # 应该失败
                assert cancelled is False
    
    def test_cancel_nonexistent_task(self, task_manager, app):
        """取消不存在的任务应返回 False"""
        with app.test_request_context():
            g.user_id = 'user-test'
            
            with patch.object(task_manager, '_stop_polling'):
                cancelled = task_manager.cancel_task("nonexistent-task-id")
            
            assert cancelled is False
    
    def test_cancel_task_stops_polling(self, task_manager, app):
        """取消任务时应停止轮询"""
        with app.test_request_context():
            g.user_id = 'user-test'
            
            with patch.object(task_manager, '_start_polling'), \
                 patch('services.gateway.task.utils.task_manager_util.TaskStatusBroadcaster'):
                
                prompt_body = {
                    "prompt": {"1": {"class_type": "Test"}},
                    "extra_data": {"client_id": "test-client"}
                }
                
                # 提交任务
                task_id = task_manager.submit_task(prompt_body, "client-123")
                
                # 取消任务，验证 _stop_polling 被调用
                with patch.object(task_manager, '_stop_polling') as mock_stop_polling:
                    task_manager.cancel_task(task_id)
                    
                    # 验证停止轮询被调用
                    mock_stop_polling.assert_called_once_with(task_id)
    
    def test_concurrent_cancel_and_complete(self, task_manager, app):
        """模拟并发场景：取消和完成同时发生"""
        with app.test_request_context():
            g.user_id = 'user-test'
            
            with patch.object(task_manager, '_start_polling'), \
                 patch('services.gateway.task.utils.task_manager_util.TaskStatusBroadcaster'):
                
                prompt_body = {
                    "prompt": {"1": {"class_type": "Test"}},
                    "extra_data": {"client_id": "test-client"}
                }
                
                # 提交任务
                task_id = task_manager.submit_task(prompt_body, "client-123")
                
                initial_count = task_manager.get_running_task_count_by_user(g.user_id)
                assert initial_count == 1
                
                # 模拟任务开始运行
                task = task_manager.get_task(task_id)
                task.update_status(TaskStatus.RUNNING)
                
                # 尝试取消（在锁内完成所有操作）
                with patch.object(task_manager, '_stop_polling'):
                    cancelled = task_manager.cancel_task(task_id)
                
                # 验证取消成功
                assert cancelled is True
                
                # 验证计数正确
                final_count = task_manager.get_running_task_count_by_user(g.user_id)
                assert final_count == 0
                
                # 验证任务已被删除
                task_after = task_manager.get_task(task_id)
                assert task_after is None
class TestPerformance:
    """测试性能"""
    
    def test_get_history_with_many_users(self, task_manager, app):
        """多用户场景性能测试"""
        with task_manager._lock:
            for user_idx in range(100):
                user_id = f"user-{user_idx}"
                for i in range(10):
                    prompt_id = f"prompt-{user_id}-{i}"
                    history_item = {
                        "prompt": [i, prompt_id, {}, {}, []],
                        "outputs": {},
                        "status": {"completed": True, "status_str": "success", "messages": []},
                        "meta": {},
                        "user_id": user_id
                    }
                    task_manager._history_manager.history[prompt_id] = history_item
                    task_manager._history_manager._history_by_user[user_id][prompt_id] = history_item
        
        assert len(task_manager._history_manager.history) == 1000
        
        with app.test_request_context():
            g.user_id = 'user-50'
            
            start_time = time.time()
            result = task_manager.get_history()
            elapsed = time.time() - start_time
            
            assert len(result) == 10
            assert elapsed < 0.05


class TestDataConsistency:
    """测试数据一致性"""
    
    def test_history_and_index_stay_in_sync(self, task_manager, app):
        """history 和索引保持同步"""
        with app.test_request_context():
            g.user_id = 'user-test'
            
            with task_manager._lock:
                for i in range(5):
                    prompt_id = f"prompt-{i}"
                    history_item = {
                        "prompt": [i, prompt_id, {}, {}, []],
                        "outputs": {},
                        "status": {"completed": True, "status_str": "success", "messages": []},
                        "meta": {},
                        "user_id": "user-test"
                    }
                    task_manager._history_manager.history[prompt_id] = history_item
                    task_manager._history_manager._history_by_user["user-test"][prompt_id] = history_item
            
            assert len(task_manager._history_manager.history) == 5
            assert len(task_manager._history_manager._history_by_user["user-test"]) == 5
            assert set(task_manager._history_manager.history.keys()) == set(task_manager._history_manager._history_by_user["user-test"].keys())
