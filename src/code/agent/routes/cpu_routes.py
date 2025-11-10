import json
import os
import time
import traceback

from flask import Blueprint, Flask, jsonify, request
from flask_sock import Sock

from services.management_service import ManagementService, BackendStatus
from utils.logger import log
from services.gateway import (
    CpuGatewayService,
    HistoryGatewayService,
    get_task_queue
)
from services.process.websocket.websocket_manager import ws_manager
from services.serverlessapi.serverless_api_service import ServerlessApiService


class CpuRoutes:
    """CPU模式路由：处理任务队列和异步转发"""
    
    def __init__(self):
        # HTTP 路由使用 /api 前缀
        self.bp = Blueprint("cpu_routes", __name__, url_prefix="/api")
        # WebSocket 路由使用根路径（保持 ComfyUI 兼容性）
        self.ws_bp = Blueprint("cpu_ws", __name__)
        self.service = ManagementService()  # 单例模式，直接创建实例
        self.sock = Sock()
        self.sock.bp = self.ws_bp  # 将 WebSocket 绑定到单独的 Blueprint
        self.setup_routes()
    
    def register(self, app: Flask):
        app.register_blueprint(self.bp)
        app.register_blueprint(self.ws_bp)
    
    def setup_routes(self):
        """设置所有路由"""
        self._register_websocket()
        self._register_queue_handler()
        self._register_prompt_handler()
        self._register_serverless_run_handler()
        self._register_history_handler()
        # 通过环境变量控制是否禁用 userdata 保存
        # DISABLE_USERDATA_SAVE=true 时禁用
        disable_userdata = os.environ.get('DISABLE_USERDATA_SAVE', '').lower() in ('true', '1', 'yes')
        if disable_userdata:
            self._register_userdata_handler()
    
    def _check_backend_status(self):
        """
        检查后端服务状态
        
        Returns:
            tuple: (is_valid, error_response) 
                   is_valid为True时error_response为None
                   is_valid为False时error_response为错误响应
        """
        backend_status = self.service.status
        if backend_status not in (BackendStatus.RUNNING, BackendStatus.SAVING):
            return False, (jsonify({
                "status": "failed",
                "message": "Please start your comfyui/sd service first"
            }), 500)
        return True, None
    
    def _register_websocket(self):
        @self.sock.route("/ws")
        def comfyui_compatible_ws(ws):
            """
            CPU函数接收ComfyUI原生的WebSocket连接
            保持与ComfyUI前端完全兼容，但推送的是基于任务队列和状态轮询的真实状态
            
            支持重连机制：
            - 客户端可通过 ?clientId=xxx 参数传递已有的 client_id
            - 重连时会复用相同的 client_id，确保能接收到之前任务的状态更新
            """
            try:
                # 从查询参数获取 clientId（ComfyUI 前端重连时会传递）
                from flask import request as flask_request
                client_id = flask_request.args.get('clientId', '')
                
                if client_id:
                    # 复用已有的 client_id（重连场景）
                    log("INFO", f"WebSocket reconnecting with existing client_id: {client_id}")
                else:
                    # 生成新的 client_id（首次连接）
                    client_id = f"cpu_client_{int(time.time() * 1000)}"
                    log("INFO", f"New ComfyUI WebSocket connection with client_id: {client_id}")
                
                # 添加连接到管理器
                ws_manager.add_connection(ws)
                
                # 发送初始状态消息（模拟ComfyUI原生行为）
                try:
                    ws.send(json.dumps({
                        "type": "status",
                        "data": {
                            "sid": client_id,
                            "status": {
                                "exec_info": {
                                    "queue_remaining": get_task_queue()._get_pending_task_count()
                                }
                            }
                        }
                    }))
                except Exception as e:
                    log("ERROR", f"Failed to send initial status: {e}")
                    return
                
                # 设置客户端ID，用于后续关联任务
                setattr(ws, '_comfyui_client_id', client_id)
                
                # 将客户端ID与连接关联在WebSocketManager中
                ws_manager.associate_client_id_with_connection(ws, client_id)
                
                # 如果是重连，重新订阅该客户端的所有进行中的任务
                ws_manager.resubscribe_client_tasks(ws, client_id)
                
                # TODO 可能是多余的
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
                    ws_manager.remove_connection(ws)
                    log("INFO", f"ComfyUI WebSocket connection closed")
                except Exception as e:
                    log("ERROR", f"Error removing connection: {e}")
    
    def _register_queue_handler(self):
        @self.bp.route("/queue", methods=["GET", "POST"])
        def handle_queue():
            is_valid, error_response = self._check_backend_status()
            if not is_valid:
                return error_response
            
            try:
                gateway_service = CpuGatewayService()
                
                if request.method == "GET":
                    return gateway_service.handle_queue_get_request()
                elif request.method == "POST":
                    return gateway_service.handle_queue_post_request()
                else:
                    return jsonify({
                        "error": {
                            "type": "method_not_allowed",
                            "message": f"Method {request.method} not allowed"
                        }
                    }), 405
                    
            except Exception as e:
                error_msg = f"Failed to handle queue request: {str(e)}"
                log("ERROR", f"{error_msg}\nStacktrace:\n{traceback.format_exc()}")
                
                return jsonify({
                    "error": {
                        "type": "queue_operation_error",
                        "message": error_msg
                    }
                }), 500
    
    def _register_prompt_handler(self):
        @self.bp.route("/prompt", methods=["POST"])
        def handle_prompt():
            is_valid, error_response = self._check_backend_status()
            if not is_valid:
                return error_response
            
            try:
                gateway_service = CpuGatewayService()
                return gateway_service.handle_prompt_request_async()
            except Exception as e:
                error_msg = f"Failed to handle prompt request: {str(e)}"
                log("ERROR", f"{error_msg}\nStacktrace:\n{traceback.format_exc()}")
                
                return jsonify({
                    "error": {
                        "type": "prompt_operation_error",
                        "message": error_msg
                    }
                }), 500
    
    def _register_serverless_run_handler(self):
        @self.bp.route("/serverless/run", methods=["POST"])
        def handle_serverless_run():
            """
            处理 /api/serverless/run 请求，支持同步和异步两种模式
            
            调用方式:
            - 默认: 异步调用（与 /api/prompt 处理一致）
            - Header X-Art-Invocation-Type: Sync 时: 同步调用，等待GPU返回结果
            
            异步模式:
            - 将请求转发到GPU函数（异步调用）
            - 返回任务ID，前端通过任务ID轮询获取结果
            - 使用任务队列跟踪任务状态
            
            同步模式:
            - 将请求转发到GPU函数（同步调用）
            - 等待GPU处理完成并返回结果
            - 直接返回结果给客户端
            """
            is_valid, error_response = self._check_backend_status()
            if not is_valid:
                return error_response
            
            try:
                gateway_service = CpuGatewayService()
                
                # 检查调用类型：Header X-Art-Invocation-Type: Sync 表示同步调用
                invocation_type = request.headers.get("X-Art-Invocation-Type", "").strip()
                is_sync = invocation_type.lower() == "sync"
                
                if is_sync:
                    log("DEBUG", f"Processing /serverless/run in SYNC mode (X-Art-Invocation-Type: Sync)")
                    return gateway_service.handle_serverless_run_sync()
                else:
                    log("DEBUG", f"Processing /serverless/run in ASYNC mode (default)")
                    return gateway_service.handle_serverless_run_async()
                    
            except Exception as e:
                error_msg = f"Failed to handle serverless run request: {str(e)}"
                log("ERROR", f"{error_msg}\nStacktrace:\n{traceback.format_exc()}")
                
                return jsonify({
                    "error": {
                        "type": "serverless_run_error",
                        "message": error_msg
                    }
                }), 500
    
    def _register_history_handler(self):
        @self.bp.route("/history", methods=["GET", "POST", "DELETE"])
        @self.bp.route("/history/<path:subpath>", methods=["GET", "POST", "DELETE"])
        def handle_history(subpath=""):
            is_valid, error_response = self._check_backend_status()
            if not is_valid:
                return error_response
            
            try:
                history_gateway = HistoryGatewayService()
                path = f"api/history/{subpath}" if subpath else "api/history"
                return history_gateway.handle_history_request(path)
            except Exception as e:
                error_msg = f"Failed to handle history request: {str(e)}"
                log("ERROR", f"{error_msg}\nStacktrace:\n{traceback.format_exc()}")
                
                return jsonify({
                    "error": {
                        "type": "history_operation_error",
                        "message": error_msg
                    }
                }), 500
    
    def _register_userdata_handler(self):
        """在 prod 模式下，阻止保存 userdata 文件"""
        @self.bp.route("/userdata/<path:file>", methods=["POST"])
        def block_userdata_save(file):
            log("WARN", f"Attempt to save userdata blocked in prod mode: {file}")
            return jsonify({
                "error": {
                    "type": "forbidden",
                    "message": "Saving workflow is disabled in prod mode"
                }
            }), 403
