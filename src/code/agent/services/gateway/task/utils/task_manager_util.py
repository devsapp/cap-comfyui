"""
任务状态广播器 - 处理WebSocket消息广播和ComfyUI消息格式转换
工具类，提供静态方法
"""
import traceback
from typing import Callable, Union

import constants
from utils.logger import log


class TaskStatusBroadcaster:
    """处理任务状态的WebSocket广播"""
    
    # FIXME:@dehui.kdh, 不是广播，而是直接推送给客户端
    @staticmethod
    def broadcast_task_status(task_id: str, status_data: Union[dict, str]):
        """
        通过WebSocket直接转发任务状态给对应的客户端
        从状态文件读到什么就转发什么，不进行额外处理
        
        Args:
            task_id: 任务ID
            status_data: 从状态文件读取的原始状态数据（dict 或原始字符串）
        """
        try:
            # 只在CPU模式下广播
            if constants.COMFYUI_MODE != "cpu":
                return
            
            from services.gateway import get_task_manager
            from services.process.websocket.websocket_manager import ws_manager
            
            # 数据为空直接返回
            if not status_data:
                return
            
            # 通过 task_id 获取 Task，再获取 client_id
            task_manager = get_task_manager()
            task = task_manager._tasks.get(task_id)
            
            if not task:
                log("WARNING", f"Task {task_id} not found, cannot broadcast status")
                return

            # 将消息发送给对应的客户端
            if isinstance(status_data, list):
                for msg in status_data:
                    ws_manager.send_to_client(task.client_id, msg)
            else:
                ws_manager.send_to_client(task.client_id, status_data)

        except Exception as e:
            log("ERROR", f"Error broadcasting task status via WebSocket: {e}")
    
    @staticmethod
    def broadcast_queue_status(get_pending_task_count_fn: Callable[[], int]):
        """广播当前队列状态给所有连接（类似 ComfyUI 的 queue_updated）
        
        Args:
            get_pending_task_count_fn: 获取运行中任务数量的函数
        """
        try:
            # 只在CPU模式下广播
            if constants.COMFYUI_MODE != "cpu":
                return
            
            from services.process.websocket.websocket_manager import ws_manager
            
            # 获取当前队列中的任务数
            pending_count = get_pending_task_count_fn()
            
            # 构建 ComfyUI 格式的状态消息
            queue_status_msg = {
                "type": "status",
                "data": {
                    "status": {
                        "exec_info": {
                            "queue_remaining": pending_count
                        }
                    }
                }
            }
            
            # 将队列状态消息广播给所有连接
            ws_manager.broadcast_to_all(queue_status_msg)

        except Exception as e:
            log("ERROR", f"[TaskStatusBroadcaster] Failed to broadcast queue status: {e}")
            log("ERROR", f"Traceback: {traceback.format_exc()}")
    

