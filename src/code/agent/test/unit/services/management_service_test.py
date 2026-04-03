import time
import pytest
from unittest.mock import Mock, patch
from concurrent.futures import ThreadPoolExecutor, as_completed

import constants
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

def test_install_custom_nodes_calls_install_all(service):
    """install_custom_nodes 应创建 PIPInstaller 并调用 install_all"""
    expected = {"baseline": {}, "dependencies": {}, "scripts": []}
    with patch("services.pip.pip_installer.PIPInstaller") as mock_cls:
        mock_cls.return_value.install_all.return_value = expected
        result = service.install_custom_nodes()
    _, kwargs = mock_cls.return_value.install_all.call_args
    assert kwargs["nodes_map"] is None
    assert kwargs["custom_nodes_dirs"] is None
    assert result == expected


def test_install_custom_nodes_passes_custom_dirs(service):
    """install_custom_nodes 应将 custom_nodes_dirs 透传给 install_all"""
    dirs = ["/some/custom_nodes", "/extra/custom_nodes"]
    with patch("services.pip.pip_installer.PIPInstaller") as mock_cls:
        mock_cls.return_value.install_all.return_value = {}
        service.install_custom_nodes(custom_nodes_dirs=dirs)
    _, kwargs = mock_cls.return_value.install_all.call_args
    assert kwargs["custom_nodes_dirs"] == dirs


def test_install_custom_nodes_passes_nodes_map(service):
    """install_custom_nodes 应将 nodes_map 透传给 install_all"""
    nodes = {"NodeA": {"version": "1.0"}}
    with patch("services.pip.pip_installer.PIPInstaller") as mock_cls:
        mock_cls.return_value.install_all.return_value = {}
        service.install_custom_nodes(nodes_map=nodes)
    _, kwargs = mock_cls.return_value.install_all.call_args
    assert kwargs["nodes_map"] == nodes


def test_install_custom_nodes_passes_timeout(service):
    """install_custom_nodes 应将 timeout 透传给 install_all"""
    with patch("services.pip.pip_installer.PIPInstaller") as mock_cls:
        mock_cls.return_value.install_all.return_value = {}
        service.install_custom_nodes(timeout=999)
    _, kwargs = mock_cls.return_value.install_all.call_args
    assert kwargs["timeout"] == 999


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


# ── start() 中的 clone + install 逻辑 ────────────────────────────────────────

def test_start_with_nonempty_dict_calls_clone_and_install(service, mock_process_mgr, mock_snapshot_mgr):
    """nodes_map 为非空 dict 时，应先调用 clone_custom_nodes，再调用 install_custom_nodes"""
    nodes_map = {"NodeA": {"source": {"cloneUrl": "https://github.com/a/a.git"}}}
    clone_result = {"details": {}, "summary": {}, "timed_out": False}
    install_result = {"baseline": {}, "dependencies": {}, "scripts": []}

    with patch.object(service, 'clone_custom_nodes', return_value=clone_result) as mock_clone, \
         patch.object(service, 'install_custom_nodes', return_value=install_result) as mock_install:
        result = service.start("test_snapshot", nodes_map=nodes_map)

    mock_clone.assert_called_once()
    clone_call_kwargs = mock_clone.call_args[1]
    assert clone_call_kwargs["custom_nodes_dirs"] is not None
    assert len(clone_call_kwargs["custom_nodes_dirs"]) == 2
    assert clone_call_kwargs["timeout"] == 300

    mock_install.assert_called_once()
    install_call_kwargs = mock_install.call_args[1]
    assert install_call_kwargs["custom_nodes_dirs"] is not None

    assert "clone_result" in result


def test_start_with_none_nodes_map_skips_clone_calls_install(service, mock_process_mgr, mock_snapshot_mgr):
    """nodes_map=None → 安装所有插件依赖，但不执行 clone"""
    install_result = {"baseline": {}, "dependencies": {}, "scripts": []}

    with patch.object(service, 'clone_custom_nodes') as mock_clone, \
         patch.object(service, 'install_custom_nodes', return_value=install_result) as mock_install:
        result = service.start("test_snapshot", nodes_map=None)

    mock_clone.assert_not_called()
    mock_install.assert_called_once()
    assert "clone_result" not in result


def test_start_with_empty_dict_skips_clone_calls_install(service, mock_process_mgr, mock_snapshot_mgr):
    """nodes_map={} → 不 clone，但仍执行 install（安装行为由 PIPInstaller 处理空 dict）"""
    install_result = {"baseline": {}, "dependencies": {}, "scripts": []}

    with patch.object(service, 'clone_custom_nodes') as mock_clone, \
         patch.object(service, 'install_custom_nodes', return_value=install_result) as mock_install:
        result = service.start("test_snapshot", nodes_map={})

    mock_clone.assert_not_called()
    mock_install.assert_called_once()
    assert "clone_result" not in result


def test_start_with_sentinel_skips_both_clone_and_install(service, mock_process_mgr, mock_snapshot_mgr):
    """nodes_map=SKIP_INSTALL_SENTINEL → 完全跳过 clone 和 install"""
    with patch.object(service, 'clone_custom_nodes') as mock_clone, \
         patch.object(service, 'install_custom_nodes') as mock_install:
        result = service.start("test_snapshot", nodes_map=constants.SKIP_INSTALL_SENTINEL)

    mock_clone.assert_not_called()
    mock_install.assert_not_called()
    assert "clone_result" not in result
    assert "time_install_process" not in result


def test_start_default_nodes_map_is_sentinel(service, mock_process_mgr, mock_snapshot_mgr):
    """不传 nodes_map 时默认为 constants.SKIP_INSTALL_SENTINEL，跳过 clone 和 install"""
    with patch.object(service, 'clone_custom_nodes') as mock_clone, \
         patch.object(service, 'install_custom_nodes') as mock_install:
        service.start("test_snapshot")

    mock_clone.assert_not_called()
    mock_install.assert_not_called()


def test_start_clone_result_merged_into_result_map(service, mock_process_mgr, mock_snapshot_mgr):
    """clone_result 应以 'clone_result' key 写入返回的 result_map"""
    nodes_map = {"NodeA": {"source": {}}}
    clone_result = {"details": {"NodeA": {"status": "cloned"}}, "summary": {"total": 1}, "timed_out": False}
    install_result = {"baseline": {}, "dependencies": {}, "scripts": []}

    with patch.object(service, 'clone_custom_nodes', return_value=clone_result), \
         patch.object(service, 'install_custom_nodes', return_value=install_result):
        result = service.start("test_snapshot", nodes_map=nodes_map)

    assert result["clone_result"] == clone_result
    assert result["clone_result"]["timed_out"] is False


def test_start_install_result_merged_into_result_map(service, mock_process_mgr, mock_snapshot_mgr):
    """install_result 的 key 应合并（update）到 result_map 顶层"""
    nodes_map = {"NodeA": {"source": {}}}
    install_result = {"baseline": {"pkg": "1.0"}, "dependencies": {"success": True}, "scripts": []}

    with patch.object(service, 'clone_custom_nodes', return_value={}), \
         patch.object(service, 'install_custom_nodes', return_value=install_result):
        result = service.start("test_snapshot", nodes_map=nodes_map)

    assert result["baseline"] == {"pkg": "1.0"}
    assert result["dependencies"] == {"success": True}


def test_start_custom_nodes_dirs_includes_two_dirs(service, mock_process_mgr, mock_snapshot_mgr):
    """custom_nodes_dirs 应包含 comfyui/custom_nodes 和 BUILTIN_DELTA_NODES_DIR"""
    nodes_map = {"NodeA": {"source": {}}}

    with patch.object(service, 'clone_custom_nodes', return_value={}) as mock_clone, \
         patch.object(service, 'install_custom_nodes', return_value={}) as mock_install:
        service.start("test_snapshot", nodes_map=nodes_map)

    clone_dirs = mock_clone.call_args[1]["custom_nodes_dirs"]
    install_dirs = mock_install.call_args[1]["custom_nodes_dirs"]

    assert len(clone_dirs) == 2
    assert "custom_nodes" in clone_dirs[0]
    assert clone_dirs == install_dirs


@pytest.mark.parametrize("nodes_map_input", [
    None,
    {"NodeA": {"source": {}}},
    "*",
])
def test_start_api_mode_skips_install_regardless_of_nodes_map(
    service, mock_process_mgr, mock_snapshot_mgr, nodes_map_input
):
    """USE_API_MODE=True 时，无论 nodes_map 传什么值都应跳过 clone 和 install"""
    with patch("services.management_service.constants") as mock_constants, \
         patch.object(service, 'clone_custom_nodes') as mock_clone, \
         patch.object(service, 'install_custom_nodes') as mock_install:
        mock_constants.USE_API_MODE = True
        mock_constants.SKIP_SNAPSHOT_LOADING = 'true'
        mock_constants.BACKEND_TYPE = 'comfyui'
        mock_constants.TYPE_COMFYUI = 'comfyui'
        mock_constants.BOOT_CMD = ['echo', 'test']
        mock_constants.COMFYUI_DIR = '/root/comfyui'
        mock_constants.BUILTIN_DELTA_NODES_DIR = '/root/built-in/custom_nodes_delta'
        result = service.start("test_snapshot", nodes_map=nodes_map_input)

    mock_clone.assert_not_called()
    mock_install.assert_not_called()
    assert "clone_result" not in result
    assert "time_install_process" not in result


def test_start_dev_mode_allows_install(service, mock_process_mgr, mock_snapshot_mgr):
    """USE_API_MODE=False（项目开发）时，nodes_map 正常生效"""
    install_result = {"baseline": {}, "dependencies": {}, "scripts": []}

    with patch("services.management_service.constants") as mock_constants, \
         patch.object(service, 'clone_custom_nodes', return_value={}) as mock_clone, \
         patch.object(service, 'install_custom_nodes', return_value=install_result) as mock_install:
        mock_constants.USE_API_MODE = False
        mock_constants.SKIP_SNAPSHOT_LOADING = 'true'
        mock_constants.BACKEND_TYPE = 'comfyui'
        mock_constants.TYPE_COMFYUI = 'comfyui'
        mock_constants.BOOT_CMD = ['echo', 'test']
        mock_constants.COMFYUI_DIR = '/root/comfyui'
        mock_constants.BUILTIN_DELTA_NODES_DIR = '/root/built-in/custom_nodes_delta'
        result = service.start("test_snapshot", nodes_map=None)

    mock_install.assert_called_once()
    assert "time_install_process" in result


def test_clone_custom_nodes_delegates_to_git_cloner(service):
    """clone_custom_nodes 应创建 GitCloner 并调用 clone_all"""
    expected = {"details": {}, "summary": {}, "timed_out": False}
    with patch("services.git.git_cloner.GitCloner") as mock_cls:
        mock_cls.return_value.clone_all.return_value = expected
        result = service.clone_custom_nodes({"NodeA": {}})
    assert result == expected


def test_clone_custom_nodes_passes_custom_dirs(service):
    """clone_custom_nodes 应将 custom_nodes_dirs 透传给 clone_all"""
    dirs = ["/dir1", "/dir2"]
    with patch("services.git.git_cloner.GitCloner") as mock_cls:
        mock_cls.return_value.clone_all.return_value = {}
        service.clone_custom_nodes({"NodeA": {}}, custom_nodes_dirs=dirs)
    _, kwargs = mock_cls.return_value.clone_all.call_args
    assert kwargs["custom_nodes_dirs"] == dirs


def test_clone_custom_nodes_passes_timeout(service):
    """clone_custom_nodes 应将 timeout 透传给 clone_all"""
    with patch("services.git.git_cloner.GitCloner") as mock_cls:
        mock_cls.return_value.clone_all.return_value = {}
        service.clone_custom_nodes({"NodeA": {}}, timeout=999)
    _, kwargs = mock_cls.return_value.clone_all.call_args
    assert kwargs["timeout"] == 999
