"""
Mock 不健康的 ComfyUI 进程
端口可以连接，但 HTTP 请求不返回 200 状态码
"""
import signal
import time
import sys
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler


class UnhealthyHandler(BaseHTTPRequestHandler):
    """返回 500 错误的处理器"""
    def do_GET(self):
        self.send_response(500)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Server is unhealthy!")
    
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
        server = HTTPServer(('127.0.0.1', 8188), UnhealthyHandler)
        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.daemon = True
        server_thread.start()
        
        print("Unhealthy server is listening on port 8188")
        
        while True:
            time.sleep(1)
    except Exception as e:
        print(f"Failed to start server: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

