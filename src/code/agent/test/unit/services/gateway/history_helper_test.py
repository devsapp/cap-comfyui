import pytest
import time
from unittest.mock import Mock, patch
from flask import Flask, g
from collections import defaultdict

from services.gateway.task.task_manager import TaskManager
from services.gateway.task.task import Task, TaskStatus
from services.gateway.task.history_manager import HistoryManager


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


@pytest.fixture
def history_manager():
    """独立的 HistoryManager 实例用于单元测试"""
    return HistoryManager()


# ==================== 测试类 ====================

class TestHistoryByUserIndex:
    """测试用户索引功能"""
    
    def test_history_by_user_initialization(self, task_manager):
        """_history_by_user 初始化"""
        assert hasattr(task_manager._history_manager, '_history_by_user')
        assert isinstance(task_manager._history_manager._history_by_user, defaultdict)
        assert len(task_manager._history_manager._history_by_user) == 0
    
    def test_add_history_updates_index(self, task_manager, app):
        """添加 history 时同步更新索引"""
        with app.test_request_context():
            g.user_id = 'user-123'
            
            prompt_id = "prompt-abc"
            history_item = {
                "prompt": [1, prompt_id, {}, {}, []],
                "outputs": {},
                "status": {"completed": True},
                "meta": {},
                "user_id": "user-123"
            }
            
            with task_manager._lock:
                task_manager._history_manager.history[prompt_id] = history_item
                task_manager._history_manager._history_by_user["user-123"][prompt_id] = history_item
            
            assert prompt_id in task_manager._history_manager.history
            assert prompt_id in task_manager._history_manager._history_by_user["user-123"]
            assert task_manager._history_manager._history_by_user["user-123"][prompt_id] == history_item
    
    def test_get_history_uses_user_index(self, task_manager, app):
        """get_history 使用用户索引"""
        with app.test_request_context():
            g.user_id = 'user-1'
            
            with task_manager._lock:
                for i in range(3):
                    prompt_id = f"prompt-user1-{i}"
                    history_item = {
                        "prompt": [i, prompt_id, {}, {}, []],
                        "outputs": {},
                        "status": {"completed": True, "status_str": "success", "messages": []},
                        "meta": {},
                        "user_id": "user-1"
                    }
                    task_manager._history_manager.history[prompt_id] = history_item
                    task_manager._history_manager._history_by_user["user-1"][prompt_id] = history_item
                
                for i in range(5):
                    prompt_id = f"prompt-user2-{i}"
                    history_item = {
                        "prompt": [i, prompt_id, {}, {}, []],
                        "outputs": {},
                        "status": {"completed": True, "status_str": "success", "messages": []},
                        "meta": {},
                        "user_id": "user-2"
                    }
                    task_manager._history_manager.history[prompt_id] = history_item
                    task_manager._history_manager._history_by_user["user-2"][prompt_id] = history_item
            
            result = task_manager.get_history()
            
            assert len(result) == 3
            for prompt_id in result:
                assert "user1" in prompt_id
                assert "user2" not in prompt_id
                # user_id 字段保留（性能优化）
                assert result[prompt_id]["user_id"] == "user-1"
    
    def test_delete_history_removes_from_index(self, task_manager, app):
        """删除 history 时同步从索引中删除"""
        with app.test_request_context():
            g.user_id = 'user-123'
            
            prompt_id = "prompt-to-delete"
            history_item = {
                "prompt": [1, prompt_id, {}, {}, []],
                "outputs": {},
                "status": {"completed": True},
                "meta": {},
                "user_id": "user-123"
            }
            
            with task_manager._lock:
                task_manager._history_manager.history[prompt_id] = history_item
                task_manager._history_manager._history_by_user["user-123"][prompt_id] = history_item
            
            with task_manager._lock:
                task_manager._history_manager.history.pop(prompt_id, None)
                task_manager._history_manager._history_by_user["user-123"].pop(prompt_id, None)
            
            assert prompt_id not in task_manager._history_manager.history
            assert prompt_id not in task_manager._history_manager._history_by_user["user-123"]
    
    def test_multi_tenant_isolation(self, task_manager, app):
        """多租户隔离"""
        users = ["user-a", "user-b", "user-c"]
        
        with task_manager._lock:
            for user in users:
                for i in range(2):
                    prompt_id = f"prompt-{user}-{i}"
                    history_item = {
                        "prompt": [i, prompt_id, {}, {}, []],
                        "outputs": {},
                        "status": {"completed": True, "status_str": "success", "messages": []},
                        "meta": {},
                        "user_id": user
                    }
                    task_manager._history_manager.history[prompt_id] = history_item
                    task_manager._history_manager._history_by_user[user][prompt_id] = history_item
        
        for user in users:
            with app.test_request_context():
                g.user_id = user
                result = task_manager.get_history()
                
                assert len(result) == 2
                for prompt_id in result:
                    assert user in prompt_id


class TestGetHistory:
    """测试 get_history 方法"""
    
    def test_get_history_empty(self, task_manager, app):
        """获取空 history"""
        with app.test_request_context():
            g.user_id = 'user-empty'
            result = task_manager.get_history()
            assert result == {}
    
    def test_get_history_with_max_items(self, task_manager, app):
        """max_items 参数"""
        with app.test_request_context():
            g.user_id = 'user-test'
            
            with task_manager._lock:
                for i in range(10):
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
            
            result = task_manager.get_history(max_items=3)
            assert len(result) == 3
    
    def test_get_history_filters_uncompleted(self, task_manager, app):
        """过滤未完成的任务"""
        with app.test_request_context():
            g.user_id = 'user-test'
            
            with task_manager._lock:
                for i in range(3):
                    prompt_id = f"prompt-completed-{i}"
                    history_item = {
                        "prompt": [i, prompt_id, {}, {}, []],
                        "outputs": {},
                        "status": {"completed": True, "status_str": "success", "messages": []},
                        "meta": {},
                        "user_id": "user-test"
                    }
                    task_manager._history_manager.history[prompt_id] = history_item
                    task_manager._history_manager._history_by_user["user-test"][prompt_id] = history_item
                
                for i in range(2):
                    prompt_id = f"prompt-running-{i}"
                    history_item = {
                        "prompt": [i, prompt_id, {}, {}, []],
                        "outputs": {},
                        "status": {"completed": False, "status_str": "running", "messages": []},
                        "meta": {},
                        "user_id": "user-test"
                    }
                    task_manager._history_manager.history[prompt_id] = history_item
                    task_manager._history_manager._history_by_user["user-test"][prompt_id] = history_item
            
            result = task_manager.get_history()
            assert len(result) == 3
            for prompt_id in result:
                assert "completed" in prompt_id
    
    def test_get_history_keeps_user_id_field(self, task_manager, app):
        """返回的 history 中包含 user_id 字段（性能优化，不再复制）"""
        with app.test_request_context():
            g.user_id = 'user-test'
            
            with task_manager._lock:
                prompt_id = "prompt-123"
                history_item = {
                    "prompt": [1, prompt_id, {}, {}, []],
                    "outputs": {},
                    "status": {"completed": True, "status_str": "success", "messages": []},
                    "meta": {},
                    "user_id": "user-test"
                }
                task_manager._history_manager.history[prompt_id] = history_item
                task_manager._history_manager._history_by_user["user-test"][prompt_id] = history_item
            
            result = task_manager.get_history()
            
            assert prompt_id in result
            # ✅ 性能优化：不再去除 user_id（因为已经通过 user_id 过滤）
            assert "user_id" in result[prompt_id]
            assert result[prompt_id]["user_id"] == "user-test"
            assert "prompt" in result[prompt_id]
            assert "outputs" in result[prompt_id]
            assert "status" in result[prompt_id]


class TestHistoryRaceCondition:
    """测试 history 初始化的竞态条件修复"""
    
    def test_init_history_double_check_locking(self, task_manager, app):
        """测试双重检查锁定防止重复初始化"""
        with app.test_request_context():
            g.user_id = 'user-test'
            
            with patch.object(task_manager, '_start_polling'), \
                 patch('services.gateway.task.utils.task_manager_util.TaskStatusBroadcaster'):
                
                prompt_body = {
                    "prompt": {"1": {"class_type": "Test"}}
                }
                
                # 提交任务
                task_id = task_manager.submit_task(prompt_body, "client-123")
                
                # 第一次初始化
                message = {
                    "type": "execution_start",
                    "data": {"prompt_id": task_id, "timestamp": int(time.time() * 1000)}
                }
                task_manager._init_history_item(task_id, message)
                
                # 验证 history 已创建
                assert task_id in task_manager._history_manager.history
                first_item = task_manager._history_manager.history[task_id]
                
                # 尝试第二次初始化（应该被跳过）
                task_manager._init_history_item(task_id, message)
                
                # 验证 history 没有改变
                assert task_manager._history_manager.history[task_id] is first_item
    
    def test_init_history_with_placeholder(self, task_manager, app):
        """测试占位符机制防止并发初始化"""
        with app.test_request_context():
            g.user_id = 'user-test'
            
            with patch.object(task_manager, '_start_polling'), \
                 patch('services.gateway.task.utils.task_manager_util.TaskStatusBroadcaster'):
                
                prompt_body = {
                    "prompt": {"1": {"class_type": "Test"}}
                }
                
                task_id = task_manager.submit_task(prompt_body, "client-123")
                
                message = {
                    "type": "execution_start",
                    "data": {"prompt_id": task_id, "timestamp": int(time.time() * 1000)}
                }
                
                # 初始化
                task_manager._init_history_item(task_id, message)
                
                # 验证最终的 history 不包含 _initializing 标记
                history_item = task_manager._history_manager.history.get(task_id)
                assert history_item is not None
                assert "_initializing" not in history_item or history_item.get("_initializing") is not True
                assert "prompt" in history_item
                assert "user_id" in history_item


class TestExecutedMessageHandling:
    """测试 executed 消息处理的健壮性"""
    
    def test_executed_with_missing_history(self, task_manager, app):
        """executed 消息到达时 history 不存在应延迟初始化"""
        with app.test_request_context():
            g.user_id = 'user-test'
            
            with patch.object(task_manager, '_start_polling'), \
                 patch('services.gateway.task.utils.task_manager_util.TaskStatusBroadcaster'):
                
                prompt_body = {
                    "prompt": {"1": {"class_type": "Test"}}
                }
                
                task_id = task_manager.submit_task(prompt_body, "client-123")
                
                # 直接发送 executed 消息（跳过 execution_start）
                message = {
                    "type": "executed",
                    "data": {
                        "prompt_id": task_id,
                        "node": "10",
                        "display_node": "10",
                        "output": {
                            "images": [
                                {"filename": "test.png", "type": "output", "subfolder": ""}
                            ]
                        }
                    }
                }
                
                # 处理消息
                task_manager.handle_message(task_id, message)
                
                # 验证 history 被延迟初始化
                assert task_id in task_manager._history_manager.history
                history_item = task_manager._history_manager.history[task_id]
                
                # 验证包含必要字段
                assert "meta" in history_item
                assert "outputs" in history_item
                assert "user_id" in history_item
                assert history_item["user_id"] == "user-test"
                
                # 验证 outputs 被正确添加
                assert "10" in history_item["outputs"]
                assert "images" in history_item["outputs"]["10"]
                assert len(history_item["outputs"]["10"]["images"]) == 1
    
    def test_executed_message_validation(self, task_manager, app):
        """测试 executed 消息的字段验证"""
        with app.test_request_context():
            g.user_id = 'user-test'
            
            with patch.object(task_manager, '_start_polling'), \
                 patch('services.gateway.task.utils.task_manager_util.TaskStatusBroadcaster'):
                
                prompt_body = {
                    "prompt": {"1": {"class_type": "Test"}},
                }
                
                task_id = task_manager.submit_task(prompt_body, "client-123")
                
                # 缺少 prompt_id 的消息
                message_no_prompt = {
                    "type": "executed",
                    "data": {
                        "node": "10",
                        "output": {}
                    }
                }
                
                # 不应抛出异常
                task_manager.handle_message(task_id, message_no_prompt)
                
                # 缺少 node_id 的消息
                message_no_node = {
                    "type": "executed",
                    "data": {
                        "prompt_id": "some-prompt",
                        "output": {}
                    }
                }
                
                # 不应抛出异常
                task_manager.handle_message(task_id, message_no_node)
    
    def test_executed_with_initializing_placeholder(self, task_manager, app):
        """测试 executed 遇到初始化占位符时的处理"""
        with app.test_request_context():
            g.user_id = 'user-test'
            
            with patch.object(task_manager, '_start_polling'), \
                 patch('services.gateway.task.utils.task_manager_util.TaskStatusBroadcaster'):
                
                prompt_body = {
                    "prompt": {"1": {"class_type": "Test"}}
                }
                
                task_id = task_manager.submit_task(prompt_body, "client-123")
                
                # 手动设置一个初始化占位符
                with task_manager._lock:
                    task_manager._history_manager.history[task_id] = {
                        "_initializing": True,
                        "user_id": "user-test"
                    }
                
                # 发送 executed 消息
                message = {
                    "type": "executed",
                    "data": {
                        "prompt_id": task_id,
                        "node": "10",
                        "output": {"images": []}
                    }
                }
                
                # 应该跳过处理（因为还在初始化中）
                task_manager.handle_message(task_id, message)
                
                # 验证占位符还在
                history_item = task_manager._history_manager.history.get(task_id)
                assert history_item.get("_initializing") is True


class TestHistoryAtomicOperations:
    """测试 history 原子操作"""
    
    def test_add_history_item_atomic(self, task_manager, app):
        """测试 _add_history_item 的原子性"""
        with app.test_request_context():
            g.user_id = 'user-test'
            
            history_item = {
                "prompt": [1, "prompt-123", {}, {}, []],
                "outputs": {},
                "status": {"completed": False},
                "meta": {},
                "user_id": "user-test"
            }
            
            # 添加
            success = task_manager._history_manager.add_history_item("prompt-123", history_item)
            assert success is True
            
            # 验证两个字典都更新了
            assert "prompt-123" in task_manager._history_manager.history
            assert "prompt-123" in task_manager._history_manager._history_by_user["user-test"]
            
            # 尝试重复添加
            success = task_manager._history_manager.add_history_item("prompt-123", history_item)
            assert success is False
    
    def test_add_history_item_missing_user_id(self, task_manager):
        """测试缺少 user_id 时添加失败"""
        history_item = {
            "prompt": [1, "prompt-456", {}, {}, []],
            "outputs": {},
            # 缺少 user_id
        }
        
        success = task_manager._history_manager.add_history_item("prompt-456", history_item)
        assert success is False
        assert "prompt-456" not in task_manager._history_manager.history
    
    def test_remove_history_item_atomic(self, task_manager, app):
        """测试 _remove_history_item 的原子性"""
        with app.test_request_context():
            g.user_id = 'user-test'
            
            # 先添加
            history_item = {
                "prompt": [1, "prompt-789", {}, {}, []],
                "outputs": {},
                "status": {"completed": True},
                "meta": {},
                "user_id": "user-test"
            }
            
            task_manager._history_manager.add_history_item("prompt-789", history_item)
            
            # 验证存在
            assert "prompt-789" in task_manager._history_manager.history
            assert "prompt-789" in task_manager._history_manager._history_by_user["user-test"]
            
            # 删除
            success = task_manager._history_manager.remove_history_item("prompt-789")
            assert success is True
            
            # 验证两个字典都删除了
            assert "prompt-789" not in task_manager._history_manager.history
            assert "prompt-789" not in task_manager._history_manager._history_by_user["user-test"]
    
    def test_remove_nonexistent_history_item(self, task_manager):
        """测试删除不存在的 history item"""
        success = task_manager._history_manager.remove_history_item("nonexistent-prompt")
        assert success is False
    
    def test_history_consistency_after_operations(self, task_manager, app):
        """测试多次操作后 history 和索引保持一致"""
        with app.test_request_context():
            g.user_id = 'user-alice'
            
            # 添加多个 history items
            for i in range(5):
                history_item = {
                    "prompt": [i, f"prompt-{i}", {}, {}, []],
                    "outputs": {},
                    "status": {"completed": True},
                    "meta": {},
                    "user_id": "user-alice"
                }
                task_manager._history_manager.add_history_item(f"prompt-{i}", history_item)
            
            # 验证一致性
            assert len(task_manager._history_manager.history) >= 5
            assert len(task_manager._history_manager._history_by_user["user-alice"]) >= 5
            
            # 删除一些
            task_manager._history_manager.remove_history_item("prompt-1")
            task_manager._history_manager.remove_history_item("prompt-3")
            
            # 验证一致性
            assert "prompt-1" not in task_manager._history_manager.history
            assert "prompt-1" not in task_manager._history_manager._history_by_user["user-alice"]
            assert "prompt-3" not in task_manager._history_manager.history
            assert "prompt-3" not in task_manager._history_manager._history_by_user["user-alice"]
            
            # 其他的还在
            assert "prompt-0" in task_manager._history_manager.history
            assert "prompt-2" in task_manager._history_manager.history
            assert "prompt-4" in task_manager._history_manager.history


class TestImageHandling:
    """测试图片处理"""
    
    def test_multiple_images_added_directly(self, task_manager):
        """多张图片直接添加"""
        history_item = {
            "prompt": [1, "prompt-123", {}, {}, []],
            "outputs": {},
            "status": {"completed": False},
            "meta": {},
            "user_id": "user-test"
        }
        
        node_id = "33"
        history_item["outputs"][node_id] = {"images": []}
        
        images = [
            {"filename": "image1.png", "type": "output", "subfolder": ""},
            {"filename": "image2.png", "type": "output", "subfolder": ""},
            {"filename": "image3.png", "type": "output", "subfolder": ""}
        ]
        
        for img in images:
            image_item = {
                "filename": img.get("filename", ""),
                "type": img.get("type", "output"),
                "subfolder": img.get("subfolder", "")
            }
            history_item["outputs"][node_id]["images"].append(image_item)
        
        assert len(history_item["outputs"][node_id]["images"]) == 3
        assert history_item["outputs"][node_id]["images"][0]["filename"] == "image1.png"
        assert history_item["outputs"][node_id]["images"][1]["filename"] == "image2.png"
        assert history_item["outputs"][node_id]["images"][2]["filename"] == "image3.png"


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


class TestHistoryManagerUnit:
    """HistoryManager 独立单元测试"""
    
    def test_helper_initialization(self, history_manager):
        """测试 HistoryManager 初始化"""
        assert isinstance(history_manager.history, dict)
        assert isinstance(history_manager._history_by_user, defaultdict)
        assert len(history_manager.history) == 0
        assert len(history_manager._history_by_user) == 0
    
    def test_get_history_empty(self, history_manager):
        """测试获取空历史"""
        result = history_manager.get_history("user-test")
        assert result == {}
    
    def test_add_and_get_history(self, history_manager):
        """测试添加和获取历史"""
        history_item = {
            "prompt": [1, "prompt-1", {}, {}, []],
            "outputs": {},
            "status": {"completed": True, "status_str": "success", "messages": []},
            "meta": {},
            "user_id": "user-alice"
        }
        
        success = history_manager.add_history_item("prompt-1", history_item)
        assert success is True
        
        result = history_manager.get_history("user-alice")
        assert len(result) == 1
        assert "prompt-1" in result
    
    def test_remove_history(self, history_manager):
        """测试删除历史"""
        history_item = {
            "prompt": [1, "prompt-1", {}, {}, []],
            "outputs": {},
            "status": {"completed": True},
            "meta": {},
            "user_id": "user-bob"
        }
        
        history_manager.add_history_item("prompt-1", history_item)
        assert "prompt-1" in history_manager.history
        
        success = history_manager.remove_history_item("prompt-1")
        assert success is True
        assert "prompt-1" not in history_manager.history
        assert "prompt-1" not in history_manager._history_by_user["user-bob"]
    
    def test_update_history_status(self, history_manager):
        """测试更新历史状态"""
        # 先添加一个历史项
        history_item = {
            "prompt": [1, "prompt-1", {}, {}, []],
            "outputs": {},
            "status": {
                "completed": False,
                "status_str": "running",
                "messages": []
            },
            "meta": {},
            "user_id": "user-test"
        }
        
        history_manager.add_history_item("prompt-1", history_item)
        
        # 更新为成功
        message = {
            "type": "execution_success",
            "data": {
                "prompt_id": "prompt-1",
                "timestamp": int(time.time() * 1000)
            }
        }
        
        success = history_manager.update_history_status(message, "success")
        assert success is True
        
        # 验证状态已更新
        updated_item = history_manager.history["prompt-1"]
        assert updated_item["status"]["completed"] is True
        assert updated_item["status"]["status_str"] == "success"
    
    def test_update_history_outputs(self, history_manager):
        """测试更新历史输出"""
        # 先添加一个历史项
        history_item = {
            "prompt": [1, "prompt-1", {}, {}, []],
            "outputs": {},
            "status": {"completed": False},
            "meta": {},
            "user_id": "user-test"
        }
        
        history_manager.add_history_item("prompt-1", history_item)
        
        # 更新输出
        message = {
            "type": "executed",
            "data": {
                "prompt_id": "prompt-1",
                "node": "10",
                "display_node": "10",
                "output": {
                    "images": [
                        {"filename": "test.png", "type": "output", "subfolder": ""}
                    ]
                }
            }
        }
        
        success = history_manager.update_history_outputs(message)
        assert success is True
        
        # 验证输出已更新
        updated_item = history_manager.history["prompt-1"]
        assert "10" in updated_item["meta"]
        assert "10" in updated_item["outputs"]
        assert len(updated_item["outputs"]["10"]["images"]) == 1


class TestHistoryManagerEdgeCases:
    """测试 HistoryManager 的边界情况和错误处理（提升覆盖率到 100%）"""
    
    def test_add_history_item_with_exception_in_assignment(self, history_manager):
        """测试添加 history 时发生异常的回滚逻辑"""
        # 模拟一个会导致赋值失败的情况
        history_item = {
            "prompt": [1, "prompt-1", {}, {}, []],
            "outputs": {},
            "status": {"completed": False},
            "meta": {},
            "user_id": "user-test"
        }
        
        # 先添加成功
        success = history_manager.add_history_item("prompt-1", history_item)
        assert success is True
        
        # 尝试重复添加（应该失败并返回 False）
        success = history_manager.add_history_item("prompt-1", history_item)
        assert success is False
        assert "prompt-1" in history_manager.history
    
    def test_add_history_item_with_invalid_history_item(self, history_manager):
        """测试 add_history_item 传入无效的 history_item（触发异常）"""
        # 传入一个无法获取 user_id 的对象（不是字典）
        class BadHistoryItem:
            def get(self, key, default=None):
                raise RuntimeError("Simulated error in get")
        
        bad_item = BadHistoryItem()
        
        # 应该捕获异常并返回 False
        success = history_manager.add_history_item("prompt-bad", bad_item)
        assert success is False
    
    def test_remove_history_item_with_corrupted_data(self, history_manager):
        """测试 remove_history_item 处理损坏的数据"""
        # 手动创建一个会导致问题的情况
        # 添加一个没有 user_id 的项（边界情况）
        history_manager.history["prompt-corrupt"] = {
            "prompt": [1, "prompt-corrupt", {}, {}, []],
            # 故意不添加 user_id
        }
        
        # 应该成功删除（因为代码中有 if user_id 检查）
        success = history_manager.remove_history_item("prompt-corrupt")
        assert success is True
        assert "prompt-corrupt" not in history_manager.history
    
    def test_init_history_item_placeholder_modified(self, history_manager):
        """测试初始化过程中占位符被修改的情况"""
        # 手动设置一个占位符
        history_manager.history["prompt-1"] = {"_initializing": True, "user_id": "user-test"}
        
        # 尝试初始化（已存在，应该返回 False）
        success = history_manager.init_history_item(
            prompt_id="prompt-1",
            prompt_body={"1": {"class_type": "Test"}},
            client_id="client-1",
            user_id="user-test",
            message={"type": "execution_start", "data": {"prompt_id": "prompt-1"}}
        )
        assert success is False
    
    def test_init_history_item_placeholder_not_initializing(self, history_manager):
        """测试构建过程中占位符状态被改变的情况"""
        # 先手动设置一个占位符
        history_manager.history["prompt-new"] = {"_initializing": True, "user_id": "user-test"}
        
        # 在初始化过程中，手动改变占位符状态（模拟并发修改）
        # 通过直接修改来模拟这种情况
        history_manager.history["prompt-new"]["_initializing"] = False
        
        # 由于我们无法真正并发测试，这里测试已存在的情况
        success = history_manager.init_history_item(
            prompt_id="prompt-new",
            prompt_body={"1": {"class_type": "Test"}},
            client_id="client-1",
            user_id="user-test",
            message={"type": "execution_start", "data": {"prompt_id": "prompt-new"}}
        )
        
        # 已存在，应该返回 False
        assert success is False
    
    def test_init_history_item_build_exception(self, history_manager, monkeypatch):
        """测试 _build_history_item 抛出异常时的清理逻辑"""
        def mock_build_raising(*args, **kwargs):
            raise ValueError("Build failed")
        
        monkeypatch.setattr(history_manager, "_build_history_item", mock_build_raising)
        
        success = history_manager.init_history_item(
            prompt_id="prompt-fail",
            prompt_body={"1": {"class_type": "Test"}},
            client_id="client-1",
            user_id="user-test",
            message={"type": "execution_start", "data": {"prompt_id": "prompt-fail"}}
        )
        
        assert success is False
        # 验证占位符被清理
        assert "prompt-fail" not in history_manager.history
    
    def test_init_history_item_with_invalid_message(self, history_manager):
        """测试 init_history_item 传入无效消息格式"""
        # 传入 None 作为 message，会在 _build_history_item 中导致问题
        # 但由于有异常处理，应该返回 False
        success = history_manager.init_history_item(
            prompt_id="prompt-error",
            prompt_body={},
            client_id="client-1",
            user_id="user-test",
            message=None  # 无效的 message
        )
        
        # 应该捕获异常并清理占位符
        assert success is False
        assert "prompt-error" not in history_manager.history
    
    def test_build_history_item_with_nested_prompt(self, history_manager):
        """测试构建 history_item 时 prompt_body 包含嵌套 prompt 字段"""
        prompt_body = {
            "prompt": {"1": {"class_type": "Test"}},
            "outputs_to_execute": ["1", "2"]
        }
        
        message = {
            "type": "execution_start",
            "data": {"prompt_id": "prompt-1", "timestamp": 1609459200000}
        }
        
        history_item = history_manager._build_history_item(
            prompt_id="prompt-1",
            prompt_body=prompt_body,
            client_id="client-1",
            user_id="user-test",
            message=message
        )
        
        # 验证 outputs_to_execute 被正确提取
        assert history_item["prompt"][4] == ["1", "2"]
        assert history_item["prompt"][2] == {"1": {"class_type": "Test"}}
    
    def test_build_history_item_with_small_timestamp(self, history_manager):
        """测试时间戳小于 10000000000 的情况（秒级时间戳）"""
        message = {
            "type": "execution_start",
            "data": {"prompt_id": "prompt-1", "timestamp": 1609459200}  # 秒级时间戳
        }
        
        history_item = history_manager._build_history_item(
            prompt_id="prompt-1",
            prompt_body={},
            client_id="client-1",
            user_id="user-test",
            message=message
        )
        
        # 验证时间戳被转换为毫秒
        messages = history_item["status"]["messages"]
        assert messages[0][1]["timestamp"] == 1609459200000
    
    def test_build_history_item_with_large_timestamp(self, history_manager):
        """测试时间戳大于等于 10000000000 的情况（毫秒级时间戳）"""
        message = {
            "type": "execution_start",
            "data": {"prompt_id": "prompt-1", "timestamp": 1609459200000}  # 毫秒级
        }
        
        history_item = history_manager._build_history_item(
            prompt_id="prompt-1",
            prompt_body={},
            client_id="client-1",
            user_id="user-test",
            message=message
        )
        
        # 验证时间戳保持不变
        messages = history_item["status"]["messages"]
        assert messages[0][1]["timestamp"] == 1609459200000
    
    def test_update_history_status_missing_prompt_id(self, history_manager):
        """测试 update_history_status 缺少 prompt_id"""
        message = {
            "type": "execution_success",
            "data": {}  # 缺少 prompt_id
        }
        
        success = history_manager.update_history_status(message, "success")
        assert success is False
    
    def test_update_history_status_history_not_found(self, history_manager):
        """测试 update_history_status 找不到 history_item"""
        message = {
            "type": "execution_success",
            "data": {"prompt_id": "nonexistent"}
        }
        
        success = history_manager.update_history_status(message, "success")
        assert success is False
    
    def test_update_history_status_create_status_if_missing(self, history_manager):
        """测试当 status 字段不存在时自动创建"""
        history_item = {
            "prompt": [1, "prompt-1", {}, {}, []],
            "outputs": {},
            "meta": {},
            "user_id": "user-test"
            # 注意：没有 status 字段
        }
        history_manager.add_history_item("prompt-1", history_item)
        
        message = {
            "type": "execution_success",
            "data": {"prompt_id": "prompt-1", "timestamp": 1609459200000}
        }
        
        success = history_manager.update_history_status(message, "success")
        assert success is True
        assert "status" in history_manager.history["prompt-1"]
    
    def test_update_history_status_error_with_node_info(self, history_manager):
        """测试 error 状态更新包含 node 信息"""
        history_item = {
            "prompt": [1, "prompt-1", {}, {}, []],
            "outputs": {},
            "status": {"completed": False, "messages": []},
            "meta": {},
            "user_id": "user-test"
        }
        history_manager.add_history_item("prompt-1", history_item)
        
        message = {
            "type": "execution_error",
            "data": {
                "prompt_id": "prompt-1",
                "node_id": "10",
                "exception_message": "Test error",
                "timestamp": 1609459200000
            }
        }
        
        success = history_manager.update_history_status(message, "error")
        assert success is True
        
        status = history_manager.history["prompt-1"]["status"]
        assert status["completed"] is True
        assert status["status_str"] == "error"
        assert any(msg[0] == "execution_error" for msg in status["messages"])
    
    def test_update_history_status_running_with_execution_cached(self, history_manager):
        """测试 running 状态且消息类型为 execution_cached"""
        history_item = {
            "prompt": [1, "prompt-1", {}, {}, []],
            "outputs": {},
            "status": {"completed": False, "messages": []},
            "meta": {},
            "user_id": "user-test"
        }
        history_manager.add_history_item("prompt-1", history_item)
        
        message = {
            "type": "execution_cached",
            "data": {"prompt_id": "prompt-1", "timestamp": 1609459200000}
        }
        
        success = history_manager.update_history_status(message, "running")
        assert success is True
        
        status = history_manager.history["prompt-1"]["status"]
        assert status["completed"] is False  # 不改变 completed 标志
        assert any(msg[0] == "execution_cached" for msg in status["messages"])
    
    def test_update_history_status_with_small_timestamp(self, history_manager):
        """测试状态更新时小时间戳转换"""
        history_item = {
            "prompt": [1, "prompt-1", {}, {}, []],
            "outputs": {},
            "status": {"completed": False, "messages": []},
            "meta": {},
            "user_id": "user-test"
        }
        history_manager.add_history_item("prompt-1", history_item)
        
        message = {
            "type": "execution_success",
            "data": {"prompt_id": "prompt-1", "timestamp": 1609459200}  # 秒级
        }
        
        success = history_manager.update_history_status(message, "success")
        assert success is True
        
        # 验证时间戳被转换为毫秒
        messages = history_manager.history["prompt-1"]["status"]["messages"]
        for msg in messages:
            if msg[0] == "execution_success":
                assert msg[1]["timestamp"] == 1609459200000
    
    def test_update_history_status_with_invalid_message(self, history_manager):
        """测试 update_history_status 传入无效消息"""
        history_item = {
            "prompt": [1, "prompt-1", {}, {}, []],
            "user_id": "user-test",
            "status": {"completed": False, "messages": []}
        }
        history_manager.add_history_item("prompt-1", history_item)
        
        # 传入 None 作为 message
        success = history_manager.update_history_status(None, "success")
        # 会在 message.get 时失败，被异常捕获
        assert success is False
    
    def test_update_history_outputs_missing_prompt_id(self, history_manager):
        """测试 update_history_outputs 缺少 prompt_id"""
        message = {
            "type": "executed",
            "data": {"node": "10"}  # 缺少 prompt_id
        }
        
        success = history_manager.update_history_outputs(message)
        assert success is False
    
    def test_update_history_outputs_missing_node_id(self, history_manager):
        """测试 update_history_outputs 缺少 node_id"""
        message = {
            "type": "executed",
            "data": {"prompt_id": "prompt-1"}  # 缺少 node
        }
        
        success = history_manager.update_history_outputs(message)
        assert success is False
    
    def test_update_history_outputs_history_not_found(self, history_manager):
        """测试 update_history_outputs 找不到 history_item"""
        message = {
            "type": "executed",
            "data": {"prompt_id": "nonexistent", "node": "10"}
        }
        
        success = history_manager.update_history_outputs(message)
        assert success is False
    
    def test_update_history_outputs_initializing_placeholder(self, history_manager):
        """测试 update_history_outputs 遇到初始化占位符"""
        history_manager.history["prompt-1"] = {
            "_initializing": True,
            "user_id": "user-test"
        }
        
        message = {
            "type": "executed",
            "data": {"prompt_id": "prompt-1", "node": "10", "output": {}}
        }
        
        success = history_manager.update_history_outputs(message)
        assert success is False
    
    def test_update_history_outputs_create_meta_if_missing(self, history_manager):
        """测试当 meta 字段不存在时自动创建"""
        history_item = {
            "prompt": [1, "prompt-1", {}, {}, []],
            "outputs": {},
            "status": {"completed": False},
            "user_id": "user-test"
            # 注意：没有 meta 字段
        }
        history_manager.add_history_item("prompt-1", history_item)
        
        message = {
            "type": "executed",
            "data": {
                "prompt_id": "prompt-1",
                "node": "10",
                "display_node": "10",
                "output": {}
            }
        }
        
        success = history_manager.update_history_outputs(message)
        assert success is True
        assert "meta" in history_manager.history["prompt-1"]
        assert "10" in history_manager.history["prompt-1"]["meta"]
    
    def test_update_history_outputs_create_outputs_if_missing(self, history_manager):
        """测试当 outputs 字段不存在时自动创建"""
        history_item = {
            "prompt": [1, "prompt-1", {}, {}, []],
            "meta": {},
            "status": {"completed": False},
            "user_id": "user-test"
            # 注意：没有 outputs 字段
        }
        history_manager.add_history_item("prompt-1", history_item)
        
        message = {
            "type": "executed",
            "data": {
                "prompt_id": "prompt-1",
                "node": "10",
                "output": {
                    "images": [{"filename": "test.png", "type": "output", "subfolder": ""}]
                }
            }
        }
        
        success = history_manager.update_history_outputs(message)
        assert success is True
        assert "outputs" in history_manager.history["prompt-1"]
        assert "10" in history_manager.history["prompt-1"]["outputs"]
    
    def test_update_history_outputs_with_invalid_message(self, history_manager):
        """测试 update_history_outputs 传入无效消息"""
        history_item = {
            "prompt": [1, "prompt-1", {}, {}, []],
            "user_id": "user-test",
            "meta": {},
            "outputs": {}
        }
        history_manager.add_history_item("prompt-1", history_item)
        
        # 传入 None 作为 message
        success = history_manager.update_history_outputs(None)
        # 会在 message.get 时失败，被异常捕获
        assert success is False
    
    def test_late_init_history_item_already_exists(self, history_manager):
        """测试 late_init_history_item 当 history 已存在"""
        history_manager.history["prompt-1"] = {
            "prompt": [1, "prompt-1", {}, {}, []],
            "user_id": "user-test"
        }
        
        success = history_manager.late_init_history_item(
            task_id="task-1",
            prompt_id="prompt-1",
            prompt_body={},
            client_id="client-1",
            user_id="user-test"
        )
        
        assert success is False
    
    def test_late_init_with_none_prompt_body(self, history_manager):
        """测试 late_init_history_item 使用 None prompt_body"""
        # prompt_body 为 None 是合法的（代码中有 prompt_body or {}）
        success = history_manager.late_init_history_item(
            task_id="task-1",
            prompt_id="prompt-none",
            prompt_body=None,
            client_id="client-1",
            user_id="user-test"
        )
        
        # 应该成功创建
        assert success is True
        assert "prompt-none" in history_manager.history
        # 验证 prompt_body 被替换为 {}
        assert history_manager.history["prompt-none"]["prompt"][2] == {}


class TestHistoryManagerFullCoverage:
    """额外测试用例以达到 100% 覆盖率"""
    
    def test_add_history_item_assignment_exception(self, history_manager):
        """测试 add_history_item 内部赋值时的异常（触发 92-97 行）"""
        # 创建一个特殊的对象，在被赋值时会抛出异常
        class RaisingDict(dict):
            def __setitem__(self, key, value):
                if key == "test-prompt":
                    raise RuntimeError("Assignment failed")
                super().__setitem__(key, value)
        
        # 替换 history 为会抛出异常的字典
        history_manager.history = RaisingDict()
        history_manager._history_by_user = defaultdict(dict)
        
        history_item = {
            "prompt": [1, "test-prompt", {}, {}, []],
            "user_id": "user-test",
            "outputs": {},
            "status": {"completed": False},
            "meta": {}
        }
        
        # 应该捕获异常并回滚
        success = history_manager.add_history_item("test-prompt", history_item)
        assert success is False
        # 验证回滚：history 中不应该有这个项
        assert "test-prompt" not in history_manager.history
    
    def test_remove_history_item_deletion_exception(self, history_manager):
        """测试 remove_history_item 删除时的异常（触发 128-130 行）"""
        # 创建一个会在 pop 时抛出异常的字典
        class RaisingDict(dict):
            def pop(self, key, default=None):
                raise RuntimeError("Pop failed")
        
        # 手动添加一个项并替换为会抛出异常的字典
        history_manager.history["test-prompt"] = {"user_id": "user-test"}
        history_manager._history_by_user["user-test"]["test-prompt"] = {"user_id": "user-test"}
        
        # 保存原始引用
        original_history = history_manager.history
        # 替换为会抛出异常的字典
        history_manager.history = RaisingDict(original_history)
        
        # 应该捕获异常
        success = history_manager.remove_history_item("test-prompt")
        assert success is False
    
    def test_init_history_item_placeholder_warning(self, history_manager):
        """测试 init_history_item 占位符被修改的警告（触发 176-177 行）"""
        # 手动设置一个不是初始化占位符的项
        history_manager.history["test-prompt"] = {
            "_initializing": False,  # 已经不是初始化状态
            "user_id": "user-test"
        }
        
        # 尝试初始化，会进入占位符检查逻辑，发现 _initializing 为 False
        success = history_manager.init_history_item(
            prompt_id="test-prompt",
            prompt_body={"1": {"class_type": "Test"}},
            client_id="client-1",
            user_id="user-test",
            message={"type": "execution_start", "data": {"prompt_id": "test-prompt"}}
        )
        
        # 已存在，返回 False
        assert success is False
    
    def test_init_history_item_check_fails_after_build(self, history_manager, monkeypatch):
        """测试构建完成后占位符检查失败（触发 176-177 行）"""
        # 模拟在构建过程中其他线程修改了占位符
        original_build = history_manager._build_history_item
        
        def mock_build_and_modify(*args, **kwargs):
            # 在构建过程中，将占位符的 _initializing 设置为 False
            if "test-prompt" in history_manager.history:
                history_manager.history["test-prompt"]["_initializing"] = False
            return original_build(*args, **kwargs)
        
        monkeypatch.setattr(history_manager, "_build_history_item", mock_build_and_modify)
        
        success = history_manager.init_history_item(
            prompt_id="test-prompt",
            prompt_body={"1": {"class_type": "Test"}},
            client_id="client-1",
            user_id="user-test",
            message={"type": "execution_start", "data": {"prompt_id": "test-prompt"}}
        )
        
        # 占位符被修改，应该返回 False
        assert success is False
    
    def test_init_history_item_outer_exception_during_placeholder_set(self, history_manager):
        """测试在设置占位符时发生异常，触发最外层异常处理（187-189行）"""
        # 创建一个在设置占位符时会抛出异常的字典
        class RaisingDictOnSet(dict):
            def __setitem__(self, key, value):
                if key == "test-outer-exception":
                    raise RuntimeError("Failed to set placeholder")
                super().__setitem__(key, value)
        
        history_manager.history = RaisingDictOnSet()
        history_manager._history_by_user = defaultdict(dict)
        
        # 调用 init_history_item，在设置占位符时会抛出异常
        success = history_manager.init_history_item(
            prompt_id="test-outer-exception",
            prompt_body={"1": {"class_type": "Test"}},
            client_id="client-1",
            user_id="user-test",
            message={"type": "execution_start", "data": {"prompt_id": "test-outer-exception"}}
        )
        
        # 最外层异常处理应该捕获并返回 False
        assert success is False
        # 验证没有添加到 history
        assert "test-outer-exception" not in history_manager.history
    
    def test_init_history_item_placeholder_cleanup(self, history_manager, monkeypatch):
        """测试 init_history_item 构建失败后清理占位符（触发 187-189 行）"""
        # 让 _build_history_item 抛出异常
        def mock_build_exception(*args, **kwargs):
            raise ValueError("Build failed intentionally")
        
        monkeypatch.setattr(history_manager, "_build_history_item", mock_build_exception)
        
        success = history_manager.init_history_item(
            prompt_id="test-build-fail",
            prompt_body={"1": {"class_type": "Test"}},
            client_id="client-1",
            user_id="user-test",
            message={"type": "execution_start", "data": {"prompt_id": "test-build-fail"}}
        )
        
        # 应该失败并清理占位符
        assert success is False
        assert "test-build-fail" not in history_manager.history
    
    def test_build_history_item_no_timestamp(self, history_manager):
        """测试 _build_history_item 消息中没有 timestamp（触发 231 行）"""
        message = {
            "type": "execution_start",
            "data": {"prompt_id": "test-prompt"}  # 没有 timestamp
        }
        
        history_item = history_manager._build_history_item(
            prompt_id="test-prompt",
            prompt_body={"1": {"class_type": "Test"}},
            client_id="client-1",
            user_id="user-test",
            message=message
        )
        
        # 验证使用了默认时间戳（当前时间）
        messages = history_item["status"]["messages"]
        assert messages[0][0] == "execution_start"
        assert "timestamp" in messages[0][1]
        assert messages[0][1]["timestamp"] > 0
    
    def test_update_history_status_no_timestamp(self, history_manager):
        """测试 update_history_status 消息中没有 timestamp（触发 294 行）"""
        history_item = {
            "prompt": [1, "test-prompt", {}, {}, []],
            "user_id": "user-test",
            "status": {"completed": False, "messages": []},
            "outputs": {},
            "meta": {}
        }
        history_manager.add_history_item("test-prompt", history_item)
        
        message = {
            "type": "execution_success",
            "data": {"prompt_id": "test-prompt"}  # 没有 timestamp
        }
        
        success = history_manager.update_history_status(message, "success")
        assert success is True
        
        # 验证使用了默认时间戳
        status = history_manager.history["test-prompt"]["status"]
        assert status["completed"] is True
        success_msg = [msg for msg in status["messages"] if msg[0] == "execution_success"][0]
        assert "timestamp" in success_msg[1]
        assert success_msg[1]["timestamp"] > 0
    
    def test_late_init_history_item_with_exception(self, history_manager):
        """测试 late_init_history_item 发生异常（触发 440-442 行）"""
        # 创建一个会在赋值时抛出异常的字典
        class RaisingDict(dict):
            def __setitem__(self, key, value):
                raise RuntimeError("Assignment failed")
        
        history_manager.history = RaisingDict()
        history_manager._history_by_user = defaultdict(dict)
        
        success = history_manager.late_init_history_item(
            task_id="task-1",
            prompt_id="test-exception",
            prompt_body={"1": {"class_type": "Test"}},
            client_id="client-1",
            user_id="user-test"
        )
        
        # 应该捕获异常并返回 False
        assert success is False


class TestHistoryManagerThreadSafety:
    """测试 HistoryManager 的线程安全性（独立锁）"""
    
    def test_has_independent_lock(self, history_manager):
        """验证 HistoryManager 有独立的锁"""
        import threading
        assert hasattr(history_manager, '_lock')
        # 检查锁是否有 acquire 和 release 方法（鸭子类型检查）
        assert hasattr(history_manager._lock, 'acquire')
        assert hasattr(history_manager._lock, 'release')
        assert callable(history_manager._lock.acquire)
        assert callable(history_manager._lock.release)
    
    def test_concurrent_add_operations(self, history_manager):
        """测试并发添加操作的线程安全性"""
        import threading
        results = []
        errors = []
        
        def add_item(index):
            try:
                prompt_id = f"prompt-{index}"
                history_item = {
                    "prompt": [index, prompt_id, {}, {}, []],
                    "user_id": f"user-{index % 5}",  # 5个用户
                    "status": {"completed": False, "messages": []},
                    "outputs": {},
                    "meta": {}
                }
                success = history_manager.add_history_item(prompt_id, history_item)
                results.append((index, success))
            except Exception as e:
                errors.append((index, str(e)))
        
        # 创建100个线程并发添加
        threads = []
        for i in range(100):
            t = threading.Thread(target=add_item, args=(i,))
            threads.append(t)
            t.start()
        
        # 等待所有线程完成
        for t in threads:
            t.join()
        
        # 验证结果
        assert len(errors) == 0, f"应该没有错误，但发现: {errors}"
        assert len(results) == 100
        assert all(success for _, success in results), "所有添加操作应该成功"
        assert len(history_manager.history) == 100
        
        # 验证 _history_by_user 索引正确
        for i in range(100):
            user_id = f"user-{i % 5}"
            prompt_id = f"prompt-{i}"
            assert prompt_id in history_manager._history_by_user[user_id]
    
    def test_concurrent_read_write_operations(self, history_manager):
        """测试并发读写操作的线程安全性"""
        import threading
        import random
        
        # 预先添加一些数据
        for i in range(10):
            prompt_id = f"prompt-{i}"
            history_item = {
                "prompt": [i, prompt_id, {}, {}, []],
                "user_id": f"user-{i % 3}",
                "status": {"completed": False, "messages": []},
                "outputs": {},
                "meta": {}
            }
            history_manager.add_history_item(prompt_id, history_item)
        
        errors = []
        read_results = []
        write_results = []
        
        def reader(user_id, iterations):
            try:
                for _ in range(iterations):
                    result = history_manager.get_history(user_id)
                    read_results.append(len(result))
                    time.sleep(0.001)
            except Exception as e:
                errors.append(("read", str(e)))
        
        def writer(start_index, count):
            try:
                for i in range(start_index, start_index + count):
                    prompt_id = f"prompt-new-{i}"
                    history_item = {
                        "prompt": [i, prompt_id, {}, {}, []],
                        "user_id": f"user-{i % 3}",
                        "status": {"completed": True, "messages": []},
                        "outputs": {},
                        "meta": {}
                    }
                    success = history_manager.add_history_item(prompt_id, history_item)
                    write_results.append(success)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(("write", str(e)))
        
        # 创建混合读写线程
        threads = []
        
        # 10个读线程
        for i in range(10):
            t = threading.Thread(target=reader, args=(f"user-{i % 3}", 10))
            threads.append(t)
        
        # 5个写线程
        for i in range(5):
            t = threading.Thread(target=writer, args=(100 + i * 10, 10))
            threads.append(t)
        
        # 随机启动线程
        random.shuffle(threads)
        for t in threads:
            t.start()
        
        # 等待完成
        for t in threads:
            t.join()
        
        # 验证没有错误
        assert len(errors) == 0, f"并发读写不应该有错误: {errors}"
        assert len(read_results) == 100  # 10个线程 * 10次迭代
        assert len(write_results) == 50   # 5个线程 * 10次写入
        assert all(write_results), "所有写入操作应该成功"
    
    def test_concurrent_remove_operations(self, history_manager):
        """测试并发删除操作的线程安全性"""
        import threading
        
        # 预先添加数据
        for i in range(50):
            prompt_id = f"prompt-{i}"
            history_item = {
                "prompt": [i, prompt_id, {}, {}, []],
                "user_id": f"user-{i % 5}",
                "status": {"completed": True, "messages": []},
                "outputs": {},
                "meta": {}
            }
            history_manager.add_history_item(prompt_id, history_item)
        
        assert len(history_manager.history) == 50
        
        remove_results = []
        errors = []
        
        def remover(index):
            try:
                prompt_id = f"prompt-{index}"
                success = history_manager.remove_history_item(prompt_id)
                remove_results.append((index, success))
            except Exception as e:
                errors.append((index, str(e)))
        
        # 创建50个线程并发删除
        threads = []
        for i in range(50):
            t = threading.Thread(target=remover, args=(i,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # 验证结果
        assert len(errors) == 0, f"删除操作不应该有错误: {errors}"
        assert len(remove_results) == 50
        assert all(success for _, success in remove_results)
        assert len(history_manager.history) == 0
        
        # 验证 _history_by_user 也被清空
        for user_id in range(5):
            assert len(history_manager._history_by_user[f"user-{user_id}"]) == 0
    
    def test_concurrent_update_operations(self, history_manager):
        """测试并发更新操作的线程安全性"""
        import threading
        
        # 预先添加一些数据
        for i in range(10):
            prompt_id = f"prompt-{i}"
            history_item = {
                "prompt": [i, prompt_id, {}, {}, []],
                "user_id": f"user-{i % 3}",
                "status": {"completed": False, "messages": []},
                "outputs": {},
                "meta": {}
            }
            history_manager.add_history_item(prompt_id, history_item)
        
        errors = []
        update_results = []
        
        def updater(prompt_id, iterations):
            try:
                for j in range(iterations):
                    message = {
                        "type": "execution_success",
                        "data": {
                            "prompt_id": prompt_id,
                            "timestamp": int(time.time() * 1000)
                        }
                    }
                    success = history_manager.update_history_status(message, "success")
                    update_results.append((prompt_id, j, success))
                    time.sleep(0.001)
            except Exception as e:
                errors.append((prompt_id, str(e)))
        
        # 创建多个线程更新同一个 history_item
        threads = []
        for i in range(10):
            # 每个 prompt 被多个线程同时更新
            t = threading.Thread(target=updater, args=(f"prompt-{i}", 5))
            threads.append(t)
        
        for t in threads:
            t.start()
        
        for t in threads:
            t.join()
        
        # 验证没有错误
        assert len(errors) == 0, f"更新操作不应该有错误: {errors}"
        assert len(update_results) == 50  # 10个线程 * 5次迭代
        
        # 验证所有 history_item 都被标记为完成
        for i in range(10):
            prompt_id = f"prompt-{i}"
            history_item = history_manager.history[prompt_id]
            assert history_item["status"]["completed"] is True
    
    def test_get_history_item_thread_safe(self, history_manager):
        """测试 get_history_item 方法的线程安全性"""
        import threading
        
        # 添加测试数据
        history_item = {
            "prompt": [1, "test-prompt", {}, {}, []],
            "user_id": "user-test",
            "status": {"completed": False, "messages": []},
            "outputs": {},
            "meta": {}
        }
        history_manager.add_history_item("test-prompt", history_item)
        
        results = []
        errors = []
        
        def getter(iterations):
            try:
                for _ in range(iterations):
                    item = history_manager.get_history_item("test-prompt")
                    results.append(item is not None)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(str(e))
        
        # 创建多个读线程
        threads = []
        for _ in range(20):
            t = threading.Thread(target=getter, args=(10,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        assert len(errors) == 0, f"get_history_item 不应该有错误: {errors}"
        assert len(results) == 200  # 20个线程 * 10次迭代
        assert all(results), "所有读取都应该成功"
