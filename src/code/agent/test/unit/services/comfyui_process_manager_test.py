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
    process_manager.start(command)

    assert process_manager.process is not None
    assert process_manager.process.pid > 0
    assert process_manager.is_ready() is False  # 子进程Readiness探针未就绪

    # 等待子进程启动完成
    process_manager.wait_until_ready()

    # 等待正常运行N秒
    time.sleep(5)

    # 停止进程
    process_manager.stop()

    # 验证进程已终止
    time.sleep(1)
    assert process_manager.is_ready() is False


def test_process_restart(process_manager):
    script_path = Path(__file__).parent / "mock_comfyui_process.py"

    # 首次启动进程
    command = ['python3', str(script_path)]
    process_manager.start(command)

    # 等待进程就绪
    process_manager.wait_until_ready()

    # 记录第一次启动的进程ID
    first_pid = process_manager.process.pid

    # 等待几秒确保进程稳定运行
    time.sleep(2)

    # 模拟进程意外退出（发送SIGTERM信号）
    process_manager.process.terminate()

    # 等待进程完全退出
    process_manager.process.wait()
    time.sleep(1)

    # 验证进程已经不再运行
    assert process_manager.is_ready() is False

    # 重新启动进程
    process_manager.start(command)

    # 等待新进程就绪
    process_manager.wait_until_ready()

    # 验证是新的进程（PID不同）
    assert process_manager.process.pid != first_pid

    # 最后停止进程
    process_manager.stop()

    # 验证进程已完全终止
    time.sleep(1)
    assert process_manager.is_ready() is False


@pytest.fixture(autouse=True)
def cleanup(process_manager):
    yield
    if process_manager.process:
        process_manager.stop()
        time.sleep(1)  # 确保进程完全终止
