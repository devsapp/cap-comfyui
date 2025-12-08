import json
import threading
from datetime import datetime
from typing import Set, Dict, Optional, Any, Union
from queue import Queue, Empty

from utils.logger import log


class WebSocketManager:
    def __init__(self):
        self.active_connections = set()
        self._lock = threading.Lock()
        self._connection_times = {}
        
        # 客户端ID映射
        self._client_id_mapping: Dict[str, Any] = {}  # client_id -> websocket
        
        # 使用消息队列序列化所有发送操作
        self._message_queue = Queue()  # 线程安全的消息队列
        self._send_thread: Optional[threading.Thread] = None
        
        # 启动单独的发送线程
        self._start_send_thread()

    def get_connection_info(self, ws):
        """
        获取WebSocket连接的详细信息
        
        Args:
            ws: WebSocket连接
            
        Returns:
            dict: 连接信息，包含 connection_id, address, port
        """
        try:
            environ = ws.environ
            return {
                'connection_id': id(ws),
                'address': environ.get('REMOTE_ADDR'),
                'port': environ.get('REMOTE_PORT')
            }
        except Exception:
            # 如果无法获取环境信息，返回基本信息
            return {
                'connection_id': id(ws),
                'address': None,
                'port': None
            }
    
    def add_connection(self, ws, client_id: Optional[str] = None):
        """
        添加WebSocket连接到管理器
        
        Args:
            ws: WebSocket连接
            client_id: 可选的客户端ID，如果提供则建立映射并处理重连
        """
        with self._lock:
            # 如果有 client_id，先处理重连逻辑（移除旧连接）
            if client_id:
                if client_id in self._client_id_mapping:
                    old_ws = self._client_id_mapping[client_id]
                    if old_ws != ws:
                        log("INFO", f"[WebSocketManager] Removing old connection for client_id {client_id} (reconnect)")
                        # 从活跃连接中移除旧连接
                        self.active_connections.discard(old_ws)
            
            # 添加新连接
            self.active_connections.add(ws)
            self._connection_times[id(ws)] = datetime.now()
            
            # 如果有 client_id，建立映射（一个客户端只有一个连接）
            if client_id:
                self._client_id_mapping[client_id] = ws
            
            conn_info = self.get_connection_info(ws)
            log("DEBUG", f"[WebSocketManager] Connection added: {json.dumps(conn_info, indent=2)}" + (f" (client_id: {client_id})" if client_id else ""))
        
        if self._send_thread is None or not self._send_thread.is_alive():
            log("WARNING", "[WebSocketManager] Send thread not running, restarting...")
            self._start_send_thread()

    def remove_connection(self, ws, client_id: Optional[str] = None):
        """
        移除WebSocket连接
        
        Args:
            ws: WebSocket连接
            client_id: 可选的客户端ID，如果提供则清理对应的映射
        """
        with self._lock:
            self.active_connections.discard(ws)
            conn_id = id(ws)
            start_time = self._connection_times.pop(conn_id, None)
            
            # 清理客户端ID映射
            if client_id and self._client_id_mapping.get(client_id) == ws:
                del self._client_id_mapping[client_id]
            
            conn_info = self.get_connection_info(ws)
            if start_time:
                duration = (datetime.now() - start_time).total_seconds()
                conn_info['duration'] = f"{duration:.2f}s"
            log("DEBUG", f"[WebSocketManager] Connection removed: {json.dumps(conn_info, indent=2)}")

    def get_connection(self, client_id: str) -> Optional[Any]:
        """
        根据客户端ID获取WebSocket连接
        
        Args:
            client_id: 客户端ID
            
        Returns:
            Optional[Any]: WebSocket连接，如果不存在则返回None
        """
        with self._lock:
            return self._client_id_mapping.get(client_id)
    
    
    def send_to_client(self, client_id: str, message: Union[dict, str]) -> bool:
        """
        向指定客户端发送消息
        
        Args:
            client_id: 客户端ID
            message: 要发送的消息（dict 或字符串）
            
        Returns:
            bool: 是否成功入队（实际发送由后台线程异步完成）
        """
        with self._lock:
            ws = self._client_id_mapping.get(client_id)
        
        if not ws:
            return False
        
        # 将消息放入队列，由发送线程异步处理
        self._enqueue_message(ws, message)
        return True
    
    def broadcast_to_all(self, message: dict) -> int:
        """
        向所有连接广播消息
        
        Args:
            message: 要广播的消息（字典格式）
            
        Returns:
            int: 已入队的连接数（实际发送由后台线程异步完成）
        """
        with self._lock:
            all_connections = self.active_connections.copy()
        
        if not all_connections:
            return 0
        
        self._enqueue_message(all_connections, message)
        return len(all_connections)
    
    def close_all_connections(self):
        """关闭所有WebSocket连接（不停止发送线程，因为重启后需要继续使用）"""
        try:
            # 先复制连接列表，避免在锁内执行网络操作
            with self._lock:
                connections_to_close = self.active_connections.copy()
                # 清理连接和映射记录
                self.active_connections.clear()
                self._client_id_mapping.clear()
            
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
    
    def _enqueue_message(self, ws_or_set, message):
        """将消息放入发送队列（异步发送）"""
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

ws_manager = WebSocketManager()
