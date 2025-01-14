import subprocess
import threading
import time
from abc import ABC, abstractmethod
from typing import Optional

import constants


class ProcessManager(ABC):
    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.stdout_thread = None
        self.stderr_thread = None

    def start(self, command: list):
        """
        启动子进程

        Args:
            command: 要执行的命令列表，例如 ['python', 'script.py']
        """
        try:
            self.process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1  # 行缓冲
            )
            print(f"Started process with PID: {self.process.pid}")

            # 启动标准输出和标准错误的读取线程
            def read_output(pipe, prefix=''):
                for line in iter(pipe.readline, ''):
                    print(f"{prefix}{line.strip()}")
                pipe.close()
            self.stdout_thread = threading.Thread(
                target=read_output,
                args=(self.process.stdout, '[OUT] '),
                daemon=True
            )
            self.stderr_thread = threading.Thread(
                target=read_output,
                args=(self.process.stderr, '[ERR] '),
                daemon=True
            )

            self.stdout_thread.start()
            self.stderr_thread.start()

            return True
        except Exception as e:
            print(f"Failed to start process: {e}")
            return False

    def wait_until_ready(self,
                         poll_interval: float = constants.DEFAULT_READINESS_POLL_INTERVAL,
                         timeout: float = constants.DEFAULT_READINESS_TIMEOUT) -> bool:
        """
        同步轮询等待进程就绪

        Args:
            poll_interval: 轮询间隔时间(秒)
            timeout: 超时时间(秒)

        Returns:
            bool: 是否成功就绪
        """
        start_time = time.time()

        while True:
            # 检查是否超时
            if time.time() - start_time > timeout:
                print(f"Process startup timed out after {timeout} seconds")
                return False

            # 检查是否就绪
            if self.is_ready():
                print("Process is ready")
                return True

            # 等待指定的轮询间隔
            time.sleep(poll_interval)

    def stop(self):
        """停止子进程"""
        if self.process:
            try:
                self.process.kill()
                self.process.wait()

                # 关闭标准输出和标准错误管道
                if self.process.stdout:
                    self.process.stdout.close()
                if self.process.stderr:
                    self.process.stderr.close()

                # 等待输出读取线程结束
                if self.stdout_thread and self.stdout_thread.is_alive():
                    self.stdout_thread.join(timeout=1)
                if self.stderr_thread and self.stderr_thread.is_alive():
                    self.stderr_thread.join(timeout=1)

                # 清理相关对象
                self.process = None
                self.stdout_thread = None
                self.stderr_thread = None

                print("Process killed")
                return True
            except Exception as e:
                print(f"Error stopping process: {e}")
                return False
        return False

    @abstractmethod
    def is_ready(self) -> bool:
        """检查进程是否就绪"""
        pass

    @abstractmethod
    def is_living(self) -> bool:
        """检查进程是否存活"""
        pass
