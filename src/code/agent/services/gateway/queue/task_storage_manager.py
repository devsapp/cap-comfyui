"""
任务存储管理器 - 处理NAS持久化逻辑
"""
import os
import json
import time
import traceback
from typing import Dict, Optional, Callable, List

import constants
from .task_models import TaskStatus, Task
from store.file_lock import FileLock
from store.filesystem import FileSystem
from utils.logger import log


class TaskStorageManager:
    """管理任务的NAS持久化存储"""
    
    # 状态到索引键的映射
    _STATUS_TO_KEY = {
        TaskStatus.PENDING: 'pending',
        TaskStatus.PROCESSING: 'processing'
    }
    _INDEX_KEYS = ['pending', 'processing']
    
    def __init__(self):
        """初始化任务存储管理器"""
        self._get_task = None
        self._add_task_to_memory = None
        self._start_polling = None
        
        if constants.QUEUE_STORAGE_TYPE == 'nas':
            self.base_dir = constants.QUEUE_NAS_DIR
            self.lock_file = os.path.join(self.base_dir, '.locks', 'queue.lock')
            os.makedirs(os.path.join(self.base_dir, 'tasks'), exist_ok=True)
            os.makedirs(os.path.dirname(self.lock_file), exist_ok=True)
            self.fs = FileSystem(self.base_dir)
            self._init_index()
            log("INFO", f"TaskStorageManager initialized at {self.base_dir}")
        else:
            self.base_dir = self.lock_file = self.fs = None
    
    def set_callbacks(self,
                      get_task_fn: Optional[Callable[[str], Optional[Task]]] = None,
                      add_task_to_memory_fn: Optional[Callable[[str, Task], None]] = None,
                      start_polling_fn: Optional[Callable[[str], None]] = None):
        """设置回调函数"""
        if get_task_fn is not None:
            self._get_task = get_task_fn
        if add_task_to_memory_fn is not None:
            self._add_task_to_memory = add_task_to_memory_fn
        if start_polling_fn is not None:
            self._start_polling = start_polling_fn
    
    def _init_index(self):
        """初始化索引文件"""
        try:
            index_data = self.fs.get('index.json')
            if index_data:
                index = json.loads(index_data)
                if not isinstance(index, dict) or not all(k in index for k in self._INDEX_KEYS):
                    raise ValueError("Invalid index format")
                return
        except (ValueError, json.JSONDecodeError):
            pass
        log("WARNING", "Index file missing or corrupted, recreating...")
        self.fs.put('index.json', json.dumps({
            'pending': [], 'processing': [], 'last_update': time.time()
        }))
    
    @property
    def has_storage(self) -> bool:
        """检查是否启用了存储"""
        return self.fs is not None
    
    def _get_lock(self) -> FileLock:
        """获取队列锁"""
        if not self.lock_file:
            raise RuntimeError("Storage not enabled")
        return FileLock(self.lock_file)
    
    def _save_task_internal(self, task: Task):
        """保存任务到文件系统（需持锁）"""
        task_data = task.to_dict()
        self.fs.put(f"tasks/{task.task_id}.json", json.dumps(task_data, ensure_ascii=False))
    
    def _load_task_internal(self, task_id: str) -> Optional[Task]:
        """从文件系统加载任务（需持锁）
        
        Args:
            task_id: 任务ID
            
        Returns:
            任务对象，如果文件不存在或解析失败则返回 None
        """
        try:
            data = self.fs.get(f"tasks/{task_id}.json")
            if not data:
                return None
            task = Task.from_dict(json.loads(data))
            return task
        except Exception as e:
            log("ERROR", f"[NAS] Failed to load task {task_id}: {e}")
            return None
    
    def _delete_task_internal(self, task_id: str):
        """从文件系统删除任务文件（需持锁）
        
        Args:
            task_id: 任务ID
        """
        try:
            task_file = os.path.join(self.base_dir, f"tasks/{task_id}.json")
            if os.path.exists(task_file):
                os.remove(task_file)
        except Exception as e:
            log("ERROR", f"[NAS] Failed to delete task {task_id}: {e}")
    
    def _get_index(self) -> Dict:
        """读取索引（需持锁）"""
        try:
            data = self.fs.get('index.json')
            if data:
                return json.loads(data)
        except Exception as e:
            log("ERROR", f"[NAS] Failed to read index: {e}")
        return {**{k: [] for k in self._INDEX_KEYS}, 'last_update': time.time()}
    
    def _update_index(self, index_data: Dict):
        """更新索引（需持锁）"""
        index_data['last_update'] = time.time()
        self.fs.put('index.json', json.dumps(index_data, ensure_ascii=False))
    
    def _get_index_key_for_status(self, status: TaskStatus) -> Optional[str]:
        """获取状态对应的索引键名，终态返回None"""
        return self._STATUS_TO_KEY.get(status)
    
    def _update_index_list(self, index_key: str, task_id: str, operation: str):
        """统一处理索引列表的添加/删除操作（需持锁）"""
        idx = self._get_index()
        lst = idx.get(index_key, [])
        
        if operation == 'add' and task_id not in lst:
            lst.append(task_id)
            idx[index_key] = lst
            self._update_index(idx)
        elif operation == 'remove' and task_id in lst:
            lst.remove(task_id)
            idx[index_key] = lst
            self._update_index(idx)
    
    def _move_task_in_index(self, task_id: str, old_status: TaskStatus, new_status: TaskStatus):
        """在索引中移动任务（需持锁）"""
        old_key = self._get_index_key_for_status(old_status)
        new_key = self._get_index_key_for_status(new_status)
        if old_key:
            self._update_index_list(old_key, task_id, 'remove')
        if new_key:
            self._update_index_list(new_key, task_id, 'add')
    
    def _remove_task_from_all_indexes(self, task_id: str):
        """从所有索引列表中移除任务（需持锁）"""
        idx = self._get_index()
        modified = False
        for key in self._INDEX_KEYS:
            if task_id in idx.get(key, []):
                idx[key] = [tid for tid in idx[key] if tid != task_id]
                modified = True
        if modified:
            self._update_index(idx)
    
    def _count_active_tasks(self) -> int:
        """获取活跃任务数量（需持锁）"""
        idx = self._get_index()
        return sum(len(idx.get(k, [])) for k in self._INDEX_KEYS)
    
    def restore_tasks_from_nas(self) -> List[Task]:
        """从 NAS 恢复活跃任务到内存"""
        if not self.has_storage:
            return []
        
        try:
            log("INFO", "[TaskRestore] Starting to restore tasks from NAS...")
            with self._get_lock():
                idx = self._get_index()
                pending_ids = idx.get('pending', [])
                processing_ids = idx.get('processing', [])
                task_ids = pending_ids + processing_ids
            
            if not task_ids:
                log("INFO", "[TaskRestore] No tasks to restore from NAS (index is empty)")
                return []
            
            log("INFO", f"[TaskRestore] Found {len(task_ids)} tasks in NAS (pending={len(pending_ids)}, processing={len(processing_ids)})")
            
            # 批量加载任务数据
            tasks_to_restore = []
            with self._get_lock():
                for task_id in task_ids:
                    task = self._load_task_internal(task_id)
                    if task:
                        tasks_to_restore.append((task_id, task))
                    else:
                        log("WARNING", f"Task {task_id} not found in NAS, skipping")
            
            # 在锁外执行内存添加和轮询启动
            restored_tasks = []
            for task_id, task in tasks_to_restore:
                try:
                    if self._add_task_to_memory:
                        self._add_task_to_memory(task_id, task)
                    if self._start_polling:
                        self._start_polling(task_id)
                    restored_tasks.append(task)
                    log("INFO", f"[TaskRestore] Restored task {task_id} (status={task.status.value}, prompt_id={task.prompt.get('prompt_id', 'N/A') if isinstance(task.prompt, dict) else 'N/A'})")
                except Exception as e:
                    log("ERROR", f"[TaskRestore] Failed to restore task {task_id} to memory: {e}")
            
            failed_count = len(task_ids) - len(restored_tasks)
            log("INFO", f"[TaskRestore] Task restoration completed (restored={len(restored_tasks)}, failed={failed_count}, total={len(task_ids)})")
            return restored_tasks
            
        except Exception as e:
            log("ERROR", f"Failed to restore tasks from NAS: {e}")
            traceback.print_exc()
            return []
    
    def save_task(self, task: Task):
        """保存任务到NAS"""
        if not self.has_storage:
            return
        try:
            with self._get_lock():
                self._save_task_internal(task)
                index_key = self._get_index_key_for_status(task.status)
                if index_key:
                    self._update_index_list(index_key, task.task_id, 'add')
        except Exception as e:
            log("ERROR", f"[Queue->NAS] Failed to persist task {task.task_id}: {e}")
    
    def sync_task_status(self, task_id: str, old_status: TaskStatus, new_status: TaskStatus):
        """同步任务状态更新到NAS"""
        if not self.has_storage:
            return
        try:
            with self._get_lock():
                if self._get_task:
                    task = self._get_task(task_id)
                    if task:
                        self._save_task_internal(task)
                if old_status.is_active() or new_status.is_active():
                    self._move_task_in_index(task_id, old_status, new_status)
        except Exception as e:
            log("ERROR", f"[Queue->NAS] Failed to sync status for {task_id}: {e}")
    
    def delete_task(self, task_id: str):
        """从NAS删除任务并更新索引"""
        if not self.has_storage:
            return
        try:
            with self._get_lock():
                self._delete_task_internal(task_id)
                self._remove_task_from_all_indexes(task_id)
        except Exception as e:
            log("ERROR", f"[Queue->NAS] Failed to delete task {task_id}: {e}")
    
    def get_active_task_count(self) -> int:
        """从NAS索引获取活跃任务数量"""
        if not self.has_storage:
            return 0
        try:
            with self._get_lock():
                return self._count_active_tasks()
        except Exception as e:
            log("ERROR", f"[Queue->NAS] Failed to get active task count: {e}")
            return 0

