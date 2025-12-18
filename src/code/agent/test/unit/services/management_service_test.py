import time
import pytest
from unittest.mock import Mock, patch
from concurrent.futures import ThreadPoolExecutor, as_completed

from exceptions.exceptions import StateTransitionError
from services.management_service import ManagementService, BackendStatus, Action

@pytest.fixture
def mock_process_mgr():
    with patch('services.process.comfyui_process_manager.ComfyUIProcessManager') as mock:
        instance = mock.return_value
        instance.start = Mock()
        instance.wait_until_ready = Mock(side_effect=lambda: time.sleep(1))
        instance.stop = Mock()
        yield instance


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
def service(mock_process_mgr, mock_snapshot_mgr):
    # 确保每次测试都使用新的 service 实例
    ManagementService._instances = {}  # 清除单例缓存
    service = ManagementService()
    service._process_mgr = mock_process_mgr
    service._snapshot_mgr = mock_snapshot_mgr
    service._status = BackendStatus.STOPPED  # 确保初始状态为 STOPPED
    service._latest_action = None  # 重置最后操作
    service._sub_status = ""  # 重置子状态
    return service

def test_concurrent_start(service, mock_process_mgr, mock_snapshot_mgr):
    thread_count = 3

    def start_service():
        try:
            initial_status = service.status
            service.start("test_snapshot")
            return {
                'success': True,
                'initial_status': initial_status,
                'final_status': service.status
            }
        except Exception as e:
            return {
                'success': False,
                'initial_status': service.status,
                'final_status': service.status,
                'error': str(e)
            }

    with ThreadPoolExecutor(max_workers=thread_count) as executor:
        futures = [executor.submit(start_service) for _ in range(thread_count)]
        start_attempts = [f.result() for f in as_completed(futures)]

    successful_starts = [attempt for attempt in start_attempts if attempt['success']]
    failed_starts = [attempt for attempt in start_attempts if not attempt['success']]

    assert len(successful_starts) == 1
    assert len(failed_starts) == thread_count - 1

    successful_start = successful_starts[0]
    assert successful_start['initial_status'] == BackendStatus.STOPPED
    assert successful_start['final_status'] == BackendStatus.RUNNING

    for failed_start in failed_starts:
        assert "Illegal state transition" in str(failed_start['error'])

    assert service.status == BackendStatus.RUNNING
    assert mock_snapshot_mgr.load.call_count == 1
    assert mock_process_mgr.start.call_count == 1
    assert mock_process_mgr.wait_until_ready.call_count == 1

def test_start_during_starting_fails(service):
    def slow_start():
        service._transition_to(BackendStatus.STARTING, Action.START)
        time.sleep(0.5)
        service._transition_to(BackendStatus.RUNNING, Action.START)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_start = executor.submit(slow_start)
        time.sleep(0.1)

        with pytest.raises(StateTransitionError):
            service.start("test_snapshot")

        first_start.result()

    assert service.status == BackendStatus.RUNNING

def test_initial_status(service):
    assert service.status == BackendStatus.STOPPED

def test_start_success(service, mock_process_mgr, mock_snapshot_mgr):
    service.start("test_snapshot")

    mock_snapshot_mgr.load.assert_called_once_with("test_snapshot")
    mock_process_mgr.start.assert_called_once()
    mock_process_mgr.wait_until_ready.assert_called_once()
    assert service.status == BackendStatus.RUNNING

def test_start_failure(service, mock_process_mgr, mock_snapshot_mgr):
    mock_process_mgr.start.side_effect = Exception("Start failed")

    with pytest.raises(Exception):
        service.start("test_snapshot")

    assert service.status == BackendStatus.STOPPED

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
    service._status = BackendStatus.RUNNING
    service.stop()

    mock_process_mgr.stop.assert_called_once()
    assert service.status == BackendStatus.STOPPED

def test_stop_failure(service, mock_process_mgr):
    service._status = BackendStatus.RUNNING
    mock_process_mgr.stop.side_effect = Exception("Stop failed")

    with pytest.raises(Exception):
        service.stop()

    assert service.status == BackendStatus.RUNNING

def test_save_and_stop(service):
    service._status = BackendStatus.RUNNING
    with patch.object(service, 'save') as mock_save:
        with patch.object(service, 'stop') as mock_stop:
            service.save_and_stop("test_type")

            mock_save.assert_called_once_with("test_type")
            mock_stop.assert_called_once()

def test_invalid_transition(service):
    with pytest.raises(StateTransitionError):
        service._transition_to(BackendStatus.RUNNING, Action.START)

@pytest.mark.parametrize("current_status,new_status,action", [
    (BackendStatus.STOPPED, BackendStatus.STARTING, Action.START),
    (BackendStatus.STARTING, BackendStatus.RUNNING, Action.START),
    (BackendStatus.RUNNING, BackendStatus.SAVING, Action.SAVE),
    (BackendStatus.SAVING, BackendStatus.RUNNING, Action.SAVE),
    (BackendStatus.RUNNING, BackendStatus.STOPPING, Action.STOP),
    (BackendStatus.STOPPING, BackendStatus.STOPPED, Action.STOP),
])
def test_valid_transitions(service, current_status, new_status, action):
    service._status = current_status
    service._transition_to(new_status, action)
    assert service.status == new_status
    assert service.latest_action == action

@pytest.mark.parametrize("current_status,new_status,action", [
    (BackendStatus.STOPPED, BackendStatus.RUNNING, Action.START),
    (BackendStatus.RUNNING, BackendStatus.STARTING, Action.START),
    (BackendStatus.SAVING, BackendStatus.STOPPED, Action.STOP),
    (BackendStatus.STOPPING, BackendStatus.SAVING, Action.SAVE),
])
def test_invalid_transitions(service, current_status, new_status, action):
    service._status = current_status
    with pytest.raises(StateTransitionError):
        service._transition_to(new_status, action)
