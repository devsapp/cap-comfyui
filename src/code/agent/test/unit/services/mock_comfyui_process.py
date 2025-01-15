import signal
import time
import socket
import sys


def signal_handler(signum, frame):
    print(f"Received signal {signum}")
    sys.exit(0)


def main():
    # 注册信号处理器
    signal.signal(signal.SIGTERM, signal_handler)

    # 模拟启动过程
    print("Mock server starting...")
    counter = 0
    while counter < 3:
        print(f"Mock server boot log message #{counter}")
        counter += 1
        time.sleep(1)

    # 尝试绑定8188端口
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(('localhost', 8188))
        sock.listen(1)
        print("Server is listening on port 8188")
    except Exception as e:
        print(f"Failed to bind port: {e}")
        sys.exit(1)

    # 模拟运行过程
    counter = 0
    while True:
        print(f"Mock server log message #{counter}")
        counter += 1
        time.sleep(1)


if __name__ == "__main__":
    main()
