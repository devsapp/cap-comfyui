import json
import logging
import os
import threading
import time
import traceback

from flask import Blueprint, Flask, jsonify, request, g
from flask_sock import Sock
import websocket

import constants
from services.management_service import ManagementService, BackendStatus
from utils.logger import log
from utils.error_handler import handle_exceptions, ErrorResponse
from services.gateway import get_task_manager
from services.gateway.handlers.queue_handler import QueueHandler
from services.gateway.handlers.prompt_handler import PromptHandler
from services.gateway.handlers.serverless_handler import ServerlessHandler
from services.gateway.handlers.history_handler import HistoryHandler
from services.gateway.handlers.interrupt_handler import InterruptHandler
from services.gateway.handlers.reboot_handler import RebootHandler
from services.gateway.handlers.task_status_handler import TaskStatusHandler
from services.gateway.handlers.userdata_handler import UserdataHandler
from services.gateway.handlers.ws_handler import WsHandler
from services.gateway.handlers.serverless_ws_handler import ServerlessWsHandler
from services.serverlessapi.serverless_api_service import ServerlessApiService
from utils.user_identity import set_user_identity_or_default


class GatewayRoutes:
    """Gateway路由"""
    
    def __init__(self):
        # HTTP 路由使用 /api 前缀
        self.bp = Blueprint("gateway_routes", __name__, url_prefix="/api")
        # WebSocket 路由使用根路径（保持 ComfyUI 兼容性）
        self.ws_bp = Blueprint("gateway_ws", __name__)
        self.service = ManagementService()  # 单例模式，直接创建实例
        self.sock = Sock()
        self.sock.bp = self.ws_bp  # 将 WebSocket 绑定到单独的 Blueprint
        
        # 初始化各个 handler
        self.reboot_handler = RebootHandler()

        task_manager = get_task_manager()

        self.queue_handler = QueueHandler(task_manager)
        self.prompt_handler = PromptHandler(task_manager)
        self.serverless_handler = ServerlessHandler()
        self.task_status_handler = TaskStatusHandler(ServerlessApiService())
        self.history_handler = HistoryHandler()
        self.interrupt_handler = InterruptHandler()
        self.userdata_handler = UserdataHandler()
        self.ws_handler = WsHandler()
        self.serverless_ws_handler = ServerlessWsHandler(constants.GPU_FUNCTION_URL)
        
        self.setup_routes()
    
    def register(self, app: Flask):
        app.register_blueprint(self.bp)
        app.register_blueprint(self.ws_bp)
    
    def setup_routes(self):
        """设置所有路由"""
        self._register_backend_status_middleware()
        self._register_user_identity_middleware()
        self._register_reboot_handler()
        
        # 只在 CPU 模式下注册这些路由
        if constants.COMFYUI_MODE == 'cpu':
            self._register_websocket()
            self._register_serverless_websocket()  # Serverless WebSocket 转发
            self._register_queue_handler()
            self._register_prompt_handler()
            self._register_serverless_run_handler()
            self._register_task_status_handler()
            self._register_history_handler()
            self._register_interrupt_handler()
            # 通过环境变量控制是否禁用工作流保存
            if constants.DISABLE_FLOW_SAVE:
                self._register_userdata_handler()
        else:
            # GPU 模式：注册通用 WebSocket 代理
            self._register_gpu_websocket_proxy()
    
    def _register_backend_status_middleware(self):
        """注册后端状态检查中间件，在每个请求前检查后端服务状态"""
        @self.bp.before_request
        def check_backend_status():
            """
            检查后端服务状态
            
            如果后端未运行，返回错误响应并阻止请求继续处理
            """
            backend_status = self.service.status
            if backend_status not in (BackendStatus.RUNNING, BackendStatus.SAVING):
                return ErrorResponse.create(
                    error_type="service_not_running",
                    message="Please start your comfyui/sd service first",
                    status_code=500
                )
    
    def _register_user_identity_middleware(self):
        """注册用户身份识别中间件，在每个请求前识别用户"""
        @self.bp.before_request
        def identify_user():
            set_user_identity_or_default()
    
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
            self.ws_handler.handle_connection(ws)
    
    def _register_gpu_websocket_proxy(self):
        @self.sock.route('/<path:path>')
        def proxy_ws(ws, path):
            """
            GPU 模式下的通用 WebSocket 代理
            将所有 WebSocket 请求转发到后端 ComfyUI 服务 (127.0.0.1:8188)
            """
            # 检查后端服务状态（middleware 不对 WebSocket Blueprint 生效，需要手动检查）
            backend_status = self.service.status
            if backend_status not in (BackendStatus.RUNNING, BackendStatus.SAVING):
                return jsonify({
                    "status": "failed",
                    "message": "Please start your comfyui/sd service first"
                }), 500
            
            # 构造目标 WebSocket URL
            target_url = f"ws://{constants.APP_HOST}/{path}"
            query_string = request.query_string.decode('utf-8')
            if query_string:
                target_url += f"?{query_string}"
            
            log("INFO", f"Forwarding WebSocket: /{path} -> {target_url}")
            
            def on_message(_, message):
                try:
                    ws.send(message)
                except Exception as ex:
                    log("ERROR", f"Error sending message to client: {ex}")
            
            def on_error(_, error):
                log("ERROR", f"WebSocket client error: {error}")
            
            def on_close(_, close_status_code, close_msg):
                log("INFO", f"WebSocket connection closed: {close_status_code} - {close_msg}")
            
            ws_client = websocket.WebSocketApp(
                target_url,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )
            
            ws_thread = threading.Thread(target=ws_client.run_forever)
            ws_thread.daemon = True
            ws_thread.start()
            
            from services.process.websocket.websocket_manager import ws_manager
            
            try:
                ws_manager.add_connection(ws)
                while True:
                    message = ws.receive()
                    ws_client.send(message)
            except Exception as e:
                log("INFO", f"WebSocket event: {e}")
            finally:
                ws_manager.remove_connection(ws)
                ws_client.close()
    
    def _register_serverless_websocket(self):
        @self.sock.route("/api/serverless/ws")
        def serverless_ws(ws):
            """
            Serverless WebSocket 接口（CPU模式下转发到GPU）
            
            接收客户端的 WebSocket 连接，转发 prompt 到 GPU 函数，
            并将 GPU 的响应实时转发回客户端
            """
            self.serverless_ws_handler.handle_connection(ws)
    
    def _register_queue_handler(self):
        @self.bp.route("/queue", methods=["GET", "POST"])
        @handle_exceptions(error_type="queue_operation_error", log_prefix="Queue")
        def handle_queue():
            if request.method == "GET":
                return self.queue_handler.handle_get_request()
            elif request.method == "POST":
                return self.queue_handler.handle_post_request()
            else:
                return ErrorResponse.create(
                    error_type="method_not_allowed",
                    message=f"Method {request.method} not allowed",
                    status_code=405
                )
    
    def _register_prompt_handler(self):
        @self.bp.route("/prompt", methods=["POST"])
        @handle_exceptions(error_type="prompt_operation_error", log_prefix="Prompt")
        def handle_prompt():
            return self.prompt_handler.handle_post_request()
    
    def _register_serverless_run_handler(self):
        @self.bp.route("/serverless/run", methods=["POST"])
        @handle_exceptions(error_type="serverless_run_error", log_prefix="ServerlessRun")
        def handle_serverless_run():
            """
            处理 /api/serverless/run 请求
            
            支持两种模式：
            - 同步模式（默认）：等待GPU处理完成，直接返回结果
            - 异步模式（X-Fc-Invocation-Type: Async）：立即返回任务ID，前端通过任务ID轮询获取结果
            
            通过请求头 X-Fc-Invocation-Type 控制：
            - 不传或传其他值：同步模式
            - X-Fc-Invocation-Type: Async：异步模式
            """
            return self.serverless_handler.handle_post_request()
    
    def _register_task_status_handler(self):
        @self.bp.get("/serverless/task/<task_id>")
        def get_task(task_id):
            return self.task_status_handler.handle_get_task(task_id)

        @self.bp.get("/serverless/tasks")
        def list_tasks():
            return self.task_status_handler.handle_list_tasks()

    def _register_history_handler(self):
        @self.bp.route("/history", methods=["GET", "POST"])
        @handle_exceptions(error_type="history_operation_error", log_prefix="History")
        def handle_history():
            if request.method == "GET":
                return self.history_handler.handle_get_request()
            return self.history_handler.handle_post_request()
    
    def _register_interrupt_handler(self):
        @self.bp.route("/interrupt", methods=["POST"])
        @handle_exceptions(error_type="interrupt_operation_error", log_prefix="Interrupt")
        def handle_interrupt():
            return self.interrupt_handler.handle_post()
    
    def _register_reboot_handler(self):
        @self.bp.route("/manager/reboot", methods=["GET", "POST"])
        @handle_exceptions(error_type="reboot_operation_error", log_prefix="Reboot")
        def handle_reboot():
            """处理服务重启请求"""
            return self.reboot_handler.handle_reboot()
    
    def _register_userdata_handler(self):
        @self.bp.route("/userdata/workflows/<path:filename>", methods=["POST"])
        def block_workflow_save(filename):
            # 只拦截 workflows 目录下的 JSON 文件（workflow 文件）
            if filename.endswith(".json"):
                return self.userdata_handler.handle_post_request(f"workflows/{filename}")
            
            # 非 JSON 文件返回 404（不应该发生）
            return ErrorResponse.create(
                error_type="not_found",
                message="Only JSON workflow files are handled here",
                status_code=404
            )

