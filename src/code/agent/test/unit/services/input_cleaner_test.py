"""
InputCleaner 单元测试

测试 Input 目录清理器的各种场景：
- 基本清理功能
- TTL 过期判断
- 并发唤醒合并
- 清理间隔控制
- 最小文件数阈值

运行方式：
    cd src/code/agent
    python -m pytest test/unit/services/input_cleaner_test.py -v
"""

import os
import time
import tempfile
import threading
import pytest
from unittest.mock import patch, MagicMock

from services.serverlessapi.input_cleaner import InputCleaner


# ==================== Fixtures ====================

@pytest.fixture
def temp_input_dir():
    """创建临时目录用于测试"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def cleaner(temp_input_dir):
    """
    创建测试用的 InputCleaner 实例
    
    使用很短的 TTL 和 interval 以便快速测试
    min_files_threshold=0 禁用阈值检查，确保基本测试正常运行
    """
    with patch.dict(os.environ, {"INPUT_CLEANUP_MIN_FILES": "0"}):
        cleaner = InputCleaner(
            input_dir=temp_input_dir,
            cleanup_interval=1,  # 1秒清理间隔
            file_ttl=2,  # 2秒过期
        )
        yield cleaner
        cleaner.stop()


@pytest.fixture
def cleaner_no_auto_start(temp_input_dir):
    """
    创建不自动启动线程的 InputCleaner（用于同步测试）
    
    通过直接调用 cleanup_sync() 进行测试
    min_files_threshold=0 禁用阈值检查
    """
    # 暂时 mock 线程启动
    with patch.object(InputCleaner, '_cleanup_loop'):
        with patch.dict(os.environ, {"INPUT_CLEANUP_MIN_FILES": "0"}):
            cleaner = InputCleaner(
                input_dir=temp_input_dir,
                cleanup_interval=1,
                file_ttl=2,
            )
            yield cleaner


def create_test_file(directory: str, filename: str, age_seconds: float = 0) -> str:
    """
    创建测试文件
    
    Args:
        directory: 目录路径
        filename: 文件名
        age_seconds: 文件年龄（秒），通过修改 mtime 实现
        
    Returns:
        str: 文件完整路径
    """
    filepath = os.path.join(directory, filename)
    with open(filepath, 'w') as f:
        f.write(f"test content for {filename}")
    
    if age_seconds > 0:
        # 修改文件的修改时间，使其看起来是 age_seconds 秒前创建的
        old_time = time.time() - age_seconds
        os.utime(filepath, (old_time, old_time))
    
    return filepath


# ==================== 基本功能测试 ====================

class TestBasicCleanup:
    """测试基本清理功能"""
    
    def test_cleanup_expired_files(self, cleaner_no_auto_start, temp_input_dir):
        """测试清理过期文件"""
        # 创建一个过期文件（3秒前）和一个新文件
        old_file = create_test_file(temp_input_dir, "old_image.png", age_seconds=3)
        new_file = create_test_file(temp_input_dir, "new_image.png", age_seconds=0)
        
        # TTL 是 2秒，所以 old_file 应该被清理
        cleaned = cleaner_no_auto_start.cleanup_sync()
        
        assert cleaned == 1
        assert not os.path.exists(old_file), "过期文件应该被删除"
        assert os.path.exists(new_file), "新文件不应该被删除"
    
    def test_no_cleanup_when_all_files_fresh(self, cleaner_no_auto_start, temp_input_dir):
        """测试所有文件都是新的时不清理"""
        create_test_file(temp_input_dir, "file1.png", age_seconds=0)
        create_test_file(temp_input_dir, "file2.png", age_seconds=1)
        
        cleaned = cleaner_no_auto_start.cleanup_sync()
        
        assert cleaned == 0
        assert len(os.listdir(temp_input_dir)) == 2
    
    def test_cleanup_all_expired_files(self, cleaner_no_auto_start, temp_input_dir):
        """测试清理所有过期文件"""
        # 创建 5 个过期文件
        for i in range(5):
            create_test_file(temp_input_dir, f"old_{i}.png", age_seconds=5)
        
        cleaned = cleaner_no_auto_start.cleanup_sync()
        
        assert cleaned == 5
        assert len(os.listdir(temp_input_dir)) == 0
    
    def test_cleanup_empty_directory(self, cleaner_no_auto_start, temp_input_dir):
        """测试空目录不报错"""
        cleaned = cleaner_no_auto_start.cleanup_sync()
        assert cleaned == 0
    
    def test_cleanup_nonexistent_directory(self):
        """测试不存在的目录不报错"""
        with patch.object(InputCleaner, '_cleanup_loop'):
            with patch.dict(os.environ, {"INPUT_CLEANUP_MIN_FILES": "0"}):
                cleaner = InputCleaner(
                    input_dir="/nonexistent/path",
                    cleanup_interval=1,
                    file_ttl=2,
                )
                cleaned = cleaner.cleanup_sync()
                assert cleaned == 0
    
    def test_only_cleanup_files_not_directories(self, cleaner_no_auto_start, temp_input_dir):
        """测试只清理文件，不清理子目录"""
        # 创建一个过期文件和一个子目录
        old_file = create_test_file(temp_input_dir, "old.png", age_seconds=5)
        subdir = os.path.join(temp_input_dir, "subdir")
        os.makedirs(subdir)
        # 在子目录中创建过期文件（不应被清理）
        create_test_file(subdir, "nested_old.png", age_seconds=5)
        
        cleaned = cleaner_no_auto_start.cleanup_sync()
        
        assert cleaned == 1
        assert not os.path.exists(old_file)
        assert os.path.exists(subdir), "子目录不应被删除"
        assert os.path.exists(os.path.join(subdir, "nested_old.png")), "子目录中的文件不应被清理"


# ==================== 异步清理测试 ====================

class TestAsyncCleanup:
    """测试异步清理功能"""
    
    def test_wake_triggers_cleanup(self, cleaner, temp_input_dir):
        """测试 wake() 能触发清理"""
        # 创建过期文件
        old_file = create_test_file(temp_input_dir, "old.png", age_seconds=5)
        
        # 唤醒清理线程
        cleaner.wake()
        
        # 等待清理完成
        time.sleep(0.5)
        
        assert not os.path.exists(old_file), "wake() 应该触发清理"
    
    def test_cleanup_interval_respected(self, cleaner, temp_input_dir):
        """测试清理间隔被遵守"""
        # 第一次清理
        old_file1 = create_test_file(temp_input_dir, "old1.png", age_seconds=5)
        cleaner.wake()
        time.sleep(0.5)
        assert not os.path.exists(old_file1)
        
        # 立即创建新的过期文件并唤醒
        old_file2 = create_test_file(temp_input_dir, "old2.png", age_seconds=5)
        cleaner.wake()
        time.sleep(0.3)
        
        # 因为距离上次清理不足 1 秒（cleanup_interval），不应该清理
        assert os.path.exists(old_file2), "清理间隔内不应该再次清理"
        
        # 等待超过清理间隔后再唤醒
        time.sleep(1)
        cleaner.wake()
        time.sleep(0.5)
        
        assert not os.path.exists(old_file2), "超过清理间隔后应该清理"
    
    def test_multiple_concurrent_wakes(self, cleaner, temp_input_dir):
        """测试多个并发唤醒只触发一次清理"""
        # 创建过期文件
        create_test_file(temp_input_dir, "old.png", age_seconds=5)
        
        # 用一个计数器来跟踪清理次数
        cleanup_count = [0]
        original_cleanup = cleaner._cleanup_old_files
        
        def counting_cleanup():
            cleanup_count[0] += 1
            return original_cleanup()
        
        cleaner._cleanup_old_files = counting_cleanup
        
        # 并发发送多个唤醒信号
        threads = []
        for _ in range(10):
            t = threading.Thread(target=cleaner.wake)
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # 等待清理完成
        time.sleep(0.5)
        
        # 应该只清理一次（因为在 cleanup_interval 内）
        assert cleanup_count[0] == 1, f"并发唤醒应该只触发一次清理，实际 {cleanup_count[0]} 次"


# ==================== 边界条件测试 ====================

class TestEdgeCases:
    """测试边界条件"""
    
    def test_file_deleted_during_cleanup(self, cleaner_no_auto_start, temp_input_dir):
        """测试清理过程中文件被其他进程删除"""
        old_file = create_test_file(temp_input_dir, "old.png", age_seconds=5)
        
        # 在清理前删除文件，模拟并发删除
        original_remove = os.remove
        def delayed_remove(path):
            if "old.png" in path:
                # 模拟文件已被删除
                raise FileNotFoundError(f"File not found: {path}")
            return original_remove(path)
        
        with patch('os.remove', side_effect=delayed_remove):
            # 不应该抛出异常
            cleaned = cleaner_no_auto_start.cleanup_sync()
        
        # FileNotFoundError 应该被忽略，返回 0
        assert cleaned == 0
    
    def test_permission_error_handled(self, cleaner_no_auto_start, temp_input_dir):
        """测试权限错误被处理"""
        create_test_file(temp_input_dir, "old.png", age_seconds=5)
        
        with patch('os.remove', side_effect=PermissionError("Access denied")):
            # 不应该抛出异常
            cleaned = cleaner_no_auto_start.cleanup_sync()
        
        assert cleaned == 0
    
    def test_cleaner_stop(self, temp_input_dir):
        """测试清理器停止"""
        with patch.dict(os.environ, {"INPUT_CLEANUP_MIN_FILES": "0"}):
            cleaner = InputCleaner(
                input_dir=temp_input_dir,
                cleanup_interval=1,
                file_ttl=2,
            )
            
            assert cleaner.is_running
            
            cleaner.stop()
            time.sleep(0.2)
            
            assert not cleaner.is_running


# ==================== 最小文件数阈值测试 ====================

class TestMinFilesThreshold:
    """测试最小文件数阈值功能"""
    
    def test_skip_cleanup_when_below_threshold(self, temp_input_dir):
        """测试文件数低于阈值时跳过清理"""
        with patch.object(InputCleaner, '_cleanup_loop'):
            with patch.dict(os.environ, {"INPUT_CLEANUP_MIN_FILES": "10"}):
                cleaner = InputCleaner(
                    input_dir=temp_input_dir,
                    cleanup_interval=1,
                    file_ttl=2,
                )
                
                # 创建 5 个过期文件（低于阈值 10）
                for i in range(5):
                    create_test_file(temp_input_dir, f"old_{i}.png", age_seconds=5)
                
                cleaned = cleaner.cleanup_sync()
                
                # 因为文件数 (5) < 阈值 (10)，不应该清理
                assert cleaned == 0
                assert len(os.listdir(temp_input_dir)) == 5, "文件数低于阈值时不应清理"
    
    def test_cleanup_when_above_threshold(self, temp_input_dir):
        """测试文件数高于阈值时正常清理"""
        with patch.object(InputCleaner, '_cleanup_loop'):
            with patch.dict(os.environ, {"INPUT_CLEANUP_MIN_FILES": "5"}):
                cleaner = InputCleaner(
                    input_dir=temp_input_dir,
                    cleanup_interval=1,
                    file_ttl=2,
                )
                
                # 创建 10 个过期文件（高于阈值 5）
                for i in range(10):
                    create_test_file(temp_input_dir, f"old_{i}.png", age_seconds=5)
                
                cleaned = cleaner.cleanup_sync()
                
                # 因为文件数 (10) >= 阈值 (5)，应该清理所有过期文件
                assert cleaned == 10
                assert len(os.listdir(temp_input_dir)) == 0
    
    def test_cleanup_at_exact_threshold(self, temp_input_dir):
        """测试文件数正好等于阈值时正常清理"""
        with patch.object(InputCleaner, '_cleanup_loop'):
            with patch.dict(os.environ, {"INPUT_CLEANUP_MIN_FILES": "5"}):
                cleaner = InputCleaner(
                    input_dir=temp_input_dir,
                    cleanup_interval=1,
                    file_ttl=2,
                )
                
                # 创建 5 个过期文件（等于阈值 5）
                for i in range(5):
                    create_test_file(temp_input_dir, f"old_{i}.png", age_seconds=5)
                
                cleaned = cleaner.cleanup_sync()
                
                # 因为文件数 (5) >= 阈值 (5)，应该清理
                assert cleaned == 5
    
    def test_threshold_counts_only_files(self, temp_input_dir):
        """测试阈值只计算文件数，不计算子目录"""
        with patch.object(InputCleaner, '_cleanup_loop'):
            with patch.dict(os.environ, {"INPUT_CLEANUP_MIN_FILES": "5"}):
                cleaner = InputCleaner(
                    input_dir=temp_input_dir,
                    cleanup_interval=1,
                    file_ttl=2,
                )
                
                # 创建 3 个文件和 3 个子目录
                for i in range(3):
                    create_test_file(temp_input_dir, f"old_{i}.png", age_seconds=5)
                    os.makedirs(os.path.join(temp_input_dir, f"subdir_{i}"))
                
                cleaned = cleaner.cleanup_sync()
                
                # 文件数 (3) < 阈值 (5)，不应清理（子目录不计入）
                assert cleaned == 0
                assert len([f for f in os.listdir(temp_input_dir) if os.path.isfile(os.path.join(temp_input_dir, f))]) == 3
    
    def test_threshold_with_mixed_files(self, temp_input_dir):
        """测试阈值与混合文件（过期和新文件）"""
        with patch.object(InputCleaner, '_cleanup_loop'):
            with patch.dict(os.environ, {"INPUT_CLEANUP_MIN_FILES": "5"}):
                cleaner = InputCleaner(
                    input_dir=temp_input_dir,
                    cleanup_interval=1,
                    file_ttl=2,
                )
                
                # 创建 3 个过期文件和 3 个新文件（总数 6，高于阈值 5）
                for i in range(3):
                    create_test_file(temp_input_dir, f"old_{i}.png", age_seconds=5)
                for i in range(3):
                    create_test_file(temp_input_dir, f"new_{i}.png", age_seconds=0)
                
                cleaned = cleaner.cleanup_sync()
                
                # 文件数 (6) >= 阈值 (5)，应该清理过期文件
                assert cleaned == 3
                assert len(os.listdir(temp_input_dir)) == 3  # 只剩新文件


# ==================== 属性测试 ====================

class TestProperties:
    """测试属性访问"""
    
    def test_properties(self, cleaner_no_auto_start, temp_input_dir):
        """测试属性返回正确的值"""
        assert cleaner_no_auto_start.input_dir == temp_input_dir
        assert cleaner_no_auto_start.cleanup_interval == 1
        assert cleaner_no_auto_start.file_ttl == 2


# ==================== 集成测试 ====================

class TestIntegration:
    """集成测试 - 模拟真实使用场景"""
    
    def test_continuous_file_generation_and_cleanup(self, temp_input_dir):
        """
        模拟持续生成文件并清理的场景
        
        场景：每 0.2 秒生成一个文件，TTL 为 1 秒，清理间隔 0.5 秒
        期望：最终目录中只保留最近 1 秒内的文件（约 5 个）
        """
        with patch.dict(os.environ, {"INPUT_CLEANUP_MIN_FILES": "0"}):
            cleaner = InputCleaner(
                input_dir=temp_input_dir,
                cleanup_interval=0.5,  # 0.5秒清理间隔
                file_ttl=1,  # 1秒过期
            )
            
            try:
                # 持续生成文件 2 秒
                for i in range(10):
                    create_test_file(temp_input_dir, f"file_{i}.png")
                    cleaner.wake()
                    time.sleep(0.2)
                
                # 等待最后一次清理
                time.sleep(1)
                cleaner.wake()
                time.sleep(0.5)
                
                # 检查剩余文件数量（应该只有最近 1 秒内的文件）
                remaining_files = os.listdir(temp_input_dir)
                
                # 由于 TTL 是 1 秒，生成间隔 0.2 秒，最多保留 5 个左右的文件
                assert len(remaining_files) <= 6, f"剩余文件数 {len(remaining_files)} 超过预期"
                
            finally:
                cleaner.stop()


# ==================== 性能测试 ====================

class TestPerformance:
    """性能测试 - 大量文件场景"""
    
    def test_cleanup_10000_files_mixed(self, temp_input_dir):
        """
        测试大量文件清理性能
        
        场景：10000 个文件，50% 过期，50% 未过期
        期望：清理耗时在合理范围内（< 10 秒）
        """
        with patch.object(InputCleaner, '_cleanup_loop'):
            with patch.dict(os.environ, {"INPUT_CLEANUP_MIN_FILES": "0"}):
                cleaner = InputCleaner(
                    input_dir=temp_input_dir,
                    cleanup_interval=1,
                    file_ttl=2,
                )
                
                total_files = 10000
                expired_count = total_files // 2
                fresh_count = total_files - expired_count
                
                print(f"\n创建 {total_files} 个测试文件...")
                start_create = time.time()
                
                # 创建过期文件
                for i in range(expired_count):
                    create_test_file(temp_input_dir, f"expired_{i}.png", age_seconds=5)
                
                # 创建新文件
                for i in range(fresh_count):
                    create_test_file(temp_input_dir, f"fresh_{i}.png", age_seconds=0)
                
                create_elapsed = time.time() - start_create
                print(f"文件创建耗时: {create_elapsed:.2f}s")
                
                # 验证文件数量
                actual_files = len(os.listdir(temp_input_dir))
                assert actual_files == total_files, f"文件数量不匹配: {actual_files} != {total_files}"
                
                # 执行清理并计时
                print(f"开始清理...")
                start_cleanup = time.time()
                cleaned = cleaner.cleanup_sync()
                cleanup_elapsed = time.time() - start_cleanup
                
                print(f"清理完成: 删除 {cleaned} 个文件，耗时 {cleanup_elapsed:.2f}s")
                
                # 验证结果
                assert cleaned == expired_count, f"清理数量不匹配: {cleaned} != {expired_count}"
                
                remaining_files = len(os.listdir(temp_input_dir))
                assert remaining_files == fresh_count, f"剩余文件数不匹配: {remaining_files} != {fresh_count}"
                
                # 性能断言：清理 10000 个文件应该在 10 秒内完成
                assert cleanup_elapsed < 10, f"清理耗时过长: {cleanup_elapsed:.2f}s > 10s"
                
                print(f"性能指标: {cleaned / cleanup_elapsed:.0f} 文件/秒")
    
    def test_cleanup_10000_files_all_expired(self, temp_input_dir):
        """
        测试大量过期文件清理性能
        
        场景：10000 个文件，全部过期
        """
        with patch.object(InputCleaner, '_cleanup_loop'):
            with patch.dict(os.environ, {"INPUT_CLEANUP_MIN_FILES": "0"}):
                cleaner = InputCleaner(
                    input_dir=temp_input_dir,
                    cleanup_interval=1,
                    file_ttl=2,
                )
                
                total_files = 10000
                
                print(f"\n创建 {total_files} 个过期文件...")
                start_create = time.time()
                
                for i in range(total_files):
                    create_test_file(temp_input_dir, f"expired_{i}.png", age_seconds=5)
                
                create_elapsed = time.time() - start_create
                print(f"文件创建耗时: {create_elapsed:.2f}s")
                
                # 执行清理并计时
                print(f"开始清理...")
                start_cleanup = time.time()
                cleaned = cleaner.cleanup_sync()
                cleanup_elapsed = time.time() - start_cleanup
                
                print(f"清理完成: 删除 {cleaned} 个文件，耗时 {cleanup_elapsed:.2f}s")
                
                # 验证结果
                assert cleaned == total_files
                assert len(os.listdir(temp_input_dir)) == 0
                
                # 性能断言
                assert cleanup_elapsed < 10, f"清理耗时过长: {cleanup_elapsed:.2f}s > 10s"
                
                print(f"性能指标: {cleaned / cleanup_elapsed:.0f} 文件/秒")
    
    def test_cleanup_10000_files_none_expired(self, temp_input_dir):
        """
        测试大量未过期文件的扫描性能
        
        场景：10000 个文件，全部未过期（只扫描不删除）
        注意：TTL 设为 60 秒，确保文件创建期间不会过期
        """
        with patch.object(InputCleaner, '_cleanup_loop'):
            with patch.dict(os.environ, {"INPUT_CLEANUP_MIN_FILES": "0"}):
                cleaner = InputCleaner(
                    input_dir=temp_input_dir,
                    cleanup_interval=1,
                    file_ttl=60,  # 60秒 TTL，确保创建期间不过期
                )
                
                total_files = 10000
                
                print(f"\n创建 {total_files} 个新文件...")
                start_create = time.time()
                
                for i in range(total_files):
                    create_test_file(temp_input_dir, f"fresh_{i}.png", age_seconds=0)
                
                create_elapsed = time.time() - start_create
                print(f"文件创建耗时: {create_elapsed:.2f}s")
                
                # 执行清理并计时（应该只扫描，不删除）
                print(f"开始扫描...")
                start_cleanup = time.time()
                cleaned = cleaner.cleanup_sync()
                cleanup_elapsed = time.time() - start_cleanup
                
                print(f"扫描完成: 删除 {cleaned} 个文件，耗时 {cleanup_elapsed:.2f}s")
                
                # 验证结果
                assert cleaned == 0, "不应删除任何文件"
                assert len(os.listdir(temp_input_dir)) == total_files
                
                # 性能断言：纯扫描应该更快
                assert cleanup_elapsed < 5, f"扫描耗时过长: {cleanup_elapsed:.2f}s > 5s"
                
                print(f"性能指标: {total_files / cleanup_elapsed:.0f} 文件/秒 (扫描)")


# ==================== 模块级函数测试 ====================

class TestModuleFunctions:
    """测试模块级便捷函数"""
    
    def test_wake_function_when_disabled(self):
        """测试清理器禁用时 wake() 不报错"""
        from services.serverlessapi import input_cleaner
        
        # 保存原始实例
        original_instance = input_cleaner._cleaner_instance
        
        try:
            # 设置为 None 模拟禁用状态
            input_cleaner._cleaner_instance = None
            
            # 不应该抛出异常
            input_cleaner.wake()
            
        finally:
            # 恢复原始实例
            input_cleaner._cleaner_instance = original_instance
    
    def test_get_cleaner_returns_instance(self):
        """测试 get_cleaner() 返回实例"""
        from services.serverlessapi.input_cleaner import get_cleaner, _cleaner_instance
        
        result = get_cleaner()
        assert result is _cleaner_instance


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

