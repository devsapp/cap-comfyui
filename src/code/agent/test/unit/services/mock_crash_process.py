"""
Mock 启动后立即崩溃的 ComfyUI 进程
模拟 OOM 或其他原因导致进程异常退出
"""
import time
import sys


def main():
    print("Process starting...")
    time.sleep(0.5)
    print("Process about to crash!")
    # 以非零状态码退出，模拟崩溃
    sys.exit(137)  # 137 通常表示被 SIGKILL 杀死（如 OOM）


if __name__ == "__main__":
    main()

