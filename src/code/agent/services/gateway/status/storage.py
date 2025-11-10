"""
Status Storage Service
处理状态存储相关的逻辑
"""
import os
import json
import threading

from store import Store, FileSystem
import constants
from utils.logger import log


class StatusStorageService:
    """状态存储服务，负责状态的读取（写入由 ServerlessApiService 直接处理）"""
    
    def __init__(self, store: Store = None):
        """
        初始化状态存储服务
        
        Args:
            store: 存储实例，如果为None则使用默认的FileSystem存储
        """
        if store is None:
            self.store: Store = FileSystem(f"{constants.MNT_DIR}/output/serverless_api")
        else:
            self.store = store
            
        # 增量文件读取缓存
        self._file_read_cache = {}  # task_id -> {"position": int, "last_modified": float}
        self._cache_lock = threading.Lock()
    
    def get_status(self, task_id: str):
        """
        从持久化存储中读取任务状态历史
        
        Args:
            task_id: 任务 ID
            
        Returns:
            list: 状态历史列表，每个元素是一条状态消息（已解析为字典）
        """
        if not self.store or not task_id:
            return []
        
        try:
            value = self.store.get(task_id)
            if not value:
                return []
            
            statuses = []
            for line in value.split("\n"):
                if line.strip():
                    try:
                        statuses.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        log("WARNING", f"Failed to parse status line for task {task_id}: {line[:100]}... Error: {e}")
                        continue
            
            return statuses
        except Exception as e:
            log("ERROR", f"Error reading status for task {task_id}: {e}")
            return []
    
    def get_status_incremental(self, task_id: str):
        """
        增量读取状态文件，减少I/O开销
        
        Args:
            task_id: 任务ID
            
        Returns:
            list: 新增的状态列表（相对于上次读取）
        """
        if not self.store or not task_id:
            return []
        
        # 获取文件路径（使用FileSystem store的正确属性）
        if hasattr(self.store, 'output_folder'):
            file_path = os.path.join(self.store.output_folder, task_id)
        else:
            # 回退到原始方法，如果store类型不是FileSystem
            log("WARNING", f"Store type {type(self.store)} not supported for incremental reading")
            return self.get_status(task_id)

        if not os.path.exists(file_path):
            return []
        
        try:
            import time as perf_time
            perf_start = perf_time.time()
            
            # 强制刷新 NFS 目录缓存：先 listdir 触发目录元数据更新
            listdir_start = perf_time.time()
            try:
                dir_path = os.path.dirname(file_path)
                os.listdir(dir_path)  # 强制刷新目录缓存
            except Exception as e:
                log("DEBUG", f"listdir failed for {task_id}: {e}")
            listdir_cost = (perf_time.time() - listdir_start) * 1000
            log("DEBUG", f"[Perf][{task_id}] listdir cost: {listdir_cost:.1f}ms")
            
            # 关键：使用 os.open + os.fstat 绕过 Python 的 stat 缓存
            # os.stat() 可能读取缓存的元数据，而 os.fstat(fd) 直接从文件描述符获取
            fstat_start = perf_time.time()
            try:
                fd = os.open(file_path, os.O_RDONLY)
                file_stat = os.fstat(fd)
                os.close(fd)
            except Exception as e:
                log("DEBUG", f"Fallback to regular stat for {task_id}: {e}")
                file_stat = os.stat(file_path)
            
            stat_time = (perf_time.time() - fstat_start) * 1000
            log("DEBUG", f"[Perf][{task_id}] fstat cost: {stat_time:.1f}ms")
            
            current_size = file_stat.st_size
            current_modified = file_stat.st_mtime
            
            with self._cache_lock:
                cache_info = self._file_read_cache.get(task_id, {
                    "position": 0,
                    "last_modified": 0
                })
                
                last_position = cache_info["position"]
                last_modified = cache_info["last_modified"]
                
                # 如果文件没有变化，直接返回空列表
                if (current_modified == last_modified and
                    current_size <= last_position):
                    return []
                
                # 如果文件被重写（修改时间变化且大小比上次记录的位置小），重置位置
                if current_modified != last_modified and current_size < last_position:
                    last_position = 0
                    log("WARNING", f"File {task_id} was rewritten, reset read position")
                
                # 读取新增内容 - 使用无缓冲模式
                new_statuses = []
                read_start = perf_time.time()
                
                # 使用 buffering=0 和 binary 模式读取，绕过 Python 的缓冲层
                with open(file_path, 'rb', buffering=0) as f:
                    # 定位到上次读取位置
                    f.seek(last_position)
                    
                    # 读取新增内容（二进制模式）
                    new_content_bytes = f.read()
                    new_position = f.tell()
                
                read_cost = (perf_time.time() - read_start) * 1000
                log("DEBUG", f"[Perf][{task_id}] file read cost: {read_cost:.1f}ms, bytes={len(new_content_bytes)}")
                
                parse_start = perf_time.time()
                # 解码为文本
                new_content = new_content_bytes.decode('utf-8', errors='ignore')
                
                if new_content.strip():
                    # 按行解析JSON
                    for line in new_content.strip().split('\n'):
                        if line.strip():
                            try:
                                status_data = json.loads(line)
                                new_statuses.append(status_data)
                            except json.JSONDecodeError as e:
                                log("WARNING", f"Failed to parse status line for task {task_id}: {line[:100]}... Error: {e}")
                                continue
                
                parse_cost = (perf_time.time() - parse_start) * 1000
                log("DEBUG", f"[Perf][{task_id}] parse cost: {parse_cost:.1f}ms")
                
                # 更新缓存
                self._file_read_cache[task_id] = {
                    "position": new_position,
                    "last_modified": current_modified
                }
                
                total_cost = (perf_time.time() - perf_start) * 1000
                
                if new_statuses:
                    log("INFO", f"[Perf][{task_id}] get_status_incremental total: {total_cost:.1f}ms "
                          f"(listdir={listdir_cost:.1f}ms, fstat={stat_time:.1f}ms, read={read_cost:.1f}ms, parse={parse_cost:.1f}ms), "
                          f"got {len(new_statuses)} statuses, position: {last_position} -> {new_position}")
                
                return new_statuses
        
        except Exception as e:
            log("ERROR", f"Error reading incremental status for task {task_id}: {e}")
            # 发生错误时，清理缓存并回退到原始方法
            with self._cache_lock:
                self._file_read_cache.pop(task_id, None)
            return self.get_status(task_id)
    
    def cleanup_cache(self, task_id: str = None):
        """
        清理状态读取缓存
        
        Args:
            task_id: 指定任务ID，如果为None则清理所有缓存
        """
        with self._cache_lock:
            if task_id:
                self._file_read_cache.pop(task_id, None)
                log("DEBUG", f"Cleaned status cache for task {task_id}")
            else:
                cache_count = len(self._file_read_cache)
                self._file_read_cache.clear()
                log("DEBUG", f"Cleaned all status cache ({cache_count} entries)")


# 全局实例（线程安全的单例）
_storage_service = None
_storage_service_lock = threading.Lock()

def get_status_storage_service() -> StatusStorageService:
    """获取全局状态存储服务实例（线程安全的单例模式）"""
    global _storage_service
    if _storage_service is None:
        with _storage_service_lock:
            if _storage_service is None:
                _storage_service = StatusStorageService()
    return _storage_service

