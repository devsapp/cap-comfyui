"""
Input 目录清理模块

用于清理 ComfyUI input 目录中的过期临时文件（自动上传的图片/音频/视频）。
适用于 Serverless 架构，支持 CPU freeze/unfreeze 场景。

仅在 API 模式且 INPUT_DIR 使用实例磁盘（非 MNT_INPUT_DIR）时启用。

使用方式:
    from services.serverlessapi.input_cleaner import wake
    wake()  # 在请求中调用，唤醒清理线程（如果清理器未启用则无操作）
"""

import os
import time
import threading
from typing import Optional

import constants
from utils.logger import log


class InputCleaner:
    """
    Input 目录清理器（Event 唤醒模式）
    
    后台线程大部分时间休眠，由请求唤醒执行清理。
    多个并发请求的唤醒信号会合并为一次。
    
    特性:
    - 惰性清理：后台线程休眠，由请求唤醒
    - 线程安全：多个并发唤醒信号合并为一次
    - Serverless 友好：无请求时不执行任何操作
    """
    
    def __init__(
        self,
        input_dir: Optional[str] = None,
        cleanup_interval: Optional[int] = None,
        file_ttl: Optional[int] = None,
    ):
        """
        初始化清理器
        
        Args:
            input_dir: 要清理的目录，默认使用 constants.INPUT_DIR
            cleanup_interval: 清理间隔（秒），默认 3600（1小时）
            file_ttl: 文件过期时间（秒），默认 21600（6小时）
            min_files_threshold: 最小文件数阈值，低于此数量不清理，默认 1000
        """
        self._input_dir = input_dir or constants.INPUT_DIR
        self._cleanup_interval = cleanup_interval or int(os.getenv("INPUT_CLEANUP_INTERVAL", "3600"))  # 默认1小时
        self._file_ttl = file_ttl or int(os.getenv("INPUT_FILE_TTL", "21600"))  # 默认6小时
        self._min_files_threshold = int(os.getenv("INPUT_CLEANUP_MIN_FILES", "1000"))  # 默认1000个文件
        
        self._last_cleanup_time = 0
        self._wake_event = threading.Event()  # 唤醒信号
        self._stop_event = threading.Event()  # 停止信号
        
        # 启动后台清理线程
        self._thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._thread.start()
        
        log("DEBUG", f"InputCleaner initialized: dir={self._input_dir}, interval={self._cleanup_interval}s, ttl={self._file_ttl}s, min_files={self._min_files_threshold}")
    
    def wake(self):
        """
        唤醒清理线程（请求时调用）
        
        多个并发请求调用 wake() 只会触发一次清理。
        如果距离上次清理时间不足 cleanup_interval，清理线程会忽略本次唤醒。
        """
        self._wake_event.set()
    
    def _cleanup_loop(self):
        """后台清理线程主循环"""
        while not self._stop_event.is_set():
            # 等待唤醒信号（Serverless 架构下无请求时实例会 freeze，无需超时兜底）
            self._wake_event.wait()
            
            # 清除唤醒信号（为下次唤醒做准备）
            self._wake_event.clear()
            
            # 检查是否需要停止
            if self._stop_event.is_set():
                break
            
            # 检查距离上次清理是否足够长
            now = time.time()
            if now - self._last_cleanup_time < self._cleanup_interval:
                log("DEBUG", "InputCleaner: awakened but skipped (too soon since last cleanup)")
                continue
            
            # 执行清理
            self._last_cleanup_time = now
            try:
                start_time = time.time()
                cleaned = self._cleanup_old_files()
                elapsed = time.time() - start_time
                if cleaned > 0:
                    log("INFO", f"InputCleaner: async cleanup completed, removed {cleaned} files from {self._input_dir} in {elapsed:.2f}s")
            except Exception as e:
                log("WARNING", f"InputCleaner: async cleanup failed: {e}")
    
    def stop(self):
        """停止清理线程"""
        self._stop_event.set()
        self._wake_event.set()  # 唤醒线程以便它能检查停止信号
        self._thread.join(timeout=5)
    
    def cleanup_sync(self) -> int:
        """
        同步执行清理（阻塞当前线程）
        
        Returns:
            int: 清理的文件数量
        """
        return self._cleanup_old_files()
    
    def _cleanup_old_files(self) -> int:
        """
        清理过期文件
        
        使用 os.scandir() 高效遍历目录，删除超过 TTL 的文件。
        注意：只清理目录下的一级文件，不会递归清理子目录。
        当文件数量低于 min_files_threshold 时跳过清理。
        
        Returns:
            int: 清理的文件数量
        """
        log("DEBUG", f"InputCleaner: starting cleanup scan on {self._input_dir}")
        
        if not os.path.exists(self._input_dir):
            return 0
        
        # 先统计文件数量，低于阈值则跳过清理
        try:
            file_count = sum(1 for entry in os.scandir(self._input_dir) if entry.is_file())
            if file_count < self._min_files_threshold:
                log("DEBUG", f"InputCleaner: skipped cleanup, file count ({file_count}) below threshold ({self._min_files_threshold})")
                return 0
        except Exception as e:
            log("WARNING", f"InputCleaner: failed to count files: {e}")
            return 0
        
        now = time.time()
        cleaned = 0
        
        try:
            with os.scandir(self._input_dir) as entries:
                for entry in entries:
                    try:
                        # entry.is_file() 和 entry.stat() 使用缓存的 stat 结果
                        if entry.is_file():
                            file_age = now - entry.stat().st_mtime
                            if file_age > self._file_ttl:
                                os.remove(entry.path)
                                cleaned += 1
                    except FileNotFoundError:
                        # 文件可能被其他进程删除，忽略
                        pass
                    except Exception as e:
                        log("DEBUG", f"InputCleaner: failed to process {entry.name}: {e}")
        except Exception as e:
            log("WARNING", f"InputCleaner: failed to scan directory {self._input_dir}: {e}")
        
        return cleaned
    
    @property
    def is_running(self) -> bool:
        """检查清理线程是否在运行"""
        return self._thread.is_alive()
    
    @property
    def input_dir(self) -> str:
        """获取清理目录路径"""
        return self._input_dir
    
    @property
    def file_ttl(self) -> int:
        """获取文件过期时间（秒）"""
        return self._file_ttl
    
    @property
    def cleanup_interval(self) -> int:
        """获取清理间隔（秒）"""
        return self._cleanup_interval


# ============================================================================
# 模块级单例和便捷函数
# ============================================================================

# 全局清理器实例（仅在满足条件时初始化）
_cleaner_instance: Optional[InputCleaner] = None


def _should_enable_cleaner() -> bool:
    """判断是否应该启用清理器"""
    # 仅在 API 模式且 INPUT_DIR 使用实例磁盘（非共享存储）时启用
    return constants.USE_API_MODE and constants.INPUT_DIR != constants.MNT_INPUT_DIR


def _init_cleaner():
    """初始化全局清理器实例"""
    global _cleaner_instance
    if _cleaner_instance is None and _should_enable_cleaner():
        _cleaner_instance = InputCleaner()
        log("INFO", f"InputCleaner enabled: INPUT_DIR={constants.INPUT_DIR}")
    elif not _should_enable_cleaner():
        log("DEBUG", f"InputCleaner disabled: USE_API_MODE={constants.USE_API_MODE}, INPUT_DIR={constants.INPUT_DIR}, MNT_INPUT_DIR={constants.MNT_INPUT_DIR}")


def wake():
    """
    唤醒清理线程（便捷函数）
    
    如果清理器未启用，则不执行任何操作。
    """
    if _cleaner_instance is not None:
        _cleaner_instance.wake()


def get_cleaner() -> Optional[InputCleaner]:
    """获取全局清理器实例（可能为 None）"""
    return _cleaner_instance


# 模块加载时自动初始化
_init_cleaner()
