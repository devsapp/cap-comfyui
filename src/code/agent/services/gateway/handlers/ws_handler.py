"""
WebSocket Handler
处理 /ws WebSocket 连接逻辑
"""
import time
import traceback

from flask import request, g

from services.gateway import get_task_manager
from services.gateway.task.task import TaskStatus
from services.process.websocket.websocket_manager import ws_manager
from utils.logger import log
from utils.user_identity import extract_user_from_header


class WsHandler:
    """处理 WebSocket 连接"""
    
    def __init__(self):
        self.task_manager = get_task_manager()
    
    def handle_connection(self, ws):
        """
        CPU函数接收ComfyUI原生的WebSocket连接
        保持与ComfyUI前端完全兼容，但推送的是基于任务队列和状态轮询的真实状态
        
        支持重连机制：
        - 客户端可通过 ?clientId=xxx 参数传递已有的 client_id
        - 重连时会复用相同的 client_id，确保能接收到之前任务的状态更新
        
        Args:
            ws: WebSocket 连接对象
        """
        client_id = None
        try:
            # 从查询参数获取 clientId（ComfyUI 前端重连时会传递）
            client_id = request.args.get('clientId', '')
            
            if client_id:
                # 复用已有的 client_id（重连场景）
                log("INFO", f"WebSocket reconnecting with existing client_id: {client_id}")
            else:
                # 生成新的 client_id（首次连接）
                client_id = f"funart_client_{int(time.time() * 1000)}"
                log("INFO", f"New ComfyUI WebSocket connection with client_id: {client_id}")
            
            user_id = extract_user_from_header()
            g.user_id = user_id if user_id is not None else 'default'
            
            log("INFO", f"[WsHandler] WebSocket connection established: client_id={client_id}, user_id={g.user_id}")
            
            # 添加连接到管理器（同时关联 client_id 和 user_id，处理重连逻辑）
            # 注意：这里传递 g.user_id 而不是原始的 user_id，确保在未认证时也能正确建立映射
            ws_manager.add_connection(ws, client_id, g.user_id)
            
            # 通过消息队列发送初始状态消息，保证线程安全
            initial_status = {
                "type": "status",
                "data": {
                    "sid": client_id,
                    "status": {
                        "exec_info": {
                            "queue_remaining": self.task_manager.get_running_task_count_by_user(g.user_id)
                        }
                    }
                }
            }
            # 将初始状态放入发送队列
            ws_manager._enqueue_message(ws, initial_status)
            
            # 设置客户端ID，用于后续关联任务
            setattr(ws, '_comfyui_client_id', client_id)

            while True:
                try:
                    message = ws.receive()
                    log("DEBUG", f"Received message from ComfyUI frontend: {message[:100]}...")

                except Exception as e:
                    error_str = str(e)
                    if "Connection closed" in error_str or "closed" in error_str.lower():
                        log("INFO", f"Connection closed by client")
                        break
                    log("ERROR", f"Error receiving message: {e}\n{traceback.format_exc()}")
                    break
        except Exception as e:
            log("ERROR", f"Connection error: {e}\n{traceback.format_exc()}")
        finally:
            try:
                # 传入 client_id 以便清理映射
                ws_manager.remove_connection(ws, client_id)
                log("INFO", f"ComfyUI WebSocket connection closed")
            except Exception as e:
                log("ERROR", f"Error removing connection: {e}")
