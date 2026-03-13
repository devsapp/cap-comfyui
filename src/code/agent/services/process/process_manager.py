import subprocess
import threading
import time
from abc import ABC, abstractmethod
from typing import Optional

import constants
from constants import BACKEND_TYPE
from utils.logger import log


class ProcessManager(ABC):
    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.stdout_thread = None
        self.stderr_thread = None
        self.health_check_thread = None
        self.should_monitor = False
        self._lock = threading.Lock()

    def start(self, command: list) -> None:
        """
        启动子进程

        Args:
            command: 要执行的命令列表，例如 ['python', 'script.py']
        """
        try:
            # 记录启动命令
            log("INFO", f"Starting {BACKEND_TYPE.capitalize()} process with command:")
            log("INFO", f"  Command: {' '.join(command)}")

            self.process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1  # 行缓冲
            )
            log("INFO", f"Started {BACKEND_TYPE.capitalize()} process with PID: {self.process.pid}")

            # 启动标准输出和标准错误的读取线程
            def read_output(pipe):
                for line in iter(pipe.readline, ''):
                    print(line.strip())
                pipe.close()
            self.stdout_thread = threading.Thread(
                target=read_output,
                args=(self.process.stdout,),
                daemon=True
            )
            self.stderr_thread = threading.Thread(
                target=read_output,
                args=(self.process.stderr,),
                daemon=True
            )

            self.stdout_thread.start()
            self.stderr_thread.start()
        except Exception as e:
            log("ERROR", f"Failed to start {BACKEND_TYPE.capitalize()} process: {e}")
            raise

    def wait_until_ready(self,
                         poll_interval: float = constants.DEFAULT_READINESS_POLL_INTERVAL,
                         timeout: float = constants.DEFAULT_READINESS_TIMEOUT) -> None:
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
                log("ERROR", f"{BACKEND_TYPE.capitalize()} process startup timed out after {timeout} seconds")
                raise RuntimeError(f"{BACKEND_TYPE.capitalize()} process startup timed out")

            # 检查是否就绪
            if self._is_ready():
                log("INFO", f"{BACKEND_TYPE.capitalize()} process is ready")
                # 进程就绪后启动liveness探针
                self.start_health_check()
                return

            # 等待指定的轮询间隔
            time.sleep(poll_interval)

    def _health_check(self, poll_interval: float = constants.DEFAULT_LIVENESS_POLL_INTERVAL):
        """健康检查线程函数"""
        while self.should_monitor:
            try:
                if not self._is_alive():
                    self._on_process_died()
                time.sleep(poll_interval)
            except Exception as e:
                log("ERROR", f"Error in health check: {e}")
                raise

    def start_health_check(self, poll_interval: float = constants.DEFAULT_LIVENESS_POLL_INTERVAL):
        """启动健康检查线程"""
        with self._lock:
            if self.health_check_thread is None or not self.health_check_thread.is_alive():
                self.should_monitor = True
                self.health_check_thread = threading.Thread(
                    target=self._health_check,
                    args=(poll_interval,),
                    daemon=True
                )
                self.health_check_thread.start()
                log("INFO", f"{BACKEND_TYPE.capitalize()} health check thread started")

    # 超时配置
    PROCESS_WAIT_TIMEOUT = 10  # SIGKILL 后等待进程退出的超时时间（秒），超时说明进程卡在内核态 D 状态
    HEALTH_CHECK_JOIN_TIMEOUT = 1  # stop() 中等待健康检查线程退出的超时时间（秒）

    def _kill_and_cleanup(self):
        """
        仅杀死子进程并清理相关资源（管道、线程引用），不涉及健康检查线程和 WebSocket 连接管理。

        供 stop() 和 _do_restart() 内部调用：
        - stop()：先停止健康检查线程，再调用此方法杀死进程，最后关闭 WebSocket 连接
        - _do_restart()：在健康检查线程内部调用，仅需杀死旧进程，不能操作健康检查线程（因为自身就是该线程）
        """
        with self._lock:
            if self.process is None:
                return

            pid = self.process.pid
            try:
                self.process.kill()
                try:
                    self.process.wait(timeout=self.PROCESS_WAIT_TIMEOUT)
                except subprocess.TimeoutExpired:
                    log("WARNING", f"Process {pid} did not exit within {self.PROCESS_WAIT_TIMEOUT}s after SIGKILL "
                        "(possibly stuck in D state due to I/O), proceeding with cleanup")

                if self.process.stdout:
                    self.process.stdout.close()
                if self.process.stderr:
                    self.process.stderr.close()

                if self.stdout_thread and self.stdout_thread.is_alive():
                    self.stdout_thread.join(timeout=1)
                if self.stderr_thread and self.stderr_thread.is_alive():
                    self.stderr_thread.join(timeout=1)

                self.process = None
                self.stdout_thread = None
                self.stderr_thread = None

                log("INFO", f"{BACKEND_TYPE.capitalize()} process stopped (pid: {pid})")
            except Exception as e:
                log("ERROR", f"Error stopping {BACKEND_TYPE.capitalize()} process: {e}")
                raise

    def stop(self) -> None:
        """
        停止子进程（完整流程：停止健康检查 + 杀死进程 + 清理资源）。

        注意：主动调用 stop() 时，健康检查线程可能正在执行 _do_restart() 中耗时较长的 wait_until_ready()。
        此时 join 仅等待 HEALTH_CHECK_JOIN_TIMEOUT（1秒），超时后立即继续执行后续的杀进程操作，
        不等待健康检查线程的重启流程完成。健康检查线程会因为 should_monitor=False 在重启流程结束后自行退出。
        """
        # 通知健康检查线程停止，短暂等待后立即继续
        self.should_monitor = False
        if self.health_check_thread and self.health_check_thread.is_alive():
            self.health_check_thread.join(timeout=self.HEALTH_CHECK_JOIN_TIMEOUT)
            if self.health_check_thread.is_alive():
                log("WARNING", "Health check thread still running (may be in restart flow), "
                    "proceeding with stop immediately")

        self._kill_and_cleanup()
        self.health_check_thread = None

        # 关闭所有 WebSocket 连接，通知前端客户端服务已停止
        # 仅在 stop() 中执行，restart 时不需要
        from services.process.websocket.websocket_manager import ws_manager
        ws_manager.close_all_connections(timeout=5)

    @abstractmethod
    def _is_ready(self) -> bool:
        """检查进程是否就绪，由子类实现"""
        pass

    @abstractmethod
    def _is_alive(self) -> bool:
        """检查进程是否存活，由子类实现"""
        pass

    @abstractmethod
    def _on_process_died(self):
        """进程死亡时的回调处理，由子类实现具体逻辑"""
        pass
