"""
任务状态广播器 - 处理WebSocket消息广播和ComfyUI消息格式转换
"""
import traceback
from typing import Callable

import constants
from utils.logger import log


class TaskStatusBroadcaster:
    """处理任务状态的WebSocket广播"""
    
    def __init__(self, get_pending_task_count_fn: Callable[[], int]):
        """
        Args:
            get_pending_task_count_fn: 获取运行中任务数量的函数
        """
        self._get_pending_task_count = get_pending_task_count_fn
    
    def broadcast_task_status(self, task_id: str, status_data: dict):
        """
        通过WebSocket广播任务状态给订阅者，使用ComfyUI原生消息格式
        
        Args:
            task_id: 任务ID
            status_data: 从 GPU函数获取的原始状态数据
        """
        try:
            # 只在CPU模式下广播
            if constants.COMFYUI_MODE != "cpu":
                return
            
            from services.process.websocket.websocket_manager import ws_manager
            
            # 转换为ComfyUI格式
            comfyui_message = self._convert_to_comfyui_message_format(task_id, status_data)
            if not comfyui_message:
                log("DEBUG", f"[TaskStatusBroadcaster] Skipping broadcast for task {task_id}: message conversion returned None (type: {status_data.get('type', 'unknown')})")
                return
            
            # 广播消息
            if isinstance(comfyui_message, list):
                for msg in comfyui_message:
                    subscriber_count = ws_manager.broadcast_comfyui_message(task_id, msg)
                    log("DEBUG", f"[TaskStatusBroadcaster] Broadcasted message to {subscriber_count} subscribers for task {task_id} (type: {msg.get('type', 'unknown')})")
            else:
                subscriber_count = ws_manager.broadcast_comfyui_message(task_id, comfyui_message)
                log("DEBUG", f"[TaskStatusBroadcaster] Broadcasted message to {subscriber_count} subscribers for task {task_id} (type: {comfyui_message.get('type', 'unknown')})")
            
        except Exception as e:
            log("ERROR", f"Error broadcasting task status via WebSocket: {e}")
    
    def broadcast_queue_status(self, caller_info: str = "unknown"):
        """广播当前队列状态给所有连接（类似 ComfyUI 的 queue_updated）"""
        try:
            # 只在CPU模式下广播
            if constants.COMFYUI_MODE != "cpu":
                return
            
            from services.process.websocket.websocket_manager import ws_manager
            
            # 获取当前队列中的任务数
            pending_count = self._get_pending_task_count()
            
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
            
            # 广播给所有连接（使用特殊的 task_id "queue_status"）
            ws_manager.broadcast_comfyui_message("queue_status", queue_status_msg)
            
            log("INFO", f"[TaskStatusBroadcaster] Broadcasted queue status: queue_remaining={pending_count}, caller={caller_info}")
            
        except Exception as e:
            log("ERROR", f"[TaskStatusBroadcaster] Failed to broadcast queue status: {e}")
            log("ERROR", f"Traceback: {traceback.format_exc()}")
    
    def associate_task_with_client_id(self, task_id: str, client_id: str):
        """
        将任务与指定的ComfyUI客户端关联，使前端能够接收到任务状态更新
        
        Args:
            task_id: 任务ID
            client_id: ComfyUI客户端ID
        """
        # 只在CPU模式下才需要关联
        if constants.COMFYUI_MODE != "cpu":
            return
        
        try:
            from services.process.websocket.websocket_manager import ws_manager
            
            # 将任务与客户端关联
            associated_count = ws_manager.associate_task_with_client_id(task_id, client_id)
            
            if associated_count > 0:
                log("INFO", f"Task {task_id} successfully associated with ComfyUI client {client_id} ({associated_count} connections)")
            else:
                # 如果找不到连接，记录警告但不阻止任务继续
                # 如果WebSocket连接在任务提交之后建立，resubscribe_client_tasks会处理订阅
                log("WARNING", f"Failed to associate task {task_id} with client {client_id} - no connections found (will retry when WebSocket connects)")
            
        except Exception as e:
            log("ERROR", f"Failed to associate task {task_id} with client {client_id}: {e}")
            log("ERROR", f"Traceback: {traceback.format_exc()}")
    
    def _convert_to_comfyui_message_format(self, task_id: str, status_data: dict):
        """将状态数据转换为ComfyUI消息格式"""
        try:
            status_type = status_data.get('type', '')
            data = status_data.get('data', {})
            
            if status_type == 'serverless_api':
                # 最终结果
                return {
                    "type": "serverless_api",
                    "data": data
                }
            
            elif status_type == 'executing':
                # 执行中状态（node 为 None 表示执行结束）
                node = data.get('node')
                return {
                    "type": "executing",
                    "data": {
                        "node": node,  # 可以是 None（表示执行结束）
                        "prompt_id": data.get('prompt_id', task_id)
                    }
                }
            
            elif status_type == 'progress':
                # 进度更新
                return {
                    "type": "progress",
                    "data": {
                        "value": data.get('value', 0),
                        "max": data.get('max', 100),
                        "prompt_id": data.get('prompt_id', task_id)
                    }
                }
            
            elif status_type == 'status':
                # 队列状态更新 - 使用消息队列后已经线程安全，可以广播
                # 返回 ComfyUI 标准的 status 消息格式
                return {
                    "type": "status",
                    "data": {
                        "status": {
                            "exec_info": {
                                "queue_remaining": data.get('queue_remaining', 0)
                            }
                        }
                    }
                }
            
            elif status_type in ('error', 'execution_error'):
                # 执行错误：error 和 execution_error 统一转换为 execution_error
                return {
                    "type": "execution_error",
                    "data": {
                        "prompt_id": data.get('prompt_id', task_id),
                        "node_id": data.get('node_id'),
                        "exception_message": data.get('exception_message', str(data.get('message', 'Unknown error'))),
                        "exception_type": data.get('exception_type', 'RuntimeError'),
                        "traceback": data.get('traceback', [])
                    }
                }
            
            elif status_type in ('execution_start', 'execution_success', 'execution_cached', 'executed'):
                # ComfyUI 执行状态消息，直接返回原格式
                return status_data
            
            # 其他类型的消息直接返回
            log("DEBUG", f"[TaskStatusBroadcaster] Unknown status type '{status_type}', returning raw status_data for task {task_id}")
            return status_data
            
        except Exception as e:
            log("ERROR", f"Error converting to ComfyUI message format: {e}")
            return None

