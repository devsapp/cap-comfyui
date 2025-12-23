"""
Mock 响应缓慢的 ComfyUI 进程
端口可以连接，但 HTTP 请求响应非常慢，用于测试超时场景
"""
import signal
import time
import sys
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler


class SlowHandler(BaseHTTPRequestHandler):
    """响应缓慢的处理器"""
    def do_GET(self):
        # 延迟 15 秒，超过健康检查超时时间（10秒）
        time.sleep(15)
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Slow response")
    
    def log_message(self, format, *args):
        pass


server = None


def signal_handler(signum, frame):
    if server:
        server.shutdown()
    sys.exit(0)


def main():
    global server
    signal.signal(signal.SIGTERM, signal_handler)
    
    time.sleep(0.5)
    
    try:
        server = HTTPServer(('127.0.0.1', 8188), SlowHandler)
        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.daemon = True
        server_thread.start()
        
        print("Slow server is listening on port 8188")
        
        while True:
            time.sleep(1)
    except Exception as e:
        print(f"Failed to start server: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

