import json
import threading
from datetime import datetime
from typing import Set, Dict, Optional, Any
from queue import Queue, Empty

from utils.logger import log
from services.gateway.queue.task_models import TaskStatus


class WebSocketManager:
    def __init__(self):
        self.active_connections = set()
        self._lock = threading.Lock()
        self._connection_times = {}
        
        # 任务状态推送功能
        self._task_subscriptions: Dict[str, Set[Any]] = {}  # task_id -> set of websockets
        self._client_subscriptions: Dict[Any, Set[str]] = {}  # websocket -> set of task_ids
        self._client_id_mapping: Dict[str, Set[Any]] = {}  # client_id -> set of websockets
        self._ws_client_id_mapping: Dict[Any, str] = {}  # websocket -> client_id
        
        # 使用消息队列序列化所有发送操作
        self._message_queue = Queue()  # 线程安全的消息队列
        self._send_thread: Optional[threading.Thread] = None
        
        # 启动单独的发送线程
        self._start_send_thread()

    def _start_send_thread(self):
        """启动消息发送线程"""
        # 如果线程已经存在且正在运行，不重复启动
        if self._send_thread is not None and self._send_thread.is_alive():
            log("DEBUG", "[WebSocketManager] Send thread already running, skipping start")
            return
        
        try:
            self._send_thread = threading.Thread(
                target=self._send_loop,
                name="ws-send-loop",
                daemon=True
            )
            self._send_thread.start()
            log("INFO", "[WebSocketManager] Send thread started successfully")
        except Exception as e:
            log("ERROR", f"[WebSocketManager] Failed to start send thread: {e}")
            import traceback
            log("ERROR", f"[WebSocketManager] Thread start error traceback: {traceback.format_exc()}")
            self._send_thread = None
    
    def _send_loop(self):
        """消息发送循环：从队列中取消息并发送"""
        while True:
            try:
                # 从队列获取消息，带超时
                try:
                    message_data = self._message_queue.get(timeout=0.1)
                except Empty:
                    continue
                
                # 解包消息：(ws_or_set, message_str)
                ws_or_set, message_str = message_data
                
                # 统一发送
                self._do_send(ws_or_set, message_str)
                
            except Exception as e:
                log("ERROR", f"[WebSocketManager] Error in send loop: {e}")
                import traceback
                log("ERROR", f"[WebSocketManager] Send loop error traceback: {traceback.format_exc()}")
    
    def _do_send(self, ws_or_set, message_str: str):
        """
        发送消息给单个或多个 WebSocket
        
        Args:
            ws_or_set: 单个 WebSocket 连接或连接集合
            message_str: 已序列化的消息字符串
        """
        # 统一处理：单个连接也转为集合，简化逻辑
        if isinstance(ws_or_set, set):
            ws_set = ws_or_set
        else:
            ws_set = {ws_or_set}
        
        # 检查连接有效性（快速检查，避免发送给已移除的连接）
        with self._lock:
            valid_connections = {ws for ws in ws_set if ws in self.active_connections}
        
        if not valid_connections:
            return
        
        disconnected = set()
        
        for ws in valid_connections:
            try:
                ws.send(message_str)
            except Exception as e:
                disconnected.add(ws)
                error_type = type(e).__name__
                log("ERROR", f"[WebSocketManager] WebSocket send failed ({error_type}): {str(e)}")
        
        # 清理断开的连接
        for ws in disconnected:
            try:
                self.remove_connection(ws)
            except Exception as cleanup_error:
                log("ERROR", f"[WebSocketManager] Error removing connection: {cleanup_error}")
    
    def _send_sync(self, ws_or_set, message):
        """线程安全地将消息放入队列"""
        if self._send_thread is None or not self._send_thread.is_alive():
            log("WARNING", "[WebSocketManager] Send thread not available, skipping message")
            return
        
        try:
            # 序列化消息
            if isinstance(message, (dict, list)):
                message_str = json.dumps(message, ensure_ascii=False)
            elif isinstance(message, bytes):
                message_str = message.decode("utf-8", errors="ignore")
            else:
                message_str = str(message)
            
            # 放入队列，由发送线程处理
            self._message_queue.put((ws_or_set, message_str))
        except Exception as e:
            log("ERROR", f"[WebSocketManager] Error queuing message: {e}")
            import traceback
            log("ERROR", f"[WebSocketManager] Queue message error traceback: {traceback.format_exc()}")
    
    
    def _set_tcp_nodelay(self, ws):
        """设置TCP_NODELAY禁用Nagle算法，确保消息立即发送而不是等待缓冲"""
        try:
            import socket
            # 尝试多种方式获取底层socket
            sock = (getattr(ws, 'environ', {}).get('werkzeug.socket') or
                   getattr(ws, 'sock', None) or
                   getattr(ws, '_sock', None) or
                   getattr(getattr(ws, 'connected', None), 'sock', None))
            
            if sock and hasattr(sock, 'setsockopt'):
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            # TCP_NODELAY 设置失败不影响功能，静默处理
            pass

    def add_connection(self, ws):
        with self._lock:
            self.active_connections.add(ws)
            self._connection_times[id(ws)] = datetime.now()
            self._client_subscriptions[ws] = set()
            log("INFO", f"[WebSocketManager] Connection added: {id(ws)}")
        
        # 在锁外设置 TCP_NODELAY，避免在锁内执行网络操作
        self._set_tcp_nodelay(ws)
        
        if self._send_thread is None or not self._send_thread.is_alive():
            log("WARNING", "[WebSocketManager] Send thread not running, restarting...")
            self._start_send_thread()
        

    def remove_connection(self, ws):
        with self._lock:
            self.active_connections.discard(ws)
            conn_id = id(ws)
            start_time = self._connection_times.pop(conn_id, None)
            
            # 清理该连接的所有任务订阅
            subscribed_tasks = self._client_subscriptions.get(ws, set())
            for task_id in subscribed_tasks:
                if task_id in self._task_subscriptions:
                    self._task_subscriptions[task_id].discard(ws)
                    # 如果没有其他订阅者，删除任务记录
                    if not self._task_subscriptions[task_id]:
                        del self._task_subscriptions[task_id]
            
            # 清理ComfyUI客户端ID映射
            client_id = self._ws_client_id_mapping.get(ws)
            if client_id:
                if client_id in self._client_id_mapping:
                    self._client_id_mapping[client_id].discard(ws)
                    if not self._client_id_mapping[client_id]:
                        del self._client_id_mapping[client_id]
                self._ws_client_id_mapping.pop(ws, None)
            
            # 清理客户端订阅记录
            self._client_subscriptions.pop(ws, None)
            
            duration_str = ""
            if start_time:
                duration = (datetime.now() - start_time).total_seconds()
                duration_str = f" (duration: {duration:.1f}s)"
            log("INFO", f"[WebSocketManager] Connection removed: {conn_id}{duration_str}")

    def subscribe_task_status(self, ws, task_id: str) -> bool:
        """
        订阅任务状态推送
        
        Args:
            ws: WebSocket连接
            task_id: 任务ID
            
        Returns:
            bool: 订阅是否成功
        """
        try:
            with self._lock:
                # 检查连接是否有效
                if ws not in self.active_connections:
                    return False
                
                # 添加任务订阅
                if task_id not in self._task_subscriptions:
                    self._task_subscriptions[task_id] = set()
                self._task_subscriptions[task_id].add(ws)
                
                # 添加客户端订阅记录
                if ws not in self._client_subscriptions:
                    self._client_subscriptions[ws] = set()
                self._client_subscriptions[ws].add(task_id)
                
                return True
                
        except Exception as e:
            log("ERROR", f"[WebSocketManager] Failed to subscribe to task {task_id}: {e}")
            return False
    
    def associate_client_id_with_connection(self, ws, client_id: str):
        """
        将ComfyUI客户端ID与连接关联
        
        Args:
            ws: WebSocket连接
            client_id: ComfyUI客户端ID
        """
        with self._lock:
            # 如果是重连，移除旧连接
            if client_id in self._client_id_mapping:
                old_connections = self._client_id_mapping[client_id].copy()
                for old_ws in old_connections:
                    if old_ws != ws:
                        log("INFO", f"[WebSocketManager] Removing old connection for client_id {client_id} (reconnect)")
                        # 清理映射和从活跃连接中移除
                        self._client_id_mapping[client_id].discard(old_ws)
                        self._ws_client_id_mapping.pop(old_ws, None)
                        self.active_connections.discard(old_ws)
                        # 清理旧连接的订阅记录
                        self._client_subscriptions.pop(old_ws, None)
            
            if client_id not in self._client_id_mapping:
                self._client_id_mapping[client_id] = set()
            self._client_id_mapping[client_id].add(ws)
            self._ws_client_id_mapping[ws] = client_id
    
    def associate_task_with_client_id(self, task_id: str, client_id: str) -> int:
        """
        将任务与指定的ComfyUI客户端关联，并自动订阅该任务的状态
        
        Args:
            task_id: 任务ID
            client_id: ComfyUI客户端ID
            
        Returns:
            int: 成功关联的连接数
        """
        with self._lock:
            connections = self._client_id_mapping.get(client_id, set()).copy()
        
        if not connections:
            return 0
        
        associated_count = 0
        for ws in connections:
            if self.subscribe_task_status(ws, task_id):
                associated_count += 1
        
        return associated_count
    
    def resubscribe_client_tasks(self, ws, client_id: str):
        """
        当客户端重连时，重新订阅该客户端的所有进行中的任务
        
        Args:
            ws: 新的WebSocket连接
            client_id: 客户端ID
        """
        try:
            from services.gateway import get_task_queue
            
            task_queue = get_task_queue()
            all_tasks = task_queue.get_all_tasks()
            
            # 过滤出该客户端的进行中的任务
            active_tasks = [
                task for task in all_tasks
                if task.client_id == client_id and 
                   task.status in [TaskStatus.PENDING, TaskStatus.PROCESSING]
            ]
            
            if not active_tasks:
                return
            
            # 为每个活跃任务重新订阅
            resubscribed_count = 0
            for task in active_tasks:
                if self.subscribe_task_status(ws, task.task_id):
                    resubscribed_count += 1
            
            if resubscribed_count > 0:
                log("INFO", f"[WebSocketManager] Resubscribed {resubscribed_count} active tasks for client_id {client_id}")
            
        except Exception as e:
            log("ERROR", f"[WebSocketManager] Failed to resubscribe tasks for client_id {client_id}: {e}")
            import traceback
            log("ERROR", f"Traceback: {traceback.format_exc()}")
    
    def broadcast_comfyui_message(self, task_id: str, comfyui_message: dict) -> int:
        """
        广播ComfyUI原生格式的消息
        
        Args:
            task_id: 任务ID（特殊值"queue_status"表示广播给所有连接，否则广播给任务订阅者）
            comfyui_message: ComfyUI原生格式的消息
            
        Returns:
            int: 成功发送的连接数
        """
        # 特殊处理队列状态广播：广播给所有连接
        if task_id == "queue_status":
            with self._lock:
                all_connections = self.active_connections.copy()
            
            if not all_connections:
                return 0
            
            self._send_sync(all_connections, comfyui_message)
            return len(all_connections)
        
        # 任务状态广播：只广播给任务订阅者
        with self._lock:
            subscribers = self._task_subscriptions.get(task_id, set()).copy()
        
        if not subscribers:
            return 0
        
        # 使用消息队列发送，由单独的发送线程处理
        self._send_sync(subscribers, comfyui_message)
        
        return len(subscribers)
    
    def close_all_connections(self):
        """关闭所有WebSocket连接（不停止发送线程，因为重启后需要继续使用）"""
        try:
            # 先复制连接列表，避免在锁内执行网络操作
            with self._lock:
                connections_to_close = self.active_connections.copy()
                # 清理连接和订阅记录
                self.active_connections.clear()
                self._task_subscriptions.clear()
                self._client_subscriptions.clear()
                self._client_id_mapping.clear()
                self._ws_client_id_mapping.clear()
            
            for ws in connections_to_close:
                try:
                    # 直接发送关闭消息，不经过队列
                    ws.send('Server shutting down')
                    ws.close()
                except Exception as e:
                    # 连接可能已经关闭，忽略错误
                    pass
                
            log("INFO", f"[WebSocketManager] Closed {len(connections_to_close)} WebSocket connection(s)")
        except Exception as e:
            log("ERROR", f"[WebSocketManager] Error closing connections: {e}")
            import traceback
            log("ERROR", f"[WebSocketManager] Cleanup error traceback: {traceback.format_exc()}")


ws_manager = WebSocketManager()
