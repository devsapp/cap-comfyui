"""
Mock ComfyUI 进程，用于测试 ProcessManager
使用 Python 标准库实现简单的 HTTP 服务器，不依赖 flask
"""
import signal
import time
import sys
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler


class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Mock ComfyUI server is running!")
    
    def log_message(self, format, *args):
        # 静默日志，避免干扰测试输出
        pass


server = None


def signal_handler(signum, frame):
    print(f"Received signal {signum}")
    if signum == signal.SIGTERM:
        print("Shutting down...")
        if server:
            server.shutdown()
        sys.exit(0)
    elif signum == signal.SIGHUP:
        print("Received SIGHUP, simulating crash...")
        if server:
            server.shutdown()
        sys.exit(1)


def main():
    global server
    current_pid = os.getpid()
    print(f"Current process PID: {current_pid}")

    # 注册信号处理器
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGHUP, signal_handler)

    # 模拟启动过程（缩短启动时间以加快测试）
    print("Mock server starting...")
    time.sleep(0.5)

    try:
        # 创建并启动服务器
        server = HTTPServer(('127.0.0.1', 8188), SimpleHandler)
        
        # 在单独线程中运行服务器
        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.daemon = True
        server_thread.start()
        
        print("Server is listening on port 8188")

        # 主线程继续输出日志
        counter = 0
        while True:
            print(f"Mock server log message #{counter}")
            counter += 1
            time.sleep(1)

    except Exception as e:
        print(f"Failed to start server: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
