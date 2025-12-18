import os
import socket
import subprocess
from datetime import datetime

import requests

import constants
from services.process.process_manager import ProcessManager
from utils.logger import log


class ComfyUIProcessManager(ProcessManager):
    """ComfyUI 进程管理器"""
    
    HEALTH_CHECK_TIMEOUT = 2  # 健康检查超时时间（秒）
    SOCKET_TIMEOUT = 1  # Socket 连接超时时间（秒）

    def _is_ready(self) -> bool:
        """
        检查进程是否就绪，通过检查端口是否已被监听来判断后端进程是否已启动完成

        Returns:
            bool: 如果进程已就绪返回 True，否则返回 False
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.settimeout(self.SOCKET_TIMEOUT)
                result = sock.connect_ex(('127.0.0.1', constants.BACKEND_PROCESS_PORT))
                return result == 0
        except socket.timeout:
            return False
        except OSError as e:
            log("DEBUG", f"Socket error during readiness check: {e}")
            return False

    def _is_alive(self) -> bool:
        """
        通过发送 HTTP GET 请求到后端服务来检查进程是否存活

        健康检查策略：
        - 主动重启期间：跳过健康检查，避免误判为崩溃
        - CPU 模式：跳过健康检查，直接返回 True
        - 其他模式（GPU 等）：进行健康检查

        Returns:
            bool: 如果在超时时间内收到正常响应返回 True，否则返回 False
        """
        # CPU 模式无需进行健康检查
        if constants.COMFYUI_MODE == 'cpu':
            return True

        # 主动重启期间跳过健康检查，避免误判为崩溃
        from services.management_service import ManagementService, BackendStatus
        if ManagementService().status == BackendStatus.REBOOTING:
            return True

        try:
            response = requests.get(
                f'http://127.0.0.1:{constants.BACKEND_PROCESS_PORT}',
                timeout=self.HEALTH_CHECK_TIMEOUT
            )
            return response.status_code == 200
        except requests.Timeout:
            log("DEBUG", "Health check timed out")
            return False
        except requests.ConnectionError:
            log("DEBUG", "Health check connection refused")
            return False
        except requests.RequestException as e:
            log("DEBUG", f"Health check failed: {e}")
            return False

    def _on_process_died(self):
        """
        进程死亡时的回调处理
        无论是线上服务还是项目开发，都采用本地重启方式
        """
        log(
            "WARNING",
            f"ComfyUI process has unexpectedly crashed (commonly due to OOM). "
            "Please try switching to a different GPU type or adjust your workflow configuration to prevent such crashes."
        )
        self._save_dmesg_log()
        
        log("INFO", "Restarting ComfyUI process...")
        self._do_restart()

    def _save_dmesg_log(self):
        """保存 dmesg 日志到 MNT_DIR 下的 crash_reports 目录"""
        try:
            log_dir = os.path.join(constants.MNT_DIR, 'crash_reports')
            os.makedirs(log_dir, exist_ok=True)
            
            timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
            log_file = os.path.join(log_dir, f'dmesg-{timestamp}.log')
            
            # 执行 dmesg -T 获取带时间戳的内核日志
            result = subprocess.run(
                ['dmesg', '-T'],
                capture_output=True,
                text=True,
                timeout=3
            )
            
            with open(log_file, 'w') as f:
                f.write(f"=== DMESG captured at {timestamp} ===\n")
                f.write(f"=== Health check failed, process exiting ===\n\n")
                f.write(result.stdout)
                if result.stderr:
                    f.write(f"\n=== STDERR ===\n{result.stderr}")
            
            log("INFO", f"Saved dmesg log to: {log_file}")
        except Exception as e:
            log("WARNING", f"Failed to save dmesg log: {e}")

    def _do_restart(self):
        """重启 ComfyUI 进程（项目开发模式），无需加载 snapshot"""
        from services.management_service import ManagementService, BackendStatus, Action
        service = ManagementService()
        
        try:
            service._transition_to(BackendStatus.REBOOTING, Action.REBOOT)
            
            # 清理旧进程资源，防止僵尸进程
            self._cleanup_dead_process()
            
            # 重新启动 ComfyUI 进程
            self.start(constants.BOOT_CMD)
            self.wait_until_ready()
            
        except Exception as e:
            # 如果重启失败，有两种方案：则退出主进程作为兜底
            # 1. 依靠健康检查机制进行重试
            # 2. 退出主进程作为兜底
            #    若是项目开发环境，则会触发实例轮转，旧的工作空间丢失
            #    若是线上服务环境，同步调用会触发实例轮转，异步调用会hang住直到超时，需要手动驱逐实例
            # 因此，采用方案1，将状态转回 RUNNING，让健康检查继续工作并触发重试，除非用户手动驱逐实例
            # 注意：不能转换到 STOPPED，因为 STOPPED 只能转换到 STARTING（不能到 REBOOTING）
            log("WARNING", f"Failed to restart ComfyUI process: {e}")
            
        finally:
            try:
                service._transition_to(BackendStatus.RUNNING, Action.REBOOT)
            except Exception as transition_error:
                log("ERROR", f"Failed to update service status: {transition_error}")
