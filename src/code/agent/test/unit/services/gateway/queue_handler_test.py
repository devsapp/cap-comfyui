"""
Queue Handler 单元测试
测试 POST /api/queue clear：对 PENDING 调 StopAsyncTask 再 clear_queue，与 ComfyUI 只清 pending 对齐
测试 GET /api/queue：返回项含 outputs_to_execute（与原生 ComfyUI 一致，未传时推断）
"""
import pytest
from unittest.mock import Mock, call, patch
from flask import Flask

from services.gateway.handlers.queue_handler import (
    MAX_PENDING_STOP_ON_CLEAR,
    QueueHandler,
)
from services.gateway.task.task import Task, TaskStatus


@pytest.fixture
def app():
    return Flask(__name__)


@pytest.fixture
def mock_task_manager():
    return Mock()


@pytest.fixture
def queue_handler(mock_task_manager):
    return QueueHandler(mock_task_manager)


def test_handle_post_clear_calls_stop_async_task_per_pending_then_clear_queue(queue_handler, mock_task_manager, app):
    """POST /api/queue clear 先对每个 PENDING 调 stop_async_task，再 clear_queue"""
    mock_task_manager.get_current_user_pending_task_ids.return_value = ["tid1", "tid2"]
    mock_task_manager.clear_queue.return_value = 2
    with patch("services.gateway.handlers.queue_handler.stop_async_task") as mock_stop:
        with app.test_request_context("/api/queue", method="POST", json={"clear": True}):
            response = queue_handler.handle_post_request()
    assert response.status_code == 200
    assert mock_stop.call_count == 2
    mock_stop.assert_any_call("tid1")
    mock_stop.assert_any_call("tid2")
    mock_task_manager.clear_queue.assert_called_once()


def test_handle_post_clear_with_no_pending_still_clears_queue(queue_handler, mock_task_manager, app):
    """POST /api/queue clear 若无 PENDING 仍会调用 clear_queue"""
    mock_task_manager.get_current_user_pending_task_ids.return_value = []
    mock_task_manager.clear_queue.return_value = 0
    with patch("services.gateway.handlers.queue_handler.stop_async_task") as mock_stop:
        with app.test_request_context("/api/queue", method="POST", json={"clear": True}):
            response = queue_handler.handle_post_request()
    assert response.status_code == 200
    mock_stop.assert_not_called()
    mock_task_manager.clear_queue.assert_called_once()


def test_handle_post_clear_caps_stop_async_task_calls(queue_handler, mock_task_manager, app):
    """POST /api/queue clear 对 PENDING 调 StopAsyncTask 有数量上限，避免请求阻塞过久"""
    over_limit = MAX_PENDING_STOP_ON_CLEAR + 10
    pending_ids = [f"tid_{i}" for i in range(over_limit)]
    mock_task_manager.get_current_user_pending_task_ids.return_value = pending_ids
    mock_task_manager.clear_queue.return_value = over_limit
    with patch("services.gateway.handlers.queue_handler.stop_async_task") as mock_stop:
        with app.test_request_context("/api/queue", method="POST", json={"clear": True}):
            response = queue_handler.handle_post_request()
    assert response.status_code == 200
    assert mock_stop.call_count == MAX_PENDING_STOP_ON_CLEAR
    mock_task_manager.clear_queue.assert_called_once()


def test_handle_post_clear_logs_warning_when_stop_partially_fails(queue_handler, mock_task_manager, app):
    """POST /api/queue clear 部分 StopAsyncTask 失败时记录聚合 WARNING 日志"""
    mock_task_manager.get_current_user_pending_task_ids.return_value = ["tid1", "tid2", "tid3"]
    mock_task_manager.clear_queue.return_value = 3
    # tid1 成功，tid2/tid3 失败
    def stop_side_effect(task_id):
        return task_id == "tid1"

    with patch("services.gateway.handlers.queue_handler.stop_async_task", side_effect=stop_side_effect):
        with patch("services.gateway.handlers.queue_handler.log") as mock_log:
            with app.test_request_context("/api/queue", method="POST", json={"clear": True}):
                response = queue_handler.handle_post_request()

    assert response.status_code == 200
    warning_calls = [c for c in mock_log.call_args_list if c.args[0] == "WARNING" and "StopAsyncTask failed" in c.args[1]]
    assert len(warning_calls) == 1
    assert "2/3" in warning_calls[0].args[1]


def test_handle_post_clear_no_warning_when_all_stop_succeed(queue_handler, mock_task_manager, app):
    """POST /api/queue clear 所有 StopAsyncTask 成功时不记录 WARNING"""
    mock_task_manager.get_current_user_pending_task_ids.return_value = ["tid1", "tid2"]
    mock_task_manager.clear_queue.return_value = 2

    with patch("services.gateway.handlers.queue_handler.stop_async_task", return_value=True):
        with patch("services.gateway.handlers.queue_handler.log") as mock_log:
            with app.test_request_context("/api/queue", method="POST", json={"clear": True}):
                response = queue_handler.handle_post_request()

    assert response.status_code == 200
    warning_calls = [c for c in mock_log.call_args_list if c.args[0] == "WARNING" and "StopAsyncTask failed" in c.args[1]]
    assert len(warning_calls) == 0


def test_handle_get_queue_returns_inferred_outputs_to_execute(queue_handler, mock_task_manager, app):
    """GET /api/queue 返回项第 5 位为 outputs_to_execute，未传时从工作流推断（与原生 ComfyUI 一致）"""
    prompt_body = {
        "prompt": {
            "3": {"class_type": "KSampler", "inputs": {}},
            "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "test", "images": ["8", 0]}},
        },
        "extra_data": {},
    }
    task = Task(
        task_id="t1",
        client_id="c1",
        prompt_body=prompt_body,
        user_id="u1",
        status=TaskStatus.PENDING,
    )
    mock_task_manager.get_current_user_tasks.return_value = [task]
    with app.test_request_context("/api/queue", method="GET"):
        from flask import g
        g.user_id = "u1"
        response = queue_handler.handle_get_request()
    data = response.get_json()
    assert "queue_pending" in data
    assert len(data["queue_pending"]) == 1
    item = data["queue_pending"][0]
    assert item[4] == ["9"]
    assert item[1] == "t1"
    assert "9" in item[2]
    assert item[2]["9"]["class_type"] == "SaveImage"
