"""
Interrupt Handler 单元测试
POST /api/interrupt 暂不支持，返回 403
"""
import pytest
from unittest.mock import Mock
from flask import Flask

from services.gateway.handlers.interrupt_handler import InterruptHandler


@pytest.fixture
def app():
    return Flask(__name__)


@pytest.fixture
def interrupt_handler():
    return InterruptHandler()


def test_handle_post_returns_403(interrupt_handler, app):
    """POST /api/interrupt 返回 403，不允许客户端中止正在运行的任务"""
    with app.test_request_context("/api/interrupt", method="POST"):
        response, status_code = interrupt_handler.handle_post()
    assert status_code == 403
    data = response.get_json()
    assert data["error"]["type"] == "not_supported"


def test_handle_post_returns_error_message(interrupt_handler, app):
    """POST /api/interrupt 错误体包含可读的 message"""
    with app.test_request_context("/api/interrupt", method="POST"):
        response, status_code = interrupt_handler.handle_post()
    data = response.get_json()
    assert "message" in data["error"]
    assert len(data["error"]["message"]) > 0
