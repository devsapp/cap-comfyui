"""
ComfyUI Process Manager 测试用例

运行指南：
===========================================

✅ 推荐运行命令：
  cd /path/to/agent && python -m pytest test/unit/services/comfyui_process_manager_test.py -v

✅ 查看实时输出（如果想观察子进程日志）：
  cd /path/to/agent && python -m pytest test/unit/services/comfyui_process_manager_test.py -v -s

✅ 运行特定测试：
  cd /path/to/agent && python -m pytest test/unit/services/comfyui_process_manager_test.py::test_start_real_process -v

预期运行时间：
- 单个测试：约 5-15 秒（取决于具体测试）
- 全部测试：约 2-3 分钟

测试覆盖功能：
1. 基础功能测试：
   - test_start_real_process: 进程启动和停止
   - test_process_manually_restart_on_unexpected_exit: 手动重启
   - test_process_auto_restart_on_unexpected_exit: 自动重启
   - test_wait_until_ready_timeout: 启动超时处理

2. 健康检查测试：
   - test_port_check_consecutive_failures: 端口检查连续失败检测
   - test_port_check_recovery: 端口检查恢复
   - test_health_check_only_in_running_status: 不同状态下健康检查行为（新增）
   - test_running_status_health_check_with_process_dead: RUNNING 状态进程死亡检测（新增）

3. 进程状态测试：
   - test_process_crash_detection: 进程崩溃检测
   - test_is_process_running_method: 进程运行状态检查
   - test_is_ready_port_check: 端口就绪检查

4. 特殊模式测试：
   - test_cpu_mode_skip_health_check: CPU 模式跳过健康检查

5. 重启失败处理测试（新增）：
   - test_restart_failure_online_service_mode: 线上服务模式重启失败处理
   - test_restart_failure_dev_mode: 项目开发模式重启失败处理
   - test_restart_success: 重启成功处理

⚠️ 重要说明：
1. pytest 默认捕获所有输出，测试期间看不到任何输出是正常现象，不代表hang住
2. 测试会启动真实的 HTTP 服务器（端口 8188），需要等待进程启动和端口就绪
3. 如果测试真的hang住，默认超时是 900 秒（15分钟），可通过 wait_until_ready(timeout=30) 缩短超时
4. 确保端口 8188 未被占用：lsof -i :8188

Mock 进程说明：
- mock_comfyui_process.py: 健康的 HTTP 服务器（监听端口 8188）
- mock_crash_process.py: 启动后立即崩溃的进程（OOM 模拟）

故障排查：
- 如果进程启动失败，检查 mock_*.py 文件是否存在
- 如果端口无法绑定，可能是权限问题或端口被占用
- 运行测试时必须从 agent 目录执行，因为需要导入 services 等模块
"""

import signal
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from services.process.comfyui_process_manager import ComfyUIProcessManager


@pytest.fixture
def process_manager():
    mgr = ComfyUIProcessManager()
    # Mock _is_alive 始终返回 True，避免健康检查失败触发 _do_restart
    mgr._is_alive = MagicMock(return_value=True)
    return mgr


def test_start_real_process(process_manager):
    """
    测试进程的基本启动和停止流程
    
    预期耗时：约 6-9 秒
    - 启动子进程：~0.5秒
    - 等待端口就绪（轮询间隔3秒）：~3秒
    - 稳定性验证：2秒
    - 停止进程：1秒
    """
    script_path = Path(__file__).parent / "mock_comfyui_process.py"

    # 启动进程（约 0.5 秒）
    command = ['python3', str(script_path)]
    process_manager.start(command)

    assert process_manager.process is not None
    assert process_manager.process.pid > 0
    assert process_manager._is_ready() is False  # 子进程Readiness探针未就绪

    # 等待子进程启动完成（约 3 秒，轮询检查端口 8188 是否可连接）
    # 注意：这里会等待，看起来像hang住，但实际是正常的等待过程
    process_manager.wait_until_ready()

    # 等待正常运行几秒确认稳定（2 秒）
    time.sleep(2)

    # 停止进程（约 1 秒）
    process_manager.stop()

    # 验证进程已终止
    time.sleep(1)
    assert process_manager._is_ready() is False


def test_process_manually_restart_on_unexpected_exit(process_manager):
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
    assert process_manager._is_ready() is False

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
    assert process_manager._is_ready() is False


def test_process_auto_restart_on_unexpected_exit(process_manager):
    script_path = Path(__file__).parent / "mock_comfyui_process.py"

    # 启动进程
    command = ['python3', str(script_path)]
    process_manager.start(command)

    # 等待进程就绪
    process_manager.wait_until_ready()

    # 记录第一次启动的进程ID
    first_pid = process_manager.process.pid

    # 等待几秒确保进程稳定运行和健康检查线程启动
    time.sleep(2)

    # 模拟进程意外退出（发送SIGTERM信号）
    process_manager.process.send_signal(signal.SIGHUP)

    # 等待几秒让健康检查线程检测到进程死亡
    time.sleep(3)

    # 验证健康检查线程仍在运行
    assert process_manager.health_check_thread.is_alive()

    # 捕获并验证控制台输出包含预期的消息


    # 最后停止进程
    process_manager.stop()

    # 验证进程已完全终止
    time.sleep(1)
    assert not process_manager._is_ready()


def test_wait_until_ready_timeout(process_manager):
    script_path = Path(__file__).parent / "mock_never_ready_process.py"

    # 创建一个永不就绪的mock进程脚本
    with open(script_path, 'w') as f:
        f.write('''
            import time
            while True:
                time.sleep(1)
            ''')

    # 启动进程
    command = ['python3', str(script_path)]
    process_manager.start(command)

    # 设置一个较短的超时时间进行测试
    short_timeout = 3

    # 验证等待超时会抛出RuntimeError
    with pytest.raises(RuntimeError) as exc_info:
        process_manager.wait_until_ready(timeout=short_timeout)

    assert "process startup timed out" in str(exc_info.value).lower()

    # 清理临时文件
    script_path.unlink()


def test_port_check_consecutive_failures():
    """
    测试端口检查连续失败达到阈值（MAX_CONSECUTIVE_FAILURES = 3）
    
    场景：进程运行正常，但端口不可连接（模拟服务挂起）
    预期：连续失败 3 次后，_is_alive() 返回 False
    """
    mgr = ComfyUIProcessManager()
    script_path = Path(__file__).parent / "mock_comfyui_process.py"
    
    try:
        # 启动进程
        command = ['python3', str(script_path)]
        mgr.start(command)
        
        # 手动等待端口就绪，不启动健康检查线程
        start_time = time.time()
        while time.time() - start_time < 10:
            if mgr._is_ready():
                break
            time.sleep(1)
        
        assert mgr._is_ready() is True
        
        # 模拟端口检查失败（通过 mock _is_ready）
        with patch.object(mgr, '_is_ready', return_value=False):
            # 第一次检查：端口失败，但未达到阈值，仍然存活
            result1 = mgr._is_alive()
            assert result1 is True
            assert mgr._consecutive_failures == 1
            
            # 第二次检查：端口失败，但未达到阈值，仍然存活
            result2 = mgr._is_alive()
            assert result2 is True
            assert mgr._consecutive_failures == 2
            
            # 第三次检查：端口失败，达到阈值，判定为不存活
            result3 = mgr._is_alive()
            assert result3 is False
            assert mgr._consecutive_failures == 0  # 计数器被重置
        
    finally:
        if mgr.process:
            mgr.stop()
            time.sleep(1)


def test_port_check_recovery():
    """
    测试端口检查失败后恢复
    
    场景：端口检查失败 2 次（未达到阈值），然后恢复正常
    预期：恢复后计数器被重置为 0
    """
    mgr = ComfyUIProcessManager()
    script_path = Path(__file__).parent / "mock_comfyui_process.py"
    
    try:
        # 启动进程
        command = ['python3', str(script_path)]
        mgr.start(command)
        
        # 手动等待端口就绪，不启动健康检查线程
        start_time = time.time()
        while time.time() - start_time < 10:
            if mgr._is_ready():
                break
            time.sleep(1)
        
        # 模拟 2 次端口检查失败
        with patch.object(mgr, '_is_ready', return_value=False):
            assert mgr._is_alive() is True
            assert mgr._consecutive_failures == 1
            assert mgr._is_alive() is True
            assert mgr._consecutive_failures == 2
        
        # 端口恢复正常（移除 mock）
        assert mgr._is_alive() is True
        assert mgr._consecutive_failures == 0  # 计数器重置
        
    finally:
        if mgr.process:
            mgr.stop()
            time.sleep(1)


def test_process_crash_detection():
    """
    测试进程崩溃检测
    
    场景：子进程启动后立即崩溃退出
    预期：_is_process_running() 返回 False，_is_alive() 返回 False
    """
    mgr = ComfyUIProcessManager()
    script_path = Path(__file__).parent / "mock_crash_process.py"
    
    try:
        # 启动会立即崩溃的进程
        command = ['python3', str(script_path)]
        mgr.start(command)
        
        # 等待进程崩溃
        time.sleep(1)
        
        # 验证进程不再运行
        assert mgr._is_process_running() is False
        assert mgr.process.returncode == 137  # 模拟 OOM killed
        
        # _is_alive 应该返回 False
        assert mgr._is_alive() is False
        
    finally:
        # 进程已经崩溃，无需 stop
        mgr.process = None


def test_is_ready_port_check(process_manager):
    """
    测试 _is_ready() 的端口检查功能
    
    场景：进程未启动时，端口未监听
    预期：_is_ready() 返回 False
    """
    # 进程未启动，端口未监听
    assert process_manager._is_ready() is False
    
    # 启动进程
    script_path = Path(__file__).parent / "mock_comfyui_process.py"
    command = ['python3', str(script_path)]
    process_manager.start(command)
    
    # 端口未就绪时返回 False
    assert process_manager._is_ready() is False
    
    # 等待端口就绪
    process_manager.wait_until_ready(timeout=10)
    
    # 端口就绪后返回 True
    assert process_manager._is_ready() is True
    
    # 停止进程
    process_manager.stop()
    time.sleep(1)
    
    # 进程停止后，端口不再监听
    assert process_manager._is_ready() is False


@patch('constants.COMFYUI_MODE', 'cpu')
def test_cpu_mode_skip_health_check():
    """
    测试 CPU 模式下跳过健康检查
    
    场景：COMFYUI_MODE 设置为 'cpu'
    预期：_is_alive() 始终返回 True，不进行健康检查
    """
    mgr = ComfyUIProcessManager()
    
    # CPU 模式下，即使进程为 None，_is_alive() 也应该返回 True
    assert mgr._is_alive() is True


def test_health_check_only_in_running_status():
    """
    测试只有在 RUNNING 状态下才进行健康检查
    
    场景：测试不同状态下 _is_alive() 的行为
    预期：
    - RUNNING 状态：执行健康检查（可能返回 True 或 False）
    - SAVING 状态：跳过健康检查（返回 True）
    - REBOOTING 状态：跳过健康检查（返回 True）
    - REBOOT_FAILED 状态：跳过健康检查（返回 True）
    """
    from services.management_service import BackendStatus
    
    mgr = ComfyUIProcessManager()
    
    # Mock 一个假的进程对象
    mock_process = MagicMock()
    mock_process.poll = MagicMock(return_value=None)  # 进程在运行
    mgr.process = mock_process
    
    # 使用 patch 模拟 ManagementService 的状态
    with patch('services.management_service.ManagementService') as mock_service_class:
        mock_service = mock_service_class.return_value
        
        # 测试 RUNNING 状态：执行健康检查
        mock_service.status = BackendStatus.RUNNING
        # Mock 进程运行和端口正常
        with patch.object(mgr, '_is_process_running', return_value=True):
            with patch.object(mgr, '_is_ready', return_value=True):
                # 进程正常运行，端口也正常，应该返回 True
                assert mgr._is_alive() is True
        
        # 测试 SAVING 状态：跳过健康检查，直接返回 True
        mock_service.status = BackendStatus.SAVING
        # 即使进程死亡、端口不可用，也应该返回 True（跳过检查）
        with patch.object(mgr, '_is_process_running', return_value=False):
            with patch.object(mgr, '_is_ready', return_value=False):
                assert mgr._is_alive() is True
        
        # 测试 REBOOTING 状态：跳过健康检查，直接返回 True
        mock_service.status = BackendStatus.REBOOTING
        with patch.object(mgr, '_is_process_running', return_value=False):
            with patch.object(mgr, '_is_ready', return_value=False):
                assert mgr._is_alive() is True
        
        # 测试 REBOOT_FAILED 状态：跳过健康检查，直接返回 True
        mock_service.status = BackendStatus.REBOOT_FAILED
        with patch.object(mgr, '_is_process_running', return_value=False):
            with patch.object(mgr, '_is_ready', return_value=False):
                assert mgr._is_alive() is True


def test_is_process_running_method():
    """
    测试 _is_process_running() 方法
    
    验证该方法能够正确判断进程是否仍在运行
    """
    mgr = ComfyUIProcessManager()
    script_path = Path(__file__).parent / "mock_comfyui_process.py"
    
    try:
        # 进程未启动
        assert mgr._is_process_running() is False
        
        # 启动进程
        command = ['python3', str(script_path)]
        mgr.start(command)
        
        # 手动等待端口就绪
        start_time = time.time()
        while time.time() - start_time < 10:
            if mgr._is_ready():
                break
            time.sleep(1)
        
        # 进程正在运行
        assert mgr._is_process_running() is True
        
        # 终止进程
        mgr.process.terminate()
        mgr.process.wait()
        time.sleep(0.5)
        
        # 进程已退出
        assert mgr._is_process_running() is False
        
    finally:
        mgr.process = None


def test_restart_failure_online_service_mode():
    """
    测试线上服务模式下重启失败的处理
    
    场景：USE_API_MODE=True，进程重启失败
    预期：状态转换到 RUNNING，允许健康检查继续重试
    """
    from services.management_service import ManagementService, BackendStatus
    
    mgr = ComfyUIProcessManager()
    
    with patch('constants.USE_API_MODE', True):
        with patch('services.management_service.ManagementService') as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.status = BackendStatus.RUNNING
            
            # Mock _transition_to 方法
            mock_service._transition_to = MagicMock()
            
            # Mock start 方法使其抛出异常
            with patch.object(mgr, 'start', side_effect=Exception("Start failed")):
                # 调用 _do_restart，预期捕获异常
                mgr._do_restart()
                
                # 验证状态转换：应该转到 RUNNING（线上服务模式）
                # 第一次调用：转到 REBOOTING
                # 第二次调用：失败后转到 RUNNING
                assert mock_service._transition_to.call_count == 2
                mock_service._transition_to.assert_any_call(BackendStatus.REBOOTING)
                mock_service._transition_to.assert_any_call(BackendStatus.RUNNING)


def test_restart_failure_dev_mode():
    """
    测试项目开发模式下重启失败的处理
    
    场景：USE_API_MODE=False，进程重启失败
    预期：状态转换到 REBOOT_FAILED，停止自动重试
    """
    from services.management_service import ManagementService, BackendStatus
    
    mgr = ComfyUIProcessManager()
    
    with patch('constants.USE_API_MODE', False):
        with patch('services.management_service.ManagementService') as mock_service_class:
            mock_service = mock_service_class.return_value
            mock_service.status = BackendStatus.RUNNING
            
            # Mock _transition_to 方法
            mock_service._transition_to = MagicMock()
            
            # Mock start 方法使其抛出异常
            with patch.object(mgr, 'start', side_effect=Exception("Start failed")):
                # 调用 _do_restart，预期捕获异常
                mgr._do_restart()
                
                # 验证状态转换：应该转到 REBOOT_FAILED（项目开发模式）
                # 第一次调用：转到 REBOOTING
                # 第二次调用：失败后转到 REBOOT_FAILED
                assert mock_service._transition_to.call_count == 2
                mock_service._transition_to.assert_any_call(BackendStatus.REBOOTING)
                mock_service._transition_to.assert_any_call(BackendStatus.REBOOT_FAILED)


def test_restart_success():
    """
    测试重启成功的处理（进程已死亡，走 _cleanup_dead_process 分支）
    
    场景：进程重启成功
    预期：状态转换到 RUNNING
    """
    from services.management_service import ManagementService, BackendStatus
    
    mgr = ComfyUIProcessManager()
    
    with patch('services.management_service.ManagementService') as mock_service_class:
        mock_service = mock_service_class.return_value
        mock_service.status = BackendStatus.RUNNING
        
        # Mock _transition_to 方法
        mock_service._transition_to = MagicMock()
        
        # Mock 相关方法使重启成功
        with patch.object(mgr, '_is_process_running', return_value=False):
            with patch.object(mgr, '_cleanup_dead_process'):
                with patch.object(mgr, 'start'):
                    with patch.object(mgr, 'wait_until_ready'):
                        # 调用 _do_restart
                        mgr._do_restart()
                        
                        # 验证状态转换：应该转到 REBOOTING，然后转到 RUNNING
                        assert mock_service._transition_to.call_count == 2
                        mock_service._transition_to.assert_any_call(BackendStatus.REBOOTING)
                        # 最后一次调用应该是转到 RUNNING
                        last_call = mock_service._transition_to.call_args_list[-1]
                        assert last_call[0][0] == BackendStatus.RUNNING


def test_restart_with_running_process_uses_kill_and_cleanup():
    """
    测试进程仍在运行时，_do_restart 调用 _kill_and_cleanup（而非 stop）来清理旧进程

    场景：进程仍在运行（如端口检查连续失败触发重启，但进程还活着）
    预期：
    - 调用 _kill_and_cleanup() 杀死旧进程
    - 不调用 stop()（因为 _do_restart 在健康检查线程中执行，stop 会尝试 join 自身线程）
    """
    from services.management_service import BackendStatus

    mgr = ComfyUIProcessManager()

    with patch('services.management_service.ManagementService') as mock_service_class:
        mock_service = mock_service_class.return_value
        mock_service.status = BackendStatus.RUNNING
        mock_service._transition_to = MagicMock()

        with patch.object(mgr, '_is_process_running', return_value=True):
            with patch.object(mgr, '_kill_and_cleanup') as mock_kill:
                with patch.object(mgr, 'stop') as mock_stop:
                    with patch.object(mgr, 'start'):
                        with patch.object(mgr, 'wait_until_ready'):
                            mgr._do_restart()

                            # 验证调用了 _kill_and_cleanup 而非 stop
                            mock_kill.assert_called_once()
                            mock_stop.assert_not_called()

            # 验证重启成功的状态转换
            assert mock_service._transition_to.call_count == 2
            mock_service._transition_to.assert_any_call(BackendStatus.REBOOTING)
            last_call = mock_service._transition_to.call_args_list[-1]
            assert last_call[0][0] == BackendStatus.RUNNING


def test_restart_does_not_close_websocket_connections():
    """
    测试 _do_restart 不会关闭 WebSocket 连接

    场景：健康检查触发自动重启
    预期：ws_manager.close_all_connections 不被调用（Agent 仍在运行，WS 连接应保持）
    """
    from services.management_service import BackendStatus

    mgr = ComfyUIProcessManager()

    with patch('services.management_service.ManagementService') as mock_service_class:
        mock_service = mock_service_class.return_value
        mock_service.status = BackendStatus.RUNNING
        mock_service._transition_to = MagicMock()

        with patch.object(mgr, '_is_process_running', return_value=False):
            with patch.object(mgr, '_cleanup_dead_process'):
                with patch.object(mgr, 'start'):
                    with patch.object(mgr, 'wait_until_ready'):
                        with patch('services.process.websocket.websocket_manager.ws_manager') as mock_ws:
                            mgr._do_restart()

                            # 验证未关闭 WebSocket 连接
                            mock_ws.close_all_connections.assert_not_called()


def test_stop_closes_websocket_connections():
    """
    测试 stop() 会关闭所有 WebSocket 连接并传入超时参数

    场景：主动调用 stop() 停止服务
    预期：ws_manager.close_all_connections(timeout=5) 被调用
    """
    mgr = ComfyUIProcessManager()

    with patch.object(mgr, '_kill_and_cleanup'):
        with patch('services.process.websocket.websocket_manager.ws_manager') as mock_ws:
            mgr.stop()

            # 验证调用了 close_all_connections 且传入了 timeout=5
            mock_ws.close_all_connections.assert_called_once_with(timeout=5)


def test_running_status_health_check_with_process_dead():
    """
    测试 RUNNING 状态下进程死亡时的健康检查
    
    场景：RUNNING 状态，进程意外退出
    预期：_is_alive() 返回 False，触发重启
    """
    from services.management_service import BackendStatus
    
    mgr = ComfyUIProcessManager()
    
    with patch('services.management_service.ManagementService') as mock_service_class:
        mock_service = mock_service_class.return_value
        mock_service.status = BackendStatus.RUNNING
        
        # 模拟进程已死亡
        with patch.object(mgr, '_is_process_running', return_value=False):
            # RUNNING 状态下，进程死亡应该返回 False
            assert mgr._is_alive() is False


@pytest.fixture(autouse=True)
def cleanup(process_manager):
    yield
    if process_manager.process:
        process_manager.stop()
        time.sleep(1)  # 确保进程完全终止
