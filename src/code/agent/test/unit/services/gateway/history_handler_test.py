"""
History Handler 单元测试
测试 /api/history 接口的核心逻辑
"""
import pytest
import time
from unittest.mock import Mock, patch, MagicMock
from flask import Flask, g
from dataclasses import dataclass
from typing import Optional

from services.gateway.handlers.history_handler import HistoryHandler


# ==================== Mock Task 数据类 ====================

@dataclass
class MockTask:
    """模拟 Task 对象用于测试"""
    task_id: str
    client_id: str
    prompt_body: dict
    user_id: str
    prompt_id: str
    status: Mock
    completed_at: Optional[float] = None


# ==================== Fixtures ====================

@pytest.fixture
def app():
    """创建测试用的 Flask 应用"""
    app = Flask(__name__)
    app.config['TESTING'] = True
    return app


@pytest.fixture
def mock_task_manager():
    """创建 mock 的 TaskManager"""
    manager = Mock()
    manager.get_history = Mock(return_value={})
    return manager


@pytest.fixture
def mock_task_status():
    """创建 mock 的 TaskStatus 枚举"""
    status = Mock()
    status.COMPLETED = Mock(name="COMPLETED")
    status.FAILED = Mock(name="FAILED")
    status.PENDING = Mock(name="PENDING")
    status.RUNNING = Mock(name="RUNNING")
    return status


@pytest.fixture
def handler_with_mocks(mock_task_manager, mock_task_status):
    """创建已初始化的 HistoryHandler"""
    with patch('services.gateway.task.task_manager.get_task_manager', return_value=mock_task_manager), \
         patch('services.gateway.task.task.TaskStatus', mock_task_status):
        handler = HistoryHandler()
        yield handler


@pytest.fixture
def handler_uninitialized():
    """创建未初始化的 HistoryHandler（模拟初始化失败）"""
    with patch('services.gateway.task.task_manager.get_task_manager', side_effect=Exception("Init failed")):
        handler = HistoryHandler()
        yield handler


# ==================== 测试类 ====================

class TestHistoryHandlerInitialization:
    """测试 HistoryHandler 初始化"""
    
    def test_successful_initialization(self, handler_with_mocks):
        """测试成功初始化"""
        assert handler_with_mocks.task_manager is not None
        assert handler_with_mocks.TaskStatus is not None
        assert handler_with_mocks._is_initialized() is True
    
    def test_initialization_failure(self, handler_uninitialized):
        """测试初始化失败"""
        assert handler_uninitialized.task_manager is None
        assert handler_uninitialized._is_initialized() is False


class TestHandleGetRequest:
    """测试 handle_get_request 方法"""
    
    def test_get_history_success_no_limit(self, app, handler_with_mocks, mock_task_manager):
        """测试成功获取历史 - 无 max_items 参数"""
        # 准备测试数据
        mock_history = {
            "prompt-123": {
                "prompt": [1, "prompt-123", {}, {}, []],
                "outputs": {},
                "status": {"status_str": "success", "completed": True, "messages": []},
                "meta": {}
            }
        }
        mock_task_manager.get_history.return_value = mock_history
        
        with app.test_request_context():
            g.user_id = 'user-test'
            response = handler_with_mocks.handle_get_request()
            
            # 验证调用
            mock_task_manager.get_history.assert_called_once_with(max_items=None)
            
            # 验证响应
            assert response.json == mock_history
            assert response.status_code == 200
    
    def test_get_history_success_with_valid_limit(self, app, handler_with_mocks, mock_task_manager):
        """测试成功获取历史 - 带有效 max_items 参数"""
        mock_history = {
            "prompt-1": {"status": {"completed": True}},
            "prompt-2": {"status": {"completed": True}}
        }
        mock_task_manager.get_history.return_value = mock_history
        
        with app.test_request_context('/?max_items=10'):
            g.user_id = 'user-test'
            response = handler_with_mocks.handle_get_request()
            
            mock_task_manager.get_history.assert_called_once_with(max_items=10)
            assert response.json == mock_history
    
    def test_get_history_empty_result(self, app, handler_with_mocks, mock_task_manager):
        """测试空历史记录 - 返回空字典"""
        mock_task_manager.get_history.return_value = {}
        
        with app.test_request_context():
            g.user_id = 'user-test'
            response = handler_with_mocks.handle_get_request()
            
            assert response.json == {}
            assert response.status_code == 200
    
    def test_get_history_uninitialized_handler(self, app, handler_uninitialized):
        """测试初始化失败 - 返回 503"""
        with app.test_request_context():
            g.user_id = 'user-test'
            response, status_code = handler_uninitialized.handle_get_request()
            
            assert response.json == {}
            assert status_code == 503
    
    def test_get_history_invalid_limit_string(self, app, handler_with_mocks, mock_task_manager):
        """测试无效 max_items 参数 - 非数字字符串"""
        mock_task_manager.get_history.return_value = {}
        
        with app.test_request_context('/?max_items=abc'):
            g.user_id = 'user-test'
            response = handler_with_mocks.handle_get_request()
            
            # 无效的 limit 应该被忽略，传递 None
            mock_task_manager.get_history.assert_called_once_with(max_items=None)
    
    def test_get_history_limit_zero(self, app, handler_with_mocks, mock_task_manager):
        """测试 max_items 为 0 - 应该被忽略"""
        mock_task_manager.get_history.return_value = {}
        
        with app.test_request_context('/?max_items=0'):
            g.user_id = 'user-test'
            response = handler_with_mocks.handle_get_request()
            
            mock_task_manager.get_history.assert_called_once_with(max_items=None)
    
    def test_get_history_limit_negative(self, app, handler_with_mocks, mock_task_manager):
        """测试 max_items 为负数 - 应该被忽略"""
        mock_task_manager.get_history.return_value = {}
        
        with app.test_request_context('/?max_items=-5'):
            g.user_id = 'user-test'
            response = handler_with_mocks.handle_get_request()
            
            mock_task_manager.get_history.assert_called_once_with(max_items=None)


class TestParseLimitParam:
    """测试 _parse_limit_param 方法"""
    
    def test_parse_valid_limit(self, app, handler_with_mocks):
        """测试解析有效的 max_items 参数"""
        with app.test_request_context('/?max_items=50'):
            result = handler_with_mocks._parse_max_items_param()
            assert result == 50
    
    def test_parse_no_limit(self, app, handler_with_mocks):
        """测试无 max_items 参数"""
        with app.test_request_context('/'):
            result = handler_with_mocks._parse_max_items_param()
            assert result is None
    
    def test_parse_invalid_limit(self, app, handler_with_mocks):
        """测试无效的 max_items 参数"""
        with app.test_request_context('/?max_items=invalid'):
            result = handler_with_mocks._parse_max_items_param()
            assert result is None
    
    def test_parse_limit_zero(self, app, handler_with_mocks):
        """测试 max_items=0"""
        with app.test_request_context('/?max_items=0'):
            result = handler_with_mocks._parse_max_items_param()
            assert result is None
    
    def test_parse_limit_negative(self, app, handler_with_mocks):
        """测试负数 max_items"""
        with app.test_request_context('/?max_items=-10'):
            result = handler_with_mocks._parse_max_items_param()
            assert result is None


class TestMultiTenantIsolation:
    """测试多租户隔离（集成测试，需要真实的 TaskManager.get_history 逻辑）"""
    
    def test_user_only_sees_own_history(self, app, handler_with_mocks, mock_task_manager):
        """测试用户只能看到自己的历史记录"""
        # TaskManager.get_history 已经实现了用户隔离
        # 这里主要验证正确调用了 get_history
        
        user_history = {
            "prompt-user1": {"status": {"completed": True}}
        }
        mock_task_manager.get_history.return_value = user_history
        
        with app.test_request_context():
            g.user_id = 'user-1'
            response = handler_with_mocks.handle_get_request()
            
            # 验证返回的是当前用户的历史
            assert response.json == user_history
            
            # TaskManager.get_history 内部会通过 _get_current_user_id_from_request()
            # 获取 g.user_id 进行过滤，这里我们验证它被正确调用
            mock_task_manager.get_history.assert_called_once()


class TestDataFormat:
    """测试返回数据格式"""
    
    def test_response_contains_required_fields(self, app, handler_with_mocks, mock_task_manager):
        """测试响应包含必需的字段"""
        complete_history = {
            "prompt-123": {
                "prompt": [1, "prompt-123", {"node1": {}}, {"client_id": "test"}, []],
                "outputs": {
                    "node1": {
                        "images": [
                            {
                                "filename": "output.png",
                                "subfolder": "",
                                "type": "output"
                            }
                        ]
                    }
                },
                "status": {
                    "status_str": "success",
                    "completed": True,
                    "messages": [
                        ["execution_start", {"prompt_id": "prompt-123", "timestamp": 1000}],
                        ["execution_success", {"prompt_id": "prompt-123", "timestamp": 2000}]
                    ]
                },
                "meta": {
                    "node1": {
                        "node_id": "node1",
                        "display_node": "node1",
                        "parent_node": None,
                        "real_node_id": "node1"
                    }
                }
            }
        }
        mock_task_manager.get_history.return_value = complete_history
        
        with app.test_request_context():
            g.user_id = 'user-test'
            response = handler_with_mocks.handle_get_request()
            
            result = response.json
            assert "prompt-123" in result
            
            history_item = result["prompt-123"]
            assert "prompt" in history_item
            assert "outputs" in history_item
            assert "status" in history_item
            assert "meta" in history_item
            
            # 验证不包含 user_id（应该在 TaskManager.get_history 中被过滤）
            assert "user_id" not in history_item
    
    def test_response_for_failed_task(self, app, handler_with_mocks, mock_task_manager):
        """测试失败任务的响应格式"""
        failed_history = {
            "prompt-failed": {
                "prompt": [1, "prompt-failed", {}, {}, []],
                "outputs": {},
                "status": {
                    "status_str": "error",
                    "completed": True,
                    "messages": [
                        ["execution_start", {"prompt_id": "prompt-failed", "timestamp": 1000}],
                        ["execution_error", {
                            "prompt_id": "prompt-failed",
                            "node_id": "node_x",
                            "exception_message": "Error occurred",
                            "timestamp": 2000
                        }]
                    ]
                },
                "meta": {}
            }
        }
        mock_task_manager.get_history.return_value = failed_history
        
        with app.test_request_context():
            g.user_id = 'user-test'
            response = handler_with_mocks.handle_get_request()
            
            result = response.json
            assert "prompt-failed" in result
            assert result["prompt-failed"]["status"]["status_str"] == "error"
            assert result["prompt-failed"]["status"]["completed"] is True


class TestHandlePostRequest:
    """测试 POST /api/history（clear、delete，与 ComfyUI 对齐）"""
    
    def test_post_history_clear_calls_clear_history_and_returns_200(self, app, handler_with_mocks, mock_task_manager):
        """POST body 含 clear: true 时调用 clear_history(current_user) 并返回 200"""
        mock_task_manager.clear_history = Mock(return_value=2)
        with app.test_request_context('/api/history', method='POST', json={"clear": True}):
            g.user_id = 'user-post-clear'
            response = handler_with_mocks.handle_post_request()
        
        assert response[1] == 200
        mock_task_manager.clear_history.assert_called_once_with('user-post-clear')
    
    def test_post_history_delete_calls_delete_history_items_and_returns_200(self, app, handler_with_mocks, mock_task_manager):
        """POST body 含 delete: [id1, id2] 时调用 delete_history_items(ids, current_user) 并返回 200"""
        mock_task_manager.delete_history_items = Mock(return_value=2)
        with app.test_request_context('/api/history', method='POST', json={"delete": ["id1", "id2"]}):
            g.user_id = 'user-post-del'
            response = handler_with_mocks.handle_post_request()
        
        assert response[1] == 200
        mock_task_manager.delete_history_items.assert_called_once_with(["id1", "id2"], 'user-post-del')

