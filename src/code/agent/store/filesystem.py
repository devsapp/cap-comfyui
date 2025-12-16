import os
import threading
import time

from utils.logger import log


class FileSystem:

    def __init__(self, output_folder: str):
        self.output_folder = output_folder
        
        # NFS 缓存刷新相关
        self._cache_refresh_enabled = True
        self._cache_refresh_interval = 1.0  # 每1秒刷新一次
        self._cache_refresh_thread = None
        self._start_cache_refresh_thread()

    def __file_path(self, key: str):
        return os.path.join(self.output_folder, key)

    def get(self, key: str) -> str:
        """读取文件内容
        
        采用优化的缓存策略：
        1. 首先尝试直接打开文件（最快路径，Page Cache Hit / GETATTR + READ）
        2. 如果捕获到 ENOENT 错误，表示文件在客户端缓存中不可见
        3. 强制刷新目录缓存（执行 listdir，触发 READDIR RPC）
        4. 重试读取文件内容
        
        Args:
            key: 文件键名
        
        Returns:
            文件内容字符串
        """
        file_path = self.__file_path(key)
        
        # 第一次尝试：直接读取文件
        # 先调用 os.stat() 强制刷新 NFS 属性缓存
        try:
            os.stat(file_path)  # 强制刷新文件属性缓存
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            # 捕获 ENOENT 错误：文件在客户端缓存中不可见
            # 强制刷新目录缓存（执行昂贵的 listdir 操作）
            try:
                if os.path.exists(self.output_folder):
                    os.listdir(self.output_folder)
            except Exception:
                pass
            
            # 重试读取文件内容
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    return f.read()
            except FileNotFoundError:
                # 文件确实不存在，返回空字符串
                return ""
            except Exception as e:
                log("ERROR", f"Error reading file {file_path}: {type(e).__name__}: {str(e)}")
                return ""
        except Exception as e:
            # 其他非 ENOENT 错误
            log("ERROR", f"Error reading file {file_path}: {type(e).__name__}: {str(e)}")
            return ""

    def put(self, key: str, value: str):
        try:
            os.makedirs(self.output_folder, exist_ok=True)

            with open(self.__file_path(key), "w", encoding="utf-8") as f:
                f.write(value)
        except Exception as e:
            log("ERROR", f"Error writing file {self.__file_path(key)}: {type(e).__name__}: {str(e)}")
    
    def _start_cache_refresh_thread(self):
        """启动后台线程定期刷新 NFS 目录缓存"""
        if self._cache_refresh_thread and self._cache_refresh_thread.is_alive():
            return
        
        self._cache_refresh_thread = threading.Thread(
            target=self._cache_refresh_loop,
            daemon=True,
            name="nfs-cache-refresh"
        )
        self._cache_refresh_thread.start()
    
    def refresh_cache(self):
        """主动刷新 NFS 目录缓存
        
        用于解决实例冻结导致的缓存问题，确保能获取到最新文件。
        建议在读取关键文件前调用此方法。
        """
        try:
            if os.path.exists(self.output_folder):
                os.listdir(self.output_folder)
        except Exception as e:
            # 忽略错误，静默失败
            pass
    
    def _cache_refresh_loop(self):
        """后台线程：定期执行 listdir 刷新 NFS 目录缓存"""
        while self._cache_refresh_enabled:
            # 使用统一的刷新方法
            self.refresh_cache()
            # 等待下次刷新
            time.sleep(self._cache_refresh_interval)
