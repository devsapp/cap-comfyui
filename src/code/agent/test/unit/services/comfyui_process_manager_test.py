import time
from pathlib import Path

import pytest

from services.comfyui_process_manager import ComfyuiProcessManager


@pytest.fixture
def process_manager():
    return ComfyuiProcessManager()


def test_start_real_process(process_manager):
    script_path = Path(__file__).parent / "mock_comfyui_process.py"

    # 启动进程
    command = ['python3', str(script_path)]
    result = process_manager.start(command)

    assert result is True
    assert process_manager.process is not None
    assert process_manager.process.pid > 0
    assert process_manager.is_ready() is False  # 子进程Readiness探针未就绪

    # 等待子进程启动完成
    result = process_manager.wait_until_ready()
    assert result is True

    # 等待正常运行N秒
    time.sleep(5)

    # 停止进程
    result = process_manager.stop()
    assert result is True

    # 验证进程已终止
    time.sleep(1)
    assert process_manager.is_ready() is False


@pytest.fixture(autouse=True)
def cleanup(process_manager):
    yield
    if process_manager.process:
        process_manager.stop()
        time.sleep(1)  # 确保进程完全终止
