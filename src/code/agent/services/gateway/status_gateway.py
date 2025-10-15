"""
Status Gateway Service
处理状态存储、轮询和获取相关的逻辑
"""
import os
import json
import time
import threading
from typing import Optional, Callable, Any

from store import Store, FileSystem
import constants
from utils.logger import log


class StatusStorageService:
    """状态存储服务，负责状态的持久化读写"""
    
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
    
    def put_status(self, task_id: str, status: str):
        """
        保存任务状态到持久化存储
        
        Args:
            task_id: 任务 ID
            status: 状态信息（JSON 字符串）
        """
        if task_id and self.store:
            try:
                value = self.store.get(task_id)
                self.store.put(task_id, f"{value}\n{status}")
            except Exception as e:
                log("ERROR", f"put status to store failed, due to {e}")
    
    def get_status(self, task_id: str):
        """
        从持久化存储中读取任务状态历史
        
        Args:
            task_id: 任务 ID
            
        Returns:
            list: 状态历史列表，每个元素是一条状态消息（已解析为字典）
        """
        if self.store:
            value = self.store.get(task_id)
            return [json.loads(line) for line in value.split("\n") if line]
        else:
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
            print(f"[StatusStorage] Store type {type(self.store)} not supported for incremental reading")
            return self.get_status(task_id)
        
        # 检查文件是否存在
        if not os.path.exists(file_path):
            return []
        
        try:
            # 强制刷新NAS客户端缓存：先读取1字节再关闭，触发缓存更新
            try:
                with open(file_path, 'rb') as f:
                    f.read(1)  # 读取1字节强制刷新元数据
            except:
                pass
            
            # 获取文件状态
            file_stat = os.stat(file_path)
            current_size = file_stat.st_size
            current_modified = file_stat.st_mtime
            
            with self._cache_lock:
                # 获取缓存状态
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
                    print(f"[StatusStorage] File {task_id} was rewritten, reset read position")
                
                # 读取新增内容
                new_statuses = []
                with open(file_path, 'r', encoding='utf-8') as f:
                    # 定位到上次读取位置
                    f.seek(last_position)
                    
                    # 读取新增内容
                    new_content = f.read()
                    new_position = f.tell()
                    
                    if new_content.strip():
                        # 按行解析JSON
                        for line in new_content.strip().split('\n'):
                            if line.strip():
                                try:
                                    status_data = json.loads(line)
                                    new_statuses.append(status_data)
                                except json.JSONDecodeError as e:
                                    print(f"[StatusStorage] Failed to parse status line for task {task_id}: {line[:100]}... Error: {e}")
                                    continue
                
                # 更新缓存
                self._file_read_cache[task_id] = {
                    "position": new_position,
                    "last_modified": current_modified
                }
                
                if new_statuses:
                    print(f"[StatusStorage] Read {len(new_statuses)} new status updates for task {task_id} "
                          f"(position: {last_position} -> {new_position})")
                
                return new_statuses
        
        except Exception as e:
            print(f"[StatusStorage] Error reading incremental status for task {task_id}: {e}")
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
                print(f"[StatusStorage] Cleaned status cache for task {task_id}")
            else:
                cache_count = len(self._file_read_cache)
                self._file_read_cache.clear()
                print(f"[StatusStorage] Cleaned all status cache ({cache_count} entries)")


class StatusPoller:
    """
    状态轮询器
    用于定期从存储中轮询工作流执行状态
    """
    
    def __init__(self, task_id: str, storage_service: StatusStorageService, poll_interval: float = 1.0):
        """
        初始化状态轮询器
        
        Args:
            task_id: 要轮询的任务ID
            storage_service: 状态存储服务实例
            poll_interval: 轮询间隔，单位秒，默认1.0秒
        """
        self.task_id = task_id
        self.storage_service = storage_service
        self.poll_interval = poll_interval
        self.is_running = False
        self.thread: Optional[threading.Thread] = None
        self.on_status_update: Optional[Callable[[str, Any], None]] = None
        
    def set_status_callback(self, callback: Callable[[str, Any], None]):
        """
        设置状态更新回调函数
        
        Args:
            callback: 回调函数，参数为 (task_id, status_data)
        """
        self.on_status_update = callback
        
    def start(self):
        """启动轮询线程"""
        if self.is_running:
            print(f"[StatusPoller] Task {self.task_id} poller is already running")
            return
            
        self.is_running = True
        self.thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.thread.start()
        print(f"[StatusPoller] Started polling for task {self.task_id}")
        
    def stop(self):
        """停止轮询线程"""
        if not self.is_running:
            return
            
        self.is_running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5.0)
        print(f"[StatusPoller] Stopped polling for task {self.task_id}")
        
    def _poll_loop(self):
        """轮询循环逻辑（使用增量文件读取）"""
        from datetime import datetime
        start_time = time.time()
        print(f"[StatusPoller] Poll loop started for task {self.task_id} at {datetime.now().strftime('%H:%M:%S.%f')[:-3]} (using incremental file reading)")
        
        # 是否已找到任务完成状态
        task_completed = False
        poll_count = 0
        
        while self.is_running and not task_completed:
            poll_count += 1
            poll_start = time.time()
            elapsed = poll_start - start_time
            
            try:
                print(f"[StatusPoller] Task {self.task_id}: Poll #{poll_count} at {datetime.now().strftime('%H:%M:%S.%f')[:-3]} (elapsed: {elapsed:.2f}s)")
                
                # 使用增量文件读取，仅获取新增状态
                new_statuses = self.storage_service.get_status_incremental(self.task_id)
                
                if new_statuses:
                    print(f"[StatusPoller] Task {self.task_id}: Found {len(new_statuses)} new status updates")
                    
                    # 调用回调函数处理新状态
                    for status in new_statuses:
                        if self.on_status_update:
                            self.on_status_update(self.task_id, status)
                        else:
                            # 默认输出到控制台
                            print(f"[StatusPoller] Task {self.task_id} status update: {json.dumps(status, ensure_ascii=False)}")
                        
                        # 检查是否为任务完成状态
                        if self._is_status_completed(status):
                            print(f"[StatusPoller] Task {self.task_id} completed, stopping poller")
                            task_completed = True
                            break
                else:
                    print(f"[StatusPoller] Task {self.task_id}: No new status updates (poll took {time.time() - poll_start:.3f}s)")
                    
            except Exception as e:
                print(f"[StatusPoller] Error polling task {self.task_id}: {e}")
                from traceback import print_exception
                print_exception(e)
            
            # 等待下次轮询
            if not task_completed:
                print(f"[StatusPoller] Task {self.task_id}: Sleeping {self.poll_interval}s until next poll")
                time.sleep(self.poll_interval)
            
        self.is_running = False
        print(f"[StatusPoller] Poll loop ended for task {self.task_id}")
        
        # 清理状态读取缓存
        try:
            self.storage_service.cleanup_cache(self.task_id)
        except Exception as e:
            print(f"[StatusPoller] Error cleaning up cache for task {self.task_id}: {e}")
    
    def _is_status_completed(self, status: dict) -> bool:
        """
        检查单个状态是否表示任务完成
        
        Args:
            status: 单个状态对象
            
        Returns:
            True if status indicates task completion, False otherwise
        """
        if not status:
            return False
        
        status_type = status.get("type", "")
        
        # 如果是最终结果（serverless_api类型）或错误状态，认为任务完成
        if status_type in ["serverless_api", "error", "execution_error"]:
            return True
            
        return False


class StatusPollerManager:
    """
    状态轮询器管理器
    管理多个任务的轮询器
    """
    
    def __init__(self, storage_service: StatusStorageService = None):
        """
        初始化轮询管理器
        
        Args:
            storage_service: 状态存储服务实例，如果为None则创建新实例
        """
        self.storage_service = storage_service or StatusStorageService()
        self.pollers: dict[str, StatusPoller] = {}
        self.lock = threading.Lock()
        
    def start_polling(self, task_id: str, poll_interval: float = 2.0, 
                     callback: Optional[Callable[[str, Any], None]] = None) -> StatusPoller:
        """
        开始轮询指定任务
        
        Args:
            task_id: 任务ID
            poll_interval: 轮询间隔（默认2秒）
            callback: 状态更新回调函数
            
        Returns:
            StatusPoller实例
        """
        with self.lock:
            if task_id in self.pollers:
                print(f"[StatusPollerManager] Task {task_id} is already being polled")
                return self.pollers[task_id]
                
            poller = StatusPoller(task_id, self.storage_service, poll_interval)
            if callback:
                poller.set_status_callback(callback)
            
            poller.start()
            self.pollers[task_id] = poller
            
            print(f"[StatusPollerManager] Started polling for task {task_id}")
            return poller
            
    def stop_polling(self, task_id: str):
        """
        停止轮询指定任务
        
        Args:
            task_id: 任务ID
        """
        with self.lock:
            if task_id in self.pollers:
                poller = self.pollers.pop(task_id)
                poller.stop()
                print(f"[StatusPollerManager] Stopped polling for task {task_id}")
            else:
                print(f"[StatusPollerManager] Task {task_id} is not being polled")
                
    def stop_all(self):
        """停止所有轮询"""
        with self.lock:
            task_ids = list(self.pollers.keys())
            for task_id in task_ids:
                self.stop_polling(task_id)
            print(f"[StatusPollerManager] Stopped all {len(task_ids)} pollers")
            
    def get_active_tasks(self) -> list[str]:
        """获取正在轮询的任务列表"""
        with self.lock:
            return list(self.pollers.keys())


# 全局实例
_storage_service = None
_poller_manager = None

def get_status_storage_service() -> StatusStorageService:
    """获取全局状态存储服务实例"""
    global _storage_service
    if _storage_service is None:
        _storage_service = StatusStorageService()
    return _storage_service

def get_poller_manager() -> StatusPollerManager:
    """获取全局轮询管理器实例"""
    global _poller_manager
    if _poller_manager is None:
        _poller_manager = StatusPollerManager(get_status_storage_service())
    return _poller_manager
