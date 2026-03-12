import time
import pytest
from unittest.mock import Mock, patch
from concurrent.futures import ThreadPoolExecutor, as_completed

from exceptions.exceptions import StateTransitionError
from services.management_service import ManagementService, BackendStatus

@pytest.fixture
def mock_process_mgr():
    with patch('services.process.comfyui_process_manager.ComfyUIProcessManager') as mock:
        instance = mock.return_value
        instance.start = Mock()
        instance.wait_until_ready = Mock(side_effect=lambda: time.sleep(1))
        instance.stop = Mock()
        yield instance


@pytest.fixture
def mock_setup_builtin_custom_nodes():
    with patch('services.custom_nodes.builtin_custom_nodes.setup_builtin_custom_nodes') as mock:
        yield mock


@pytest.fixture
def mock_snapshot_mgr():
    with patch('services.workspace.snapshot_manager.SnapshotManager') as mock:
        instance = mock.return_value

        def load_with_delay(snapshot_name):
            time.sleep(1)  # 延迟1秒
            return {"time_load": 1.0}

        def save_with_delay(snapshot_type):
            time.sleep(1)  # 延迟1秒
            return {"time_save": 1.0}

        instance.load = Mock(side_effect=load_with_delay)
        instance.save = Mock(side_effect=save_with_delay)
        yield instance

@pytest.fixture
def service(mock_process_mgr, mock_snapshot_mgr, mock_setup_builtin_custom_nodes):
    # 确保每次测试都使用新的 service 实例
    ManagementService._instances = {}  # 清除单例缓存
    service = ManagementService()
    service._process_mgr = mock_process_mgr
    service._snapshot_mgr = mock_snapshot_mgr
    service._status = BackendStatus.RUNNING  # 初始状态为 RUNNING
    service._sub_status = ""  # 重置子状态
    service._is_stopped = False  # 重置停止标志
    return service

def test_initial_status(service):
    """测试初始状态为 RUNNING，且未停止"""
    assert service.status == BackendStatus.RUNNING
    assert service._is_stopped is False

def test_start_success(service, mock_process_mgr, mock_snapshot_mgr):
    """测试 start 方法成功执行（不涉及状态转换）"""
    service.start("test_snapshot")

    mock_snapshot_mgr.load.assert_called_once_with("test_snapshot")
    mock_process_mgr.start.assert_called_once()
    mock_process_mgr.wait_until_ready.assert_called_once()
    # start 不改变状态，保持 RUNNING
    assert service.status == BackendStatus.RUNNING

def test_start_failure(service, mock_process_mgr, mock_snapshot_mgr):
    """测试 start 方法失败时状态不变"""
    mock_process_mgr.start.side_effect = Exception("Start failed")

    with pytest.raises(Exception):
        service.start("test_snapshot")

    # 失败后状态保持不变
    assert service.status == BackendStatus.RUNNING

def test_save_success(service, mock_snapshot_mgr):
    service._status = BackendStatus.RUNNING
    service.save("test_type")

    mock_snapshot_mgr.save.assert_called_once_with("test_type")
    assert service.status == BackendStatus.RUNNING

def test_save_failure(service, mock_snapshot_mgr):
    service._status = BackendStatus.RUNNING
    mock_snapshot_mgr.save.side_effect = Exception("Save failed")

    with pytest.raises(Exception):
        service.save("test_type")

    assert service.status == BackendStatus.RUNNING

def test_stop_success(service, mock_process_mgr):
    """测试 stop 方法成功执行（不涉及状态转换，但设置停止标志）"""
    assert service._is_stopped is False  # 初始状态未停止
    
    service.stop()

    mock_process_mgr.stop.assert_called_once()
    # stop 不改变状态，保持 RUNNING
    assert service.status == BackendStatus.RUNNING
    # 但会设置停止标志
    assert service._is_stopped is True

def test_stop_failure(service, mock_process_mgr):
    """测试 stop 方法失败时抛出异常，且不设置停止标志"""
    mock_process_mgr.stop.side_effect = Exception("Stop failed")
    assert service._is_stopped is False  # 初始状态未停止

    with pytest.raises(Exception):
        service.stop()

    # 失败后状态保持不变
    assert service.status == BackendStatus.RUNNING
    # 失败后停止标志也不应该被设置
    assert service._is_stopped is False

def test_save_and_stop(service):
    """测试 save_and_stop 方法会调用 save 和 stop，并设置停止标志"""
    service._status = BackendStatus.RUNNING
    assert service._is_stopped is False  # 初始状态未停止
    
    with patch.object(service, 'save', return_value={"snapshot": "test"}) as mock_save:
        with patch.object(service, 'stop', return_value={"time_stop_process": 1.0}) as mock_stop:
            # 模拟 stop 方法设置 _is_stopped
            def side_effect_stop():
                service._is_stopped = True
                return {"time_stop_process": 1.0}
            mock_stop.side_effect = side_effect_stop
            
            result = service.save_and_stop("test_type")

            mock_save.assert_called_once_with("test_type")
            mock_stop.assert_called_once()
            # 验证 stop 后设置了停止标志
            assert service._is_stopped is True
            # 验证返回值合并了 save 和 stop 的结果
            assert "snapshot" in result
            assert "time_stop_process" in result

@pytest.mark.parametrize("current_status,new_status", [
    (BackendStatus.RUNNING, BackendStatus.SAVING),
    (BackendStatus.RUNNING, BackendStatus.REBOOTING),
    (BackendStatus.SAVING, BackendStatus.RUNNING),
    (BackendStatus.REBOOTING, BackendStatus.RUNNING),
    (BackendStatus.REBOOTING, BackendStatus.REBOOT_FAILED),
])
def test_valid_transitions(service, current_status, new_status):
    """测试有效的状态转换"""
    service._status = current_status
    service._transition_to(new_status)
    assert service.status == new_status

@pytest.mark.parametrize("current_status,new_status", [
    (BackendStatus.SAVING, BackendStatus.SAVING),  # 不能从 SAVING 转到 SAVING
    (BackendStatus.SAVING, BackendStatus.REBOOTING),  # 不能从 SAVING 转到 REBOOTING
    (BackendStatus.REBOOTING, BackendStatus.SAVING),  # 不能从 REBOOTING 转到 SAVING
    (BackendStatus.REBOOT_FAILED, BackendStatus.RUNNING),  # REBOOT_FAILED 是终态
    (BackendStatus.REBOOT_FAILED, BackendStatus.SAVING),  # REBOOT_FAILED 是终态
    (BackendStatus.REBOOT_FAILED, BackendStatus.REBOOTING),  # REBOOT_FAILED 是终态
])
def test_invalid_transitions(service, current_status, new_status):
    """测试无效的状态转换"""
    service._status = current_status
    with pytest.raises(StateTransitionError):
        service._transition_to(new_status)
