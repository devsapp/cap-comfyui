import json
import logging
import os
import traceback

from flask import Flask, jsonify, request
from flask_sock import Sock

import constants
from exceptions.exceptions import CustomError
from services.management_service import ManagementService, Action, BackendStatus
from utils.logger import log
from utils.error_handler import ErrorResponse
from .proxy_util import proxy_to_comfyui
from .management_routes import ManagementRoutes
from .serverless_api_routes import ServerlessApiRoutes
from .gateway_routes import GatewayRoutes
from services.serverlessapi.serverless_api_service import ServerlessApiService


class Routes:
    def __init__(self):
        self.app = Flask(__name__)
        self._sock = Sock(self.app)
        self.setup_routes()
        # 设置 Werkzeug 日志级别为 ERROR，只显示错误日志，不输出每个请求
        logging.getLogger('werkzeug').setLevel(logging.ERROR)
    

    def setup_routes(self):
        # 管控API
        self.management = ManagementRoutes()
        self.management.register(self.app)

        # ServerlessAPI
        if constants.BACKEND_TYPE == constants.TYPE_COMFYUI:
            serverless_api = ServerlessApiRoutes()
            serverless_api.register(self.app)

        # Gateway routes (CPU 模式需要全部路由，GPU 模式也需要 reboot 路由)
        gateway_router = GatewayRoutes()
        gateway_router.register(self.app)
        
        @self.app.route("/initialize", methods=["POST"])
        def initialize():
            # See FC docs for all the HTTP headers: https://www.alibabacloud.com/help/doc-detail/132044.htm#common-headers
            request_id = request.headers.get("x-fc-request-id", "")
            log("INFO", f"FC Initialize Start RequestId: {request_id}")

            # Use the following code to get temporary credentials
            # access_key_id = request.headers['x-fc-access-key-id']
            # access_key_secret = request.headers['x-fc-access-key-secret']
            # access_security_token = request.headers['x-fc-security-token']

            # API模式需要自动启动comfyui进程
            # TODO 防止抛出5xx导致函数计算一直重试产生大量费用
            service = ManagementService()
            
            # 使用环境变量指定的snapshot，默认为latest-dev
            snapshot_name = os.environ.get('AUTO_LAUNCH_SNAPSHOT_NAME', 'latest-dev')
            log("INFO", f"Initializing function with ComfyUI mode: {constants.COMFYUI_MODE}, snapshot: {snapshot_name}")
            service.start(snapshot_name, nodes_map={})

            if (
                constants.PREWARM_PROMPT
                and constants.BACKEND_TYPE == constants.TYPE_COMFYUI
                and constants.COMFYUI_MODE == "gpu"
            ):
                try:
                    log("INFO", "prewarm models")
                    prompt = json.loads(constants.PREWARM_PROMPT)
                    api = ServerlessApiService()
                    api.run(prompt)
                    api.api_clear_history()
                    log("INFO", "prewarm models done")
                except Exception as e:
                    log("ERROR", f"prewarm models got exception:\n{e}")

            log("INFO", f"FC Initialize End RequestId: {request_id}")
            return "Function is initialized, request_id: " + request_id + "\n"

        @self.app.route("/pre-stop", methods=["GET"])
        def pre_stop():
            request_id = request.headers.get("x-fc-request-id", "")
            log("INFO", f"FC PreStop Start RequestId: {request_id}")

            service = ManagementService()  # singleton
            # 若最近一次管控操作为Start或Reboot，且实例非预期销毁时，需要在pre-stop中保存工作空间从而兜底;
            # 其他情况：例如按量实例并未启动服务子进程、例如已经使用SaveAndStop保存了工作空间再销毁实例，均不需要在pre-stop中再次保存
            if service.latest_action and service.latest_action in (Action.START, Action.REBOOT):
                try:
                    from services.workspace.snapshot_manager import SnapshotManager
                    result_map = service.save(SnapshotManager.TYPE_DEV)
                    log("INFO", f"save resp when preStop: {json.dumps(result_map, indent=2)}")
                except Exception as e:
                    log("ERROR", f"error occur when preStop: {str(e)}")
            else:
                log("INFO", "Do nothing in pre-stop")
            log("INFO", f"FC PreStop End RequestId: {request_id}")
            return "OK"

        @self.app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
        @self.app.route("/", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
        def proxy(path=""):
            # issue: https://teambition.alibaba-inc.com/task/67c96194e6efb1c42a7ee904
            # 使用 RAW_URI 保持原始请求路径
            return proxy_to_comfyui(
                uri=request.environ.get('RAW_URI', request.path),
                check_status=True,
                timeout=30,
                log_prefix="RoutesProxy",
                service=self.management.service
            )

        @self.app.errorhandler(Exception)
        def handle_all_errors(error):
            """
            全局异常处理器
            捕获所有未被路由装饰器处理的异常
            """
            log("ERROR", f"Unhandled exception: {str(error)}\nStacktrace:\n{traceback.format_exc()}")
            
            if isinstance(error, CustomError):
                # 自定义异常：使用定义的错误码和消息
                return ErrorResponse.create(
                    error_type="custom_error",
                    message=error.message,
                    status_code=error.code
                )
            else:
                # 未预期的异常
                return ErrorResponse.create(
                    error_type="internal_error",
                    message=str(error),
                    status_code=500
                )
