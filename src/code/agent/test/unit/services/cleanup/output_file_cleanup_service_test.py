#!/usr/bin/env python3
"""
OutputFileCleanupService 单元测试
"""
import os
import sys
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# 添加 agent 目录到路径
agent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../../'))
sys.path.insert(0, agent_dir)

# 设置环境变量，避免依赖 constants
os.environ['MODEL_ASSET_DIR'] = '/tmp'

from services.cleanup.output_file_cleanup_service import OutputFileCleanupService


@pytest.fixture
def temp_dirs(tmp_path):
    """创建临时目录结构"""
    serverless_api = tmp_path / "serverless_api"
    archived_dir = tmp_path / "archived"
    serverless_api.mkdir()
    archived_dir.mkdir()
    return serverless_api, archived_dir


@pytest.fixture
def cleanup_service(temp_dirs):
    """创建清理服务实例"""
    serverless_api, archived_dir = temp_dirs
    return OutputFileCleanupService(
        source_dir=str(serverless_api),
        archived_dir=str(archived_dir),
        max_files=5,
        ttl_seconds=3600,  # 1小时
        archived_ttl_seconds=86400  # 1天
    )


class TestOutputFileCleanupService:
    """OutputFileCleanupService 测试类"""

    def test_init_with_default_dirs(self):
        """测试使用默认目录初始化"""
        with patch('constants.MNT_DIR', '/tmp/test_mnt'):
            service = OutputFileCleanupService()
            assert service.source_dir == Path('/tmp/test_mnt') / "output" / "serverless_api"
            assert service.archived_dir == Path('/tmp/test_mnt') / "output" / "serverless_api_archived"

    def test_archive_expired_files(self, cleanup_service, temp_dirs):
        """测试归档过期文件"""
        serverless_api, archived_dir = temp_dirs
        
        # 创建过期文件（2小时前）
        old_time = time.time() - (2 * 3600)
        expired_file = serverless_api / "expired.txt"
        expired_file.write_text("expired content")
        os.utime(expired_file, (old_time, old_time))
        
        # 创建新文件（刚刚创建）
        new_file = serverless_api / "new.txt"
        new_file.write_text("new content")
        
        cleanup_service._archive()
        
        # 验证过期文件被移动到归档目录
        assert not expired_file.exists()
        assert (archived_dir / "expired.txt").exists()
        
        # 验证新文件仍在源目录
        assert new_file.exists()
        assert not (archived_dir / "new.txt").exists()

    def test_archive_files_exceeding_max_count(self, cleanup_service, temp_dirs):
        """测试归档超过数量限制的文件"""
        serverless_api, archived_dir = temp_dirs
        
        # 创建6个新文件（超过max_files=5的限制）
        files = []
        for i in range(6):
            file_path = serverless_api / f"file_{i}.txt"
            file_path.write_text(f"content {i}")
            # 设置不同的修改时间，确保排序
            file_time = time.time() - (5 - i) * 60  # 最新的文件时间最晚
            os.utime(file_path, (file_time, file_time))
            files.append(file_path)
        
        cleanup_service._archive()
        
        # 验证源目录只保留最新的5个文件
        remaining_files = list(serverless_api.iterdir())
        assert len(remaining_files) == 5
        
        # 验证最旧的文件被移动到归档目录
        assert not files[0].exists()  # 最旧的文件
        assert (archived_dir / "file_0.txt").exists()

    def test_cleanup_archived_expired_files(self, cleanup_service, temp_dirs):
        """测试清理归档目录中的过期文件"""
        serverless_api, archived_dir = temp_dirs
        
        # 创建归档目录中的过期文件（2天前）
        old_time = time.time() - (2 * 86400)
        expired_file = archived_dir / "old_archived.txt"
        expired_file.write_text("old content")
        os.utime(expired_file, (old_time, old_time))
        
        # 创建归档目录中的新文件（刚刚创建）
        new_file = archived_dir / "new_archived.txt"
        new_file.write_text("new content")
        
        cleanup_service._cleanup_archived()
        
        # 验证过期文件被删除
        assert not expired_file.exists()
        
        # 验证新文件仍在归档目录
        assert new_file.exists()

    def test_cleanup_without_cleaning_archived(self, cleanup_service, temp_dirs):
        """测试不清理归档目录的情况"""
        serverless_api, archived_dir = temp_dirs
        
        # 创建归档目录中的过期文件
        old_time = time.time() - (2 * 86400)
        expired_file = archived_dir / "old.txt"
        expired_file.write_text("old")
        os.utime(expired_file, (old_time, old_time))
        
        cleanup_service.cleanup(clean_archived=False)
        
        # 验证归档目录中的过期文件未被删除
        assert expired_file.exists()

    def test_batch_move_files_with_conflict(self, cleanup_service, temp_dirs):
        """测试移动文件时处理目标文件冲突"""
        serverless_api, archived_dir = temp_dirs
        
        # 在归档目录中创建同名文件
        existing_file = archived_dir / "conflict.txt"
        existing_file.write_text("existing")
        
        # 创建源文件
        source_file = serverless_api / "conflict.txt"
        source_file.write_text("new content")
        
        cleanup_service._batch_move_files([source_file])
        
        # 验证源文件被移动（覆盖目标文件）
        assert not source_file.exists()
        assert (archived_dir / "conflict.txt").exists()
        assert (archived_dir / "conflict.txt").read_text() == "new content"

    def test_batch_move_files_empty_list(self, cleanup_service):
        """测试移动空文件列表"""
        cleanup_service._batch_move_files([])
        # 如果执行到这里，说明没有抛出异常，测试通过

    def test_archive_handles_file_stat_error(self, cleanup_service, temp_dirs):
        """测试处理文件stat错误的情况"""
        serverless_api, archived_dir = temp_dirs
        
        # 创建一个文件
        test_file = serverless_api / "test.txt"
        test_file.write_text("test")
        
        # Mock os.scandir 返回一个无法stat的项
        with patch('os.scandir') as mock_scandir:
            mock_entry = MagicMock()
            mock_entry.is_file.return_value = True
            mock_entry.path = str(test_file)
            mock_entry.stat.side_effect = PermissionError("Permission denied")
            mock_scandir.return_value = [mock_entry]
            
            with patch('services.cleanup.output_file_cleanup_service.log') as mock_log:
                # 应该不会抛出异常，而是记录警告日志
                cleanup_service._archive()
                # 验证记录了警告日志
                mock_log.assert_called()
                # 检查是否有 WARNING 级别的日志调用
                warning_calls = [call for call in mock_log.call_args_list 
                                if call[0][0] == "WARNING" and "Failed to process file" in call[0][1]]
                assert len(warning_calls) > 0

    def test_archive_handles_directory_error(self, cleanup_service, temp_dirs):
        """测试处理目录扫描错误的情况"""
        serverless_api, archived_dir = temp_dirs
        
        with patch('services.cleanup.output_file_cleanup_service.os.scandir', side_effect=PermissionError("Cannot access directory")):
            with patch('services.cleanup.output_file_cleanup_service.log') as mock_log:
                # 应该不会抛出异常，而是记录错误日志
                cleanup_service._archive()
                # 验证记录了错误日志
                mock_log.assert_called_once()
                call_args = mock_log.call_args
                assert call_args[0][0] == "ERROR"
                assert "Error moving old files" in call_args[0][1]

    def test_batch_move_files_handles_rename_error(self, cleanup_service, temp_dirs):
        """测试处理os.rename失败的情况"""
        serverless_api, archived_dir = temp_dirs
        
        test_file = serverless_api / "test.txt"
        test_file.write_text("test")
        
        # Mock os.rename 失败，shutil.move 成功
        with patch('os.rename', side_effect=OSError("Cross-device link")):
            with patch('shutil.move') as mock_move:
                cleanup_service._batch_move_files([test_file])
                mock_move.assert_called_once()

    def test_batch_move_files_handles_both_move_failures(self, cleanup_service, temp_dirs):
        """测试处理os.rename和shutil.move都失败的情况"""
        serverless_api, archived_dir = temp_dirs
        
        test_file = serverless_api / "test.txt"
        test_file.write_text("test")
        
        # Mock 两个移动操作都失败
        with patch('os.rename', side_effect=OSError("Error 1")):
            with patch('shutil.move', side_effect=OSError("Error 2")):
                with patch('services.cleanup.output_file_cleanup_service.log') as mock_log:
                    # 应该不会抛出异常，而是记录错误日志
                    cleanup_service._batch_move_files([test_file])
                    # 文件应该仍在源目录
                    assert test_file.exists()
                    # 验证记录了错误日志
                    mock_log.assert_called()
                    error_calls = [call for call in mock_log.call_args_list 
                                    if call[0][0] == "ERROR" and "Failed to archive file" in call[0][1]]
                    assert len(error_calls) > 0

    def test_batch_move_files_handles_remove_conflict_error(self, cleanup_service, temp_dirs):
        """测试处理删除冲突文件失败的情况"""
        serverless_api, archived_dir = temp_dirs
        
        # 在归档目录中创建同名文件
        existing_file = archived_dir / "conflict.txt"
        existing_file.write_text("existing")
        
        # 创建源文件
        source_file = serverless_api / "conflict.txt"
        source_file.write_text("new")
        
        # Mock os.remove 失败（代码会尝试删除目标文件）
        with patch('os.remove', side_effect=PermissionError("Cannot delete")):
            with patch('services.cleanup.output_file_cleanup_service.log') as mock_log:
                # 应该不会抛出异常，而是记录警告日志并跳过
                cleanup_service._batch_move_files([source_file])
                # 源文件应该仍在原位置（因为删除目标文件失败，无法移动）
                assert source_file.exists()
                # 目标文件应该仍然存在
                assert existing_file.exists()
                # 验证记录了警告日志
                mock_log.assert_called()
                warning_calls = [call for call in mock_log.call_args_list 
                                if call[0][0] == "WARNING" and "Failed to remove existing file" in call[0][1]]
                assert len(warning_calls) > 0

    def test_cleanup_archived_handles_stat_error(self, cleanup_service, temp_dirs):
        """测试清理归档目录时处理stat错误"""
        serverless_api, archived_dir = temp_dirs
        
        test_file = archived_dir / "test.txt"
        test_file.write_text("test")
        
        # Mock os.scandir 返回一个无法stat的项
        with patch('os.scandir') as mock_scandir:
            mock_entry = MagicMock()
            mock_entry.is_file.return_value = True
            mock_entry.path = str(test_file)
            mock_entry.stat.side_effect = PermissionError("Permission denied")
            mock_scandir.return_value = [mock_entry]
            
            with patch('services.cleanup.output_file_cleanup_service.log') as mock_log:
                # 应该不会抛出异常，而是记录警告日志
                cleanup_service._cleanup_archived()
                # 验证记录了警告日志
                mock_log.assert_called()
                warning_calls = [call for call in mock_log.call_args_list 
                                if call[0][0] == "WARNING" and "Failed to stat file" in call[0][1]]
                assert len(warning_calls) > 0

    def test_cleanup_archived_handles_delete_error(self, cleanup_service, temp_dirs):
        """测试清理归档目录时处理删除错误"""
        serverless_api, archived_dir = temp_dirs
        
        # 创建过期文件
        old_time = time.time() - (2 * 86400)
        expired_file = archived_dir / "expired.txt"
        expired_file.write_text("expired")
        os.utime(expired_file, (old_time, old_time))
        
        # Mock os.remove 失败
        with patch('os.remove', side_effect=PermissionError("Cannot delete")):
            with patch('services.cleanup.output_file_cleanup_service.log') as mock_log:
                # 应该不会抛出异常，而是记录错误日志
                cleanup_service._cleanup_archived()
                # 文件应该仍在归档目录
                assert expired_file.exists()
                # 验证记录了错误日志
                mock_log.assert_called()
                error_calls = [call for call in mock_log.call_args_list 
                                if call[0][0] == "ERROR" and "Failed to delete file" in call[0][1]]
                assert len(error_calls) > 0

    def test_cleanup_archived_handles_directory_error(self, cleanup_service, temp_dirs):
        """测试清理归档目录时处理目录扫描错误"""
        serverless_api, archived_dir = temp_dirs
        
        with patch('services.cleanup.output_file_cleanup_service.os.scandir', side_effect=PermissionError("Cannot access directory")):
            with patch('services.cleanup.output_file_cleanup_service.log') as mock_log:
                # 应该不会抛出异常，而是记录错误日志
                cleanup_service._cleanup_archived()
                # 验证记录了错误日志
                mock_log.assert_called_once()
                call_args = mock_log.call_args
                assert call_args[0][0] == "ERROR"
                assert "Error cleaning archived" in call_args[0][1]

    def test_cleanup_handles_exception(self, cleanup_service, temp_dirs):
        """测试cleanup方法处理异常"""
        serverless_api, archived_dir = temp_dirs
        
        # Mock _archive 抛出异常
        with patch.object(cleanup_service, '_archive', side_effect=Exception("Archive error")):
            with patch('services.cleanup.output_file_cleanup_service.log') as mock_log:
                cleanup_service.cleanup()
                # 验证记录了错误日志
                mock_log.assert_called()
                error_calls = [call for call in mock_log.call_args_list 
                                if call[0][0] == "ERROR" and "文件清理过程中出错" in call[0][1]]
                assert len(error_calls) > 0

    def test_archive_mixed_files(self, cleanup_service, temp_dirs):
        """测试归档混合的过期和未过期文件"""
        serverless_api, archived_dir = temp_dirs
        
        # 创建过期文件
        old_time = time.time() - (2 * 3600)
        expired_file = serverless_api / "expired.txt"
        expired_file.write_text("expired")
        os.utime(expired_file, (old_time, old_time))
        
        # 创建多个新文件（超过限制）
        for i in range(6):
            file_path = serverless_api / f"new_{i}.txt"
            file_path.write_text(f"new {i}")
            file_time = time.time() - (5 - i) * 60
            os.utime(file_path, (file_time, file_time))
        
        cleanup_service._archive()
        
        # 验证过期文件被移动
        assert not expired_file.exists()
        assert (archived_dir / "expired.txt").exists()
        
        # 验证源目录只保留5个文件
        remaining = list(serverless_api.iterdir())
        assert len(remaining) == 5

    def test_cleanup_full_workflow(self, cleanup_service, temp_dirs):
        """测试完整的清理工作流程"""
        serverless_api, archived_dir = temp_dirs
        
        # 创建源目录中的过期文件
        old_time = time.time() - (2 * 3600)
        expired_file = serverless_api / "expired.txt"
        expired_file.write_text("expired")
        os.utime(expired_file, (old_time, old_time))
        
        # 创建归档目录中的过期文件
        archived_old_time = time.time() - (2 * 86400)
        archived_expired = archived_dir / "old_archived.txt"
        archived_expired.write_text("old archived")
        os.utime(archived_expired, (archived_old_time, archived_old_time))
        
        # 执行完整清理
        cleanup_service.cleanup(clean_archived=True)
        
        # 验证源目录中的过期文件被移动到归档目录
        assert not expired_file.exists()
        assert (archived_dir / "expired.txt").exists()
        
        # 验证归档目录中的过期文件被删除
        assert not archived_expired.exists()

    def test_cancel_cleanup(self, cleanup_service, temp_dirs):
        """测试取消清理操作"""
        import threading
        serverless_api, archived_dir = temp_dirs
        
        # 创建大量文件以确保清理需要一定时间
        for i in range(100):
            file_path = serverless_api / f"file_{i}.txt"
            file_path.write_text(f"content {i}")
            # 设置为过期文件
            old_time = time.time() - (2 * 3600)
            os.utime(file_path, (old_time, old_time))
        
        # 在另一个线程中启动清理
        cleanup_thread = threading.Thread(target=cleanup_service.cleanup)
        cleanup_thread.start()
        
        # 立即取消清理
        time.sleep(0.01)  # 短暂等待确保清理已开始
        cleanup_service.cancel()
        
        # 等待清理线程结束
        cleanup_thread.join(timeout=5)
        
        # 验证取消标志已设置
        assert cleanup_service._cancel_event.is_set()
        
        # 验证不是所有文件都被移动（因为被取消了）
        remaining_files = list(serverless_api.iterdir())
        # 如果取消生效，应该还有一些文件未被移动
        # 注意：具体数量取决于取消时机，所以只验证不是全部移动完成
        assert len(remaining_files) > 0 or len(list(archived_dir.iterdir())) < 100

    def test_cleanup_resets_cancel_flag(self, cleanup_service, temp_dirs):
        """测试cleanup方法重置取消标志"""
        serverless_api, archived_dir = temp_dirs
        
        # 先设置取消标志
        cleanup_service.cancel()
        assert cleanup_service._cancel_event.is_set()
        
        # 创建一个测试文件
        test_file = serverless_api / "test.txt"
        test_file.write_text("test")
        
        # 再次调用cleanup应该重置标志并正常执行
        cleanup_service.cleanup()
        
        # 验证取消标志已被清除（cleanup结束后）
        # 注意：cleanup执行后标志不应该被设置
        assert not cleanup_service._cancel_event.is_set()
