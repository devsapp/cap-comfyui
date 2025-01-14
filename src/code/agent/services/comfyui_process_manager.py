import socket

import constants
from services.process_manager import ProcessManager


class ComfyuiProcessManager(ProcessManager):
    # TODO: Comfyui进程重启问题
    def is_ready(self) -> bool:
        """
        检查进程是否就绪，通过检查对应端口是否已被监听来判断comfyui进程是否已启动完成

        Returns:
            bool: 如果进程已就绪则返回True，否则返回False
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.settimeout(1)
            result = sock.connect_ex(('127.0.0.1', constants.COMFYUI_PROCESS_PORT))
            sock.close()
            # TODO: 处理非预期result值
            return result == 0  # 若result为0，则端口被占用(即comfyui进程启动成功)
        except:
            # TODO: handle corner cases
            return False

    def is_living(self) -> bool:
        """
        TODO 检查进程是否存活

        Returns:
            bool: 如果进程存在且正在运行则返回True，否则返回False
        """
        return True
