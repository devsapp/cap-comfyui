"""
History 管理模块
负责管理任务历史记录的创建、更新和查询
"""
import json
import os
import sqlite3
import time
import threading
import traceback
from typing import Dict, Any, Optional, List
from collections import defaultdict

import constants
from utils.logger import log
from services.gateway.task.utils.prompt_utils import parse_prompt_body

# 持久化数据库路径（NAS 上，实例重建后仍可读取）
_HISTORY_DB = os.path.join(constants.MNT_DIR, "output", ".history.db")
# 启动时加载到内存的最大条目数（DB 本身不限制）
_MAX_LOAD_ITEMS = 2000
# 写盘去抖间隔（秒）
_FLUSH_DEBOUNCE_SECONDS = 3


class HistoryManager:
    """
    历史记录管理类
    负责管理任务执行历史的存储和查询

    注意：此类是线程安全的，所有公共方法都使用独立的锁保护
    """

    def __init__(self):
        """初始化历史记录存储"""
        # 历史记录主存储: {prompt_id: {prompt, outputs, status, meta, user_id}}
        self.history: Dict[str, dict] = {}

        # 按用户分组的历史记录: {user_id: {prompt_id: history_item}}
        self._history_by_user: Dict[str, Dict[str, dict]] = defaultdict(dict)

        # 独立的锁，保护 history 和 _history_by_user 的并发访问
        self._lock = threading.Lock()

        # 持久化相关
        self._flush_timer: Optional[threading.Timer] = None
        self._flush_lock = threading.Lock()
        # 追踪需要写入/删除的记录
        self._dirty_prompt_ids: set = set()
        self._deleted_prompt_ids: set = set()

        # 从 NAS 加载历史数据
        self._load_from_disk()
    
    def get_history(self, user_id: str, max_items=None, offset: int = -1) -> Dict[Any, Any]:
        """
        获取用户的历史记录
        
        Args:
            user_id: 用户ID
            max_items: 最大返回数量
            offset: 偏移量，-1 表示从末尾开始
            
        Returns:
            dict: 历史记录字典，格式为 {prompt_id: {prompt, outputs, status, meta, user_id}}
                  只返回已完成（status.completed == True）的历史记录
        """
        with self._lock:
            user_history = self._history_by_user.get(user_id, {})
            
            # 过滤出已完成的历史记录（不复制数据，直接引用）
            completed_history = {}
            for prompt_id, history_item in user_history.items():
                status = history_item.get("status", {})
                if status.get("completed", False):
                    # 直接使用原始 history_item，不复制
                    # 因为已经通过 user_id 过滤，返回的都是当前用户自己的数据
                    completed_history[prompt_id] = history_item
            
            # 应用 offset 和 max_items 限制
            out = {}
            i = 0
            if offset < 0 and max_items is not None:
                offset = len(completed_history) - max_items
            for k in completed_history:
                if i >= offset:
                    out[k] = completed_history[k]
                    if max_items is not None and len(out) >= max_items:
                        break
                i += 1
            return out
    
    def add_history_item(self, prompt_id: str, history_item: dict) -> bool:
        """
        原子地添加 history item 到两个字典
        
        Args:
            prompt_id: prompt ID
            history_item: history 数据项（必须包含 user_id）
            
        Returns:
            bool: 是否成功添加（False表示已存在或缺少user_id）
        """
        with self._lock:
            try:
                user_id = history_item.get("user_id")
                if not user_id:
                    log("ERROR", f"[HistoryManager] Cannot add history item for {prompt_id}: user_id is missing")
                    return False
                
                # 检查是否已存在
                if prompt_id in self.history:
                    log("DEBUG", f"[HistoryManager] history_item for prompt_id {prompt_id} already exists")
                    return False
                
                # 原子性添加到两个字典
                try:
                    self.history[prompt_id] = history_item
                    self._history_by_user[user_id][prompt_id] = history_item
                    log("DEBUG", f"[HistoryManager] Added history_item for prompt_id {prompt_id}, user {user_id}")
                    return True
                except Exception as e:
                    # 回滚：如果出错，确保两个字典保持一致
                    self.history.pop(prompt_id, None)
                    self._history_by_user[user_id].pop(prompt_id, None)
                    log("ERROR", f"[HistoryManager] Failed to add history item for {prompt_id}, rolled back: {e}")
                    return False
                    
            except Exception as e:
                log("ERROR", f"[HistoryManager] Error in add_history_item for {prompt_id}: {e}\n{traceback.format_exc()}")
                return False
    
    def get_history_item(self, prompt_id: str) -> Optional[dict]:
        """
        获取指定 prompt_id 的 history_item
        
        Args:
            prompt_id: prompt ID
            
        Returns:
            dict: history_item，如果不存在则返回 None
        """
        with self._lock:
            return self.history.get(prompt_id)
    
    def remove_history_item(self, prompt_id: str) -> bool:
        """
        原子地从两个字典移除 history item

        Args:
            prompt_id: prompt ID

        Returns:
            bool: 是否成功移除
        """
        with self._lock:
            try:
                history_item = self.history.get(prompt_id)
                if not history_item:
                    return False

                user_id = history_item.get("user_id")

                # 原子性删除
                self.history.pop(prompt_id, None)
                if user_id:
                    self._history_by_user[user_id].pop(prompt_id, None)

                log("DEBUG", f"[HistoryManager] Removed history_item for prompt_id {prompt_id}")
                self._dirty_prompt_ids.discard(prompt_id)
                self._deleted_prompt_ids.add(prompt_id)
                self._schedule_flush()
                return True

            except Exception as e:
                log("ERROR", f"[HistoryManager] Error in remove_history_item for {prompt_id}: {e}\n{traceback.format_exc()}")
                return False

    def remove_if_owned(self, prompt_id: str, user_id: str) -> bool:
        """
        原子地校验归属并删除 history item，消除先 get 再 remove 的 TOCTOU 竞态。

        Returns:
            bool: item 存在且属于 user_id 并成功删除时返回 True，否则 False。
        """
        with self._lock:
            try:
                history_item = self.history.get(prompt_id)
                if not history_item or history_item.get("user_id") != user_id:
                    return False
                self.history.pop(prompt_id, None)
                self._history_by_user[user_id].pop(prompt_id, None)
                log("DEBUG", f"[HistoryManager] Removed history_item for prompt_id {prompt_id}")
                self._dirty_prompt_ids.discard(prompt_id)
                self._deleted_prompt_ids.add(prompt_id)
                self._schedule_flush()
                return True
            except Exception as e:
                log("ERROR", f"[HistoryManager] Error in remove_if_owned for {prompt_id}: {e}\n{traceback.format_exc()}")
                return False

    def wipe_history_for_user(self, user_id: str) -> int:
        """
        清空指定用户的全部历史记录（与 ComfyUI wipe_history 语义对齐，多租户下按用户清空）

        Args:
            user_id: 用户ID

        Returns:
            int: 被移除的条目数
        """
        with self._lock:
            try:
                user_history = self._history_by_user.get(user_id, {})
                count = len(user_history)
                for prompt_id in list(user_history.keys()):
                    self.history.pop(prompt_id, None)
                    self._dirty_prompt_ids.discard(prompt_id)
                    self._deleted_prompt_ids.add(prompt_id)
                self._history_by_user[user_id] = {}
                if count > 0:
                    log("DEBUG", f"[HistoryManager] Wiped {count} history items for user {user_id}")
                    self._schedule_flush()
                return count
            except Exception as e:
                log("ERROR", f"[HistoryManager] Error in wipe_history_for_user for {user_id}: {e}\n{traceback.format_exc()}")
                return 0
    
    def init_history_item(self, prompt_id: str, prompt_body: dict, client_id: str, 
                         user_id: str, message: dict) -> bool:
        """
        初始化 history_item（在 execution_start 时调用）
        
        Args:
            prompt_id: prompt ID
            prompt_body: 任务的 prompt 数据
            client_id: 客户端ID
            user_id: 用户ID
            message: execution_start 消息
            
        Returns:
            bool: 是否成功初始化
        """
        with self._lock:
            try:
                # 检查是否已存在
                if prompt_id in self.history:
                    log("DEBUG", f"[HistoryManager] history_item for prompt_id {prompt_id} already exists")
                    return False
                
                # 立即设置占位符，防止其他线程重复初始化
                self.history[prompt_id] = {"_initializing": True, "user_id": user_id}
                
                try:
                    # 构造 history_item
                    history_item = self._build_history_item(
                        prompt_id=prompt_id,
                        prompt_body=prompt_body,
                        client_id=client_id,
                        user_id=user_id,
                        message=message
                    )
                    
                    # 最终检查：确保占位符还在（没有被其他操作删除）
                    current = self.history.get(prompt_id)
                    if current and current.get("_initializing"):
                        # 替换占位符为完整数据
                        self.history[prompt_id] = history_item
                        self._history_by_user[user_id][prompt_id] = history_item
                        log("DEBUG", f"[HistoryManager] Initialized history_item for prompt_id {prompt_id}")
                        return True
                    else:
                        log("WARNING", f"[HistoryManager] history_item for prompt_id {prompt_id} was modified during initialization")
                        return False
                        
                except Exception as e:
                    # 清理占位符
                    current = self.history.get(prompt_id)
                    if current and current.get("_initializing"):
                        self.history.pop(prompt_id, None)
                    log("ERROR", f"[HistoryManager] Failed to build history_item for {prompt_id}: {e}\n{traceback.format_exc()}")
                    return False
                    
            except Exception as e:
                log("ERROR", f"[HistoryManager] Error initializing history_item for prompt_id {prompt_id}: {e}\n{traceback.format_exc()}")
                return False
    
    def _build_history_item(self, prompt_id: str, prompt_body: dict, client_id: str, 
                           user_id: str, message: dict) -> dict:
        """
        构造 history_item（辅助方法）
        
        Args:
            prompt_id: prompt ID
            prompt_body: 任务的 prompt 数据
            client_id: 客户端ID
            user_id: 用户ID
            message: execution_start 消息
            
        Returns:
            dict: 构造好的 history_item
        """
        # 解析 prompt_body（与原生 ComfyUI 一致：未传 outputs_to_execute 时由服务端推断，见 execution.py validate_prompt）
        prompt_dict, outputs_to_execute, extra_data = parse_prompt_body(prompt_body, client_id)
        
        # 使用时间戳作为序号（确保唯一性）
        sequence_number = int(time.time() * 1000000) % 1000000000  # 微秒时间戳
        
        # 提取时间戳
        msg_data = message.get("data", {})
        timestamp = msg_data.get("timestamp")
        if timestamp is None:
            timestamp = int(time.time() * 1000)
        else:
            # 标准化时间戳为毫秒
            if timestamp < 10000000000:
                timestamp = int(timestamp * 1000)
            else:
                timestamp = int(timestamp)
        extra_data["create_time"] = timestamp
        
        # 构造 prompt 数组，格式：[number, prompt_id, prompt_dict, extra_data, outputs_to_execute]
        return {
            "meta": {},
            "outputs": {},
            "prompt": [
                sequence_number,
                prompt_id,
                prompt_dict,
                extra_data,
                outputs_to_execute
            ],
            "status": {
                "status_str": "running",
                "completed": False,
                "messages": [
                    ["execution_start", {"prompt_id": prompt_id, "timestamp": timestamp}]
                ]
            },
            "user_id": user_id
        }
    
    def update_history_status(self, message: dict, status_str: str) -> bool:
        """
        更新 history_item 的 status
        
        Args:
            message: 消息数据（execution_success、execution_error、execution_cached）
            status_str: 状态字符串（"success"、"error"、"running"）
            
        Returns:
            bool: 是否成功更新
        """
        with self._lock:
            try:
                data = message.get("data", {})
                prompt_id = data.get("prompt_id")
                if not prompt_id:
                    return False
                
                history_item = self.history.get(prompt_id)
                if not history_item:
                    log("WARNING", f"[HistoryManager] Cannot update history status: history_item not found for prompt_id {prompt_id}")
                    return False
                
                if "status" not in history_item:
                    history_item["status"] = {
                        "status_str": status_str,
                        "completed": False,
                        "messages": []
                    }
                
                status = history_item["status"]
                
                # 提取时间戳
                timestamp = data.get("timestamp")
                if timestamp is None:
                    timestamp = int(time.time() * 1000)
                else:
                    # 标准化时间戳为毫秒
                    if timestamp < 10000000000:
                        timestamp = int(timestamp * 1000)
                    else:
                        timestamp = int(timestamp)
                
                # 更新状态
                status["status_str"] = status_str
                
                # 根据状态类型添加消息
                completed_now = False
                if status_str == "success":
                    status["completed"] = True
                    completed_now = True
                    # 添加 execution_success 消息（如果还没有）
                    if not any(msg[0] == "execution_success" for msg in status.get("messages", [])):
                        status.setdefault("messages", []).append(
                            ["execution_success", {"prompt_id": prompt_id, "timestamp": timestamp}]
                        )
                elif status_str == "error":
                    status["completed"] = True
                    completed_now = True
                    # 添加 execution_error 消息（如果还没有）
                    if not any(msg[0] == "execution_error" for msg in status.get("messages", [])):
                        error_info = {
                            "prompt_id": prompt_id,
                            "node_id": data.get("node_id") or data.get("node", "unknown"),
                            "exception_message": data.get("exception_message", "Unknown error"),
                            "timestamp": timestamp
                        }
                        status.setdefault("messages", []).append(["execution_error", error_info])
                elif status_str == "running":
                    # execution_cached 或其他运行中状态，不改变 completed 标志
                    # 可以添加 execution_cached 消息
                    if message.get("type") == "execution_cached":
                        if not any(msg[0] == "execution_cached" for msg in status.get("messages", [])):
                            status.setdefault("messages", []).append(
                                ["execution_cached", {"prompt_id": prompt_id, "timestamp": timestamp}]
                            )

                if completed_now:
                    self._dirty_prompt_ids.add(prompt_id)
                    self._schedule_flush()
                return True

            except Exception as e:
                log("ERROR", f"[HistoryManager] Error updating history status: {e}\n{traceback.format_exc()}")
                return False
    
    def update_history_outputs(self, message: dict) -> bool:
        """
        更新 history_item 的 outputs 和 meta（处理 executed 消息）
        
        Args:
            message: executed 消息数据
            
        Returns:
            bool: 是否成功更新
        """
        with self._lock:
            try:
                data = message.get("data", {})
                prompt_id = data.get("prompt_id")
                node_id = data.get("node")
                
                if not prompt_id or not node_id:
                    log("WARNING", f"[HistoryManager] executed message missing prompt_id or node_id")
                    return False
                
                history_item = self.history.get(prompt_id)
                if not history_item:
                    log("WARNING", f"[HistoryManager] History item not found for prompt_id {prompt_id}")
                    return False
                
                # 检查是否是初始化占位符
                if history_item.get("_initializing"):
                    log("WARNING", f"[HistoryManager] History item for {prompt_id} is still initializing, skipping executed message")
                    return False
                
                # 处理节点输出：构造 meta
                if "meta" not in history_item:
                    history_item["meta"] = {}
                
                history_item["meta"][node_id] = {
                    "node_id": node_id,
                    "display_node": data.get("display_node", node_id),
                    "parent_node": None,
                    "real_node_id": node_id
                }
                
                # 构造 outputs，从 output.images 中获取图片信息
                output_data = data.get("output") or {}
                images = output_data.get("images", [])
                
                if images:
                    if "outputs" not in history_item:
                        history_item["outputs"] = {}
                    if node_id not in history_item["outputs"]:
                        history_item["outputs"][node_id] = {}
                    if "images" not in history_item["outputs"][node_id]:
                        history_item["outputs"][node_id]["images"] = []
                    
                    for img in images:
                        image_item = {
                            "filename": img.get("filename", ""),
                            "type": img.get("type", "output"),
                            "subfolder": img.get("subfolder", "")
                        }
                        history_item["outputs"][node_id]["images"].append(image_item)
                
                return True
                
            except Exception as e:
                log("ERROR", f"[HistoryManager] Error updating history outputs: {e}\n{traceback.format_exc()}")
                return False
    
    def late_init_history_item(self, task_id: str, prompt_id: str, prompt_body: dict,
                               client_id: str, user_id: str) -> bool:
        """
        延迟初始化历史项（当 executed 消息到达但 history_item 尚未创建时）

        Args:
            task_id: 任务ID
            prompt_id: prompt ID
            prompt_body: 任务的 prompt 数据
            client_id: 客户端ID
            user_id: 用户ID

        Returns:
            bool: 是否成功初始化
        """
        with self._lock:
            try:
                if prompt_id in self.history:
                    return False

                prompt_dict, outputs_to_execute, extra_data = parse_prompt_body(prompt_body, client_id)
                extra_data["create_time"] = int(time.time() * 1000)

                log("INFO", f"[HistoryManager] Late-initializing history_item for prompt_id {prompt_id}")
                history_item = {
                    "meta": {},
                    "outputs": {},
                    "prompt": [0, prompt_id, prompt_dict, extra_data, outputs_to_execute],
                    "status": {
                        "status_str": "running",
                        "completed": False,
                        "messages": []
                    },
                    "user_id": user_id
                }
                self.history[prompt_id] = history_item
                self._history_by_user[user_id][prompt_id] = history_item
                return True

            except Exception as e:
                log("ERROR", f"[HistoryManager] Error in late_init_history_item for {prompt_id}: {e}\n{traceback.format_exc()}")
                return False

    # ==================== 持久化（SQLite）====================

    def _init_db(self):
        """初始化 SQLite 数据库连接和表结构"""
        try:
            os.makedirs(os.path.dirname(_HISTORY_DB), exist_ok=True)
            conn = sqlite3.connect(_HISTORY_DB, timeout=5)
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS history (
                    prompt_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    outputs TEXT,
                    meta TEXT,
                    status TEXT,
                    create_time INTEGER DEFAULT 0
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON history(user_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_create_time ON history(create_time)")
            conn.commit()
            return conn
        except Exception as e:
            log("WARNING", f"[HistoryManager] Failed to init history DB: {e}")
            return None

    def _load_from_disk(self):
        """启动时从 SQLite 加载已完成的历史记录"""
        try:
            conn = self._init_db()
            if not conn:
                return
            cursor = conn.execute(
                "SELECT prompt_id, user_id, outputs, meta, status, create_time "
                "FROM history ORDER BY create_time DESC LIMIT ?",
                (_MAX_LOAD_ITEMS,)
            )
            count = 0
            for row in cursor:
                prompt_id, user_id, outputs_json, meta_json, status_json, create_time = row
                item = {
                    "outputs": json.loads(outputs_json) if outputs_json else {},
                    "meta": json.loads(meta_json) if meta_json else {},
                    "status": json.loads(status_json) if status_json else {},
                    "user_id": user_id,
                    "create_time": create_time or 0,
                }
                self.history[prompt_id] = item
                self._history_by_user[user_id][prompt_id] = item
                count += 1
            conn.close()
            if count > 0:
                log("INFO", f"[HistoryManager] Loaded {count} history items from DB")
        except Exception as e:
            log("WARNING", f"[HistoryManager] Failed to load history from DB: {e}")

    def _schedule_flush(self):
        """去抖写盘：延迟 _FLUSH_DEBOUNCE_SECONDS 后执行，合并高频写入"""
        with self._flush_lock:
            if self._flush_timer is not None:
                self._flush_timer.cancel()
            self._flush_timer = threading.Timer(_FLUSH_DEBOUNCE_SECONDS, self._flush_to_disk)
            self._flush_timer.daemon = True
            self._flush_timer.start()

    @staticmethod
    def _get_create_time(item: dict) -> int:
        """从 history item 中提取 create_time"""
        prompt = item.get("prompt", [])
        if len(prompt) > 3 and isinstance(prompt[3], dict):
            return prompt[3].get("create_time", 0)
        return item.get("create_time", 0)

    def _flush_to_disk(self):
        """将脏记录增量写入 SQLite，删除已移除的记录"""
        try:
            with self._lock:
                dirty_ids = self._dirty_prompt_ids.copy()
                deleted_ids = self._deleted_prompt_ids.copy()
                self._dirty_prompt_ids.clear()
                self._deleted_prompt_ids.clear()

                # 收集需要写入的记录
                rows = []
                for pid in dirty_ids:
                    item = self.history.get(pid)
                    if not item or not item.get("status", {}).get("completed", False):
                        continue
                    if item.get("_initializing"):
                        continue
                    create_time = self._get_create_time(item)
                    rows.append((
                        pid,
                        item.get("user_id", ""),
                        json.dumps(item.get("outputs", {}), ensure_ascii=False, separators=(",", ":")),
                        json.dumps(item.get("meta", {}), ensure_ascii=False, separators=(",", ":")),
                        json.dumps(item.get("status", {}), ensure_ascii=False, separators=(",", ":")),
                        create_time,
                    ))

            if not rows and not deleted_ids:
                return

            conn = sqlite3.connect(_HISTORY_DB, timeout=5)
            conn.execute("PRAGMA journal_mode=DELETE")

            if rows:
                conn.executemany(
                    "INSERT OR REPLACE INTO history (prompt_id, user_id, outputs, meta, status, create_time) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    rows
                )

            if deleted_ids:
                placeholders = ",".join("?" * len(deleted_ids))
                conn.execute(f"DELETE FROM history WHERE prompt_id IN ({placeholders})", list(deleted_ids))

            conn.commit()
            conn.close()
            log("DEBUG", f"[HistoryManager] DB flush: {len(rows)} upserted, {len(deleted_ids)} deleted")
        except Exception as e:
            log("WARNING", f"[HistoryManager] Failed to flush history to DB: {e}")
