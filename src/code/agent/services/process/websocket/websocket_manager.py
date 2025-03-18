import json
import threading
from datetime import datetime


class WebSocketManager:
    def __init__(self):
        self.active_connections = set()  # 存储和用户comfyui client建立的所有活跃WebSocket连接
        self._lock = threading.Lock()
        self._connection_times = {}

    def get_connection_info(self, ws):
        environ = ws.environ
        return {
            'connection_id': id(ws),
            'address': environ.get('REMOTE_ADDR'),
            'port': environ.get('REMOTE_PORT')
        }

    def add_connection(self, ws):
        with self._lock:
            self.active_connections.add(ws)
            self._connection_times[id(ws)] = datetime.now()
            conn_info = self.get_connection_info(ws)
            print(f"ws connected: {json.dumps(conn_info, indent=2)}")

    def remove_connection(self, ws):
        with self._lock:
            self.active_connections.discard(ws)
            conn_id = id(ws)
            start_time = self._connection_times.pop(conn_id, None)
            conn_info = self.get_connection_info(ws)
            if start_time:
                duration = (datetime.now() - start_time).total_seconds()
                conn_info['duration'] = f"{duration:.2f}s"
            print(f"ws disconnected, {json.dumps(conn_info, indent=2)}")

    def close_all_connections(self):
        with self._lock:
            for ws in self.active_connections:
                try:
                    ws.send('Server shutting down')
                    ws.close()
                except Exception as e:
                    print(f"Error closing WebSocket connection: {e}")
            self.active_connections.clear()


ws_manager = WebSocketManager()
