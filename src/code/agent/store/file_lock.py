"""
文件锁实现 - 支持 NAS 上的分布式锁
"""
import os
import time
import fcntl
import json
from typing import Optional
from utils.logger import log
import constants


class FileLock:
    """基于文件的分布式锁
    
    使用 fcntl.flock 实现跨进程/跨实例的文件锁
    支持超时和自动过期机制
    """
    
    def __init__(self, lock_file_path: str, timeout: int = None):
        """
        Args:
            lock_file_path: 锁文件的完整路径
            timeout: 锁超时时间（秒），None 表示使用默认值
        """
        self.lock_file_path = lock_file_path
        self.timeout = timeout or constants.QUEUE_LOCK_TIMEOUT
        self.lock_file = None
        self._is_locked = False
        
    def acquire(self, blocking: bool = True) -> bool:
        """获取锁
        
        Args:
            blocking: 是否阻塞等待
            
        Returns:
            bool: 是否成功获取锁
        """
        # 如果已经持有锁，直接返回
        if self._is_locked:
            return True
        
        try:
            # 确保锁文件目录存在
            lock_dir = os.path.dirname(self.lock_file_path)
            if lock_dir:  # 避免空目录路径
                os.makedirs(lock_dir, exist_ok=True)
            
            # 打开锁文件（使用 'a+' 模式，如果文件不存在则创建）
            self.lock_file = open(self.lock_file_path, 'a+')
            
            # 尝试获取锁
            start_time = time.time()
            while True:
                try:
                    # 非阻塞方式尝试获取锁
                    fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    
                    # 成功获取锁，写入锁信息
                    lock_info = {
                        'instance_id': constants.INSTANCE_ID,
                        'acquired_at': time.time(),
                        'timeout': self.timeout
                    }
                    self.lock_file.seek(0)
                    self.lock_file.truncate()
                    json.dump(lock_info, self.lock_file)
                    self.lock_file.flush()
                    os.fsync(self.lock_file.fileno())
                    
                    # 只有在所有操作成功后才设置锁标志
                    self._is_locked = True
                    return True
                    
                except BlockingIOError:
                    # 锁被占用
                    if not blocking:
                        self._cleanup_file()
                        return False
                    
                    # 检查是否超时
                    elapsed = time.time() - start_time
                    if elapsed >= self.timeout:
                        log("WARNING", f"Lock acquisition timeout after {elapsed:.2f}s: {self.lock_file_path}")
                        self._cleanup_file()
                        return False
                    
                    # 短暂等待后重试
                    time.sleep(0.1)
                    
        except Exception as e:
            log("ERROR", f"Error acquiring lock {self.lock_file_path}: {e}")
            self._cleanup_file()
            return False
    
    def release(self):
        """释放锁"""
        if not self._is_locked:
            return
        
        try:
            if self.lock_file:
                # 释放文件锁
                fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
                self._is_locked = False
        except Exception as e:
            log("ERROR", f"Error releasing lock {self.lock_file_path}: {e}")
        finally:
            self._cleanup_file()
    
    def _cleanup_file(self):
        """清理文件句柄"""
        if self.lock_file:
            try:
                self.lock_file.close()
            except Exception:
                # 忽略关闭文件时的异常（文件可能已经被关闭或删除）
                pass
            self.lock_file = None
    
    def __enter__(self):
        """上下文管理器入口"""
        if not self.acquire(blocking=True):
            raise TimeoutError(f"Failed to acquire lock: {self.lock_file_path}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器退出"""
        self.release()
    
    def __del__(self):
        """析构时确保释放锁"""
        if self._is_locked:
            self.release()

