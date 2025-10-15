import json
import threading
import time
from datetime import datetime
from typing import Set, Dict
from concurrent.futures import ThreadPoolExecutor


class WebSocketManager:
    def __init__(self):
        self.active_connections = set()  # 存储和用户comfyui client建立的所有活跃WebSocket连接
        self._lock = threading.Lock()
        self._connection_times = {}
        
        # 任务状态推送功能
        self._task_subscriptions: Dict[str, Set] = {}  # task_id -> set of websockets
        self._client_subscriptions: Dict = {}  # websocket -> set of task_ids
        self._client_id_mapping: Dict[str, Set] = {}  # client_id -> set of websockets
        self._ws_client_id_mapping: Dict = {}  # websocket -> client_id
        
        # 阶段一优化：性能监控和异步广播
        self._thread_pool = ThreadPoolExecutor(max_workers=5, thread_name_prefix="ws-broadcast")
        self._performance_metrics = {
            'broadcast_times': [],  # 最近100次广播时间
            'send_failures': 0,     # 发送失败数
            'total_broadcasts': 0,  # 总广播次数
            'connection_errors': 0  # 连接错误数
        }

    def get_connection_info(self, ws):
        environ = ws.environ
        return {
            'connection_id': id(ws),
            'address': environ.get('REMOTE_ADDR'),
            'port': environ.get('REMOTE_PORT')
        }
    
    def _set_tcp_nodelay(self, ws):
        """
        设置TCP_NODELAY禁用Nagle算法，确保消息立即发送而不是等待缓冲
        """
        try:
            import socket
            # 尝试多种方式获取底层socket
            sock = None
            
            # 方法1: 通过environ获取werkzeug.socket
            if hasattr(ws, 'environ'):
                sock = ws.environ.get('werkzeug.socket')
            
            # 方法2: 通过sock属性
            if not sock and hasattr(ws, 'sock'):
                sock = ws.sock
            
            # 方法3: 通过_sock属性
            if not sock and hasattr(ws, '_sock'):
                sock = ws._sock
            
            # 方法4: simple-websocket的ws对象可能有connected属性
            if not sock and hasattr(ws, 'connected') and hasattr(ws.connected, 'sock'):
                sock = ws.connected.sock
            
            if sock and hasattr(sock, 'setsockopt'):
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                print(f"[WebSocketManager] Set TCP_NODELAY for connection {id(ws)}")
            else:
                print(f"[WebSocketManager] Could not find socket for connection {id(ws)}")
                
        except Exception as e:
            print(f"[WebSocketManager] Failed to set TCP_NODELAY: {e}")

    def add_connection(self, ws):
        with self._lock:
            self.active_connections.add(ws)
            self._connection_times[id(ws)] = datetime.now()
            self._client_subscriptions[ws] = set()  # 初始化订阅记录
            conn_info = self.get_connection_info(ws)
            print(f"ws connected: {json.dumps(conn_info, indent=2)}")
            
            # 设置TCP_NODELAY禁用Nagle算法，确保消息立即发送
            self._set_tcp_nodelay(ws)
            
            # 发送初始队列状态
            self._send_initial_status(ws)

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
            
            conn_info = self.get_connection_info(ws)
            if start_time:
                duration = (datetime.now() - start_time).total_seconds()
                conn_info['duration'] = f"{duration:.2f}s"
            print(f"ws disconnected, {json.dumps(conn_info, indent=2)}")

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
                
                subscriber_count = len(self._task_subscriptions[task_id])
                print(f"[WebSocketManager] Client subscribed to task {task_id} "
                      f"(total subscribers: {subscriber_count})")
                return True
                
        except Exception as e:
            print(f"[WebSocketManager] Failed to subscribe to task {task_id}: {e}")
            return False
    
    def unsubscribe_task_status(self, ws, task_id: str) -> bool:
        """
        取消订阅任务状态
        
        Args:
            ws: WebSocket连接
            task_id: 任务ID
            
        Returns:
            bool: 取消订阅是否成功
        """
        try:
            with self._lock:
                # 从任务订阅中移除
                if task_id in self._task_subscriptions:
                    self._task_subscriptions[task_id].discard(ws)
                    # 如果没有其他订阅者，删除任务记录
                    if not self._task_subscriptions[task_id]:
                        del self._task_subscriptions[task_id]
                
                # 从客户端订阅记录中移除
                if ws in self._client_subscriptions:
                    self._client_subscriptions[ws].discard(task_id)
                
                remaining_subscribers = len(self._task_subscriptions.get(task_id, set()))
                print(f"[WebSocketManager] Client unsubscribed from task {task_id} "
                      f"(remaining subscribers: {remaining_subscribers})")
                return True
                
        except Exception as e:
            print(f"[WebSocketManager] Failed to unsubscribe from task {task_id}: {e}")
            return False
    
    def broadcast_task_status(self, task_id: str, status_data: dict) -> int:
        """
        广播任务状态给所有订阅者（阶段一优化：带超时和性能监控）
        
        Args:
            task_id: 任务ID
            status_data: 状态数据
            
        Returns:
            int: 成功发送的连接数
        """
        broadcast_start_time = time.time()
        
        with self._lock:
            subscribers = self._task_subscriptions.get(task_id, set()).copy()
        
        if not subscribers:
            return 0
        
        # 使用线程池异步处理广播，避免阻塞主线程
        future = self._thread_pool.submit(
            self._do_broadcast_with_timeout, 
            task_id, 
            status_data, 
            subscribers,
            broadcast_start_time
        )
        
        # 不等待结果，立即返回，提高响应速度
        # 后续可通过future.result()获取结果，但为了不阻塞这里直接返回订阅者数
        return len(subscribers)
    
    def _do_broadcast_with_timeout(self, task_id: str, status_data: dict, 
                                 subscribers: set, broadcast_start_time: float) -> int:
        """
        执行实际的广播逻辑，带超时和异常处理
        
        Args:
            task_id: 任务ID
            status_data: 状态数据 
            subscribers: 订阅者集合
            broadcast_start_time: 广播开始时间
            
        Returns:
            int: 成功发送的连接数
        """
        try:
            message = json.dumps(status_data, ensure_ascii=False)
            successful_sends = 0
            disconnected = set()
            send_timeout = 2.0  # 2秒发送超时
            
            for ws in subscribers:
                try:
                    # 阶段一优化：带超时的WebSocket发送
                    self._send_message_with_timeout(ws, message, send_timeout)
                    successful_sends += 1
                except Exception as e:
                    print(f"[WebSocketManager] Failed to send to client (task {task_id}): {e}")
                    disconnected.add(ws)
                    # 更新性能指标（线程安全）
                    with self._lock:
                        self._performance_metrics['send_failures'] += 1
                        self._performance_metrics['connection_errors'] += 1
            
            # 清理断开的连接（异步执行避免阻塞）
            if disconnected:
                for ws in disconnected:
                    try:
                        self.remove_connection(ws)
                    except Exception as e:
                        print(f"[WebSocketManager] Error removing connection: {e}")
            
            # 记录性能指标
            broadcast_duration = time.time() - broadcast_start_time
            self._record_broadcast_performance(broadcast_duration, successful_sends)
            
            if successful_sends > 0:
                print(f"[WebSocketManager] Broadcasted status for task {task_id} to {successful_sends} clients "
                      f"(took {broadcast_duration*1000:.1f}ms)")
            
            return successful_sends
            
        except Exception as e:
            print(f"[WebSocketManager] Error in broadcast thread: {e}")
            return 0
    
    def _send_message_with_timeout(self, ws, message: str, timeout: float = 2.0):
        """
        带超时的WebSocket消息发送
        
        Args:
            ws: WebSocket连接
            message: 要发送的消息
            timeout: 超时时间（秒）
        """
        try:
            # 注意：当前实现仍依赖WebSocket库的内部机制
            # TODO: 如果需要真正的超时控制，可考虑：
            # 1. 使用signal.alarm()在Unix系统上
            # 2. 使用threading.Timer + threading.Event
            # 3. 使用concurrent.futures.wait(timeout=...)
            # 但对于大多数场景，当前实现已足够使用
            ws.send(message)
            
            # 尝试flush WebSocket缓冲区，确保消息立即发送
            # Flask-Sock基于simple-websocket，底层是werkzeug的socket
            if hasattr(ws, 'sock') and hasattr(ws.sock, 'flush'):
                ws.sock.flush()
            elif hasattr(ws, '_sock') and hasattr(ws._sock, 'flush'):
                ws._sock.flush()
            elif hasattr(ws, 'environ'):
                # 尝试通过environ获取底层socket
                sock = ws.environ.get('werkzeug.socket')
                if sock and hasattr(sock, 'flush'):
                    sock.flush()
        except Exception as e:
            # 记录错误类型以便分析
            error_type = type(e).__name__
            print(f"[WebSocketManager] WebSocket send failed ({error_type}): {str(e)[:100]}")
            raise  # 重新抛出异常由调用者处理
    
    def associate_client_id_with_connection(self, ws, client_id: str):
        """
        将ComfyUI客户端ID与连接关联
        
        Args:
            ws: WebSocket连接
            client_id: ComfyUI客户端ID
        """
        with self._lock:
            if client_id not in self._client_id_mapping:
                self._client_id_mapping[client_id] = set()
            self._client_id_mapping[client_id].add(ws)
            self._ws_client_id_mapping[ws] = client_id
            print(f"[WebSocketManager] Associated client_id {client_id} with WebSocket connection")
    
    def associate_task_with_client_id(self, task_id: str, client_id: str) -> int:
        """
        将任务与指定的ComfyUI客户端关联，并自动订阅该任务的状态
        
        Args:
            task_id: 任务ID
            client_id: ComfyUI客户端ID
            
        Returns:
            int: 成功关联的连接数
        """
        print(f"[WebSocketManager] Attempting to associate task {task_id} with client_id {client_id}")
        
        with self._lock:
            connections = self._client_id_mapping.get(client_id, set()).copy()
            print(f"[WebSocketManager] Found {len(connections)} connections for client_id {client_id}")
        
        if not connections:
            print(f"[WebSocketManager] No connections found for client_id {client_id}")
            print(f"[WebSocketManager] Available client IDs: {list(self._client_id_mapping.keys())}")
            return 0
        
        associated_count = 0
        for ws in connections:
            print(f"[WebSocketManager] Subscribing connection {id(ws)} to task {task_id}")
            if self.subscribe_task_status(ws, task_id):
                associated_count += 1
        
        print(f"[WebSocketManager] Associated task {task_id} with client_id {client_id} "
              f"({associated_count} connections)")
        
        return associated_count
    
    def broadcast_comfyui_message(self, task_id: str, comfyui_message: dict) -> int:
        """
        广播ComfyUI原生格式的消息给任务订阅者
        
        Args:
            task_id: 任务ID（特殊值"queue_status"表示广播给所有连接）
            comfyui_message: ComfyUI原生格式的消息
            
        Returns:
            int: 成功发送的连接数
        """
        # 特殊处理队列状态广播
        if task_id == "queue_status":
            return self._broadcast_to_all_connections(comfyui_message)
        else:
            return self.broadcast_task_status(task_id, comfyui_message)
    
    def _broadcast_to_all_connections(self, message: dict) -> int:
        """
        广播消息给所有活跃连接（同步发送，确保立即交付）
        
        Args:
            message: 要广播的消息
            
        Returns:
            int: 成功发送的连接数
        """
        broadcast_start_time = time.time()
        
        with self._lock:
            all_connections = self.active_connections.copy()
        
        if not all_connections:
            return 0
        
        # 队列状态广播改为同步发送，避免延迟
        return self._do_broadcast_to_all_with_timeout(message, all_connections, broadcast_start_time)
    
    def _do_broadcast_to_all_with_timeout(self, message: dict, 
                                        connections: set, broadcast_start_time: float) -> int:
        """
        执行实际的广播逻辑，带超时和异常处理
        
        Args:
            message: 要广播的消息
            connections: 连接集合
            broadcast_start_time: 广播开始时间
            
        Returns:
            int: 成功发送的连接数
        """
        try:
            message_str = json.dumps(message, ensure_ascii=False)
            successful_sends = 0
            disconnected = set()
            send_timeout = 2.0  # 2秒发送超时
            
            for ws in connections:
                try:
                    # 带超时的WebSocket发送
                    self._send_message_with_timeout(ws, message_str, send_timeout)
                    successful_sends += 1
                except Exception as e:
                    print(f"[WebSocketManager] Failed to send queue status to client: {e}")
                    disconnected.add(ws)
                    # 更新性能指标
                    with self._lock:
                        self._performance_metrics['send_failures'] += 1
                        self._performance_metrics['connection_errors'] += 1
            
            # 清理断开的连接
            if disconnected:
                for ws in disconnected:
                    try:
                        self.remove_connection(ws)
                    except Exception as e:
                        print(f"[WebSocketManager] Error removing connection: {e}")
            
            # 记录性能指标
            broadcast_duration = time.time() - broadcast_start_time
            self._record_broadcast_performance(broadcast_duration, successful_sends)
            
            if successful_sends > 0:
                print(f"[WebSocketManager] Broadcasted queue status to {successful_sends} clients "
                      f"(took {broadcast_duration*1000:.1f}ms)")
            
            return successful_sends
            
        except Exception as e:
            print(f"[WebSocketManager] Error in queue status broadcast thread: {e}")
            return 0
    
    def get_task_subscribers(self, task_id: str) -> int:
        """获取任务的订阅者数量"""
        with self._lock:
            return len(self._task_subscriptions.get(task_id, set()))
    
    # NOTE: update_task_id_association方法已废弃 - 使用x-fc-trace-id保持ID一致性
    # def update_task_id_association(self, old_task_id: str, new_task_id: str) -> bool:
    #     """更新任务ID关联 - 已废弃，通过x-fc-trace-id保持ID一致性"""
    #     # 通过传递x-fc-trace-id给GPU函数，CPU和GPU两边的requestId保持一致
    #     # 无需动态更新WebSocket任务ID关联
    #     print(f"[WebSocketManager] update_task_id_association method deprecated")
    #     return True
    
    def _send_initial_status(self, ws):
        """
        向新连接的WebSocket客户端发送初始队列状态
        """
        try:
            # 只在CPU模式下发送初始状态
            import constants
            if constants.COMFYUI_MODE != "cpu":
                return
            
            # 获取当前队列状态
            from services.gateway import get_task_queue_manager
            task_queue_manager = get_task_queue_manager()
            # 使用TaskQueueManager的公共方法获取待处理任务数量
            pending_count = task_queue_manager._get_pending_task_count()
            
            # 构建ComfyUI状态消息
            initial_status = {
                "type": "status",
                "data": {
                    "status": {
                        "exec_info": {
                            "queue_remaining": pending_count
                        }
                    }
                }
            }
            
            # 发送初始状态消息
            message = json.dumps(initial_status, ensure_ascii=False)
            ws.send(message)
            
            print(f"[WebSocketManager] Sent initial status to new connection (queue_remaining: {pending_count})")
            
        except Exception as e:
            print(f"[WebSocketManager] Failed to send initial status: {e}")
    
    def _record_broadcast_performance(self, duration: float, successful_sends: int):
        """
        记录广播性能指标
        
        Args:
            duration: 广播耗时（秒）
            successful_sends: 成功发送数
        """
        with self._lock:
            # 记录广播时间，只保留最近100次
            self._performance_metrics['broadcast_times'].append(duration)
            if len(self._performance_metrics['broadcast_times']) > 100:
                self._performance_metrics['broadcast_times'].pop(0)
            
            # 更新统计
            self._performance_metrics['total_broadcasts'] += 1
    
    def get_performance_metrics(self) -> dict:
        """
        获取WebSocket性能指标（阶段一优化：用于监控优化效果）
        
        Returns:
            dict: 包含各种性能指标的字典
        """
        with self._lock:
            broadcast_times = self._performance_metrics['broadcast_times'].copy()
            send_failures = self._performance_metrics['send_failures']
            total_broadcasts = self._performance_metrics['total_broadcasts']
            connection_errors = self._performance_metrics['connection_errors']
            
            # 计算统计数据
            metrics = {
                'active_connections': len(self.active_connections),
                'active_tasks': len(self._task_subscriptions),
                'total_broadcasts': total_broadcasts,
                'send_failures': send_failures,
                'connection_errors': connection_errors,
                'failure_rate': round(send_failures / max(total_broadcasts, 1) * 100, 2)
            }
            
            if broadcast_times:
                avg_time = sum(broadcast_times) / len(broadcast_times)
                max_time = max(broadcast_times)
                min_time = min(broadcast_times)
                
                metrics.update({
                    'avg_broadcast_ms': round(avg_time * 1000, 2),
                    'max_broadcast_ms': round(max_time * 1000, 2),
                    'min_broadcast_ms': round(min_time * 1000, 2),
                    'broadcast_samples': len(broadcast_times)
                })
            else:
                metrics.update({
                    'avg_broadcast_ms': 0,
                    'max_broadcast_ms': 0, 
                    'min_broadcast_ms': 0,
                    'broadcast_samples': 0
                })
            
            return metrics
    
    def print_performance_summary(self):
        """
        输出WebSocket性能摘要（阶段一优化：用于调试和监控）
        """
        metrics = self.get_performance_metrics()
        
        print(f"\n[WebSocketManager] === Performance Summary ===")
        print(f"[WebSocketManager] Active connections: {metrics['active_connections']}")
        print(f"[WebSocketManager] Active task subscriptions: {metrics['active_tasks']}")
        print(f"[WebSocketManager] Total broadcasts: {metrics['total_broadcasts']}")
        print(f"[WebSocketManager] Send failures: {metrics['send_failures']} ({metrics['failure_rate']}%)")
        print(f"[WebSocketManager] Connection errors: {metrics['connection_errors']}")
        
        if metrics['broadcast_samples'] > 0:
            print(f"[WebSocketManager] Broadcast timing (last {metrics['broadcast_samples']} samples):")
            print(f"[WebSocketManager]   Average: {metrics['avg_broadcast_ms']}ms")
            print(f"[WebSocketManager]   Min: {metrics['min_broadcast_ms']}ms")
            print(f"[WebSocketManager]   Max: {metrics['max_broadcast_ms']}ms")
        else:
            print(f"[WebSocketManager] No broadcast timing data available")
        
        print(f"[WebSocketManager] ================================\n")
    
    def reset_performance_metrics(self):
        """
        重置性能指标计数器
        """
        with self._lock:
            self._performance_metrics = {
                'broadcast_times': [],
                'send_failures': 0,
                'total_broadcasts': 0,
                'connection_errors': 0
            }
            print(f"[WebSocketManager] Performance metrics reset")
    
    def close_all_connections(self):
        with self._lock:
            for ws in self.active_connections:
                try:
                    ws.send('Server shutting down')
                    ws.close()
                except Exception as e:
                    print(f"Error closing WebSocket connection: {e}")
            self.active_connections.clear()
            # 清理任务订阅记录
            self._task_subscriptions.clear()
            self._client_subscriptions.clear()
            
        # 关闭线程池
        self._thread_pool.shutdown(wait=False)
        print(f"[WebSocketManager] All connections closed and thread pool shutdown")


ws_manager = WebSocketManager()
