import logging
import threading
import traceback

import requests
import websocket
from flask import Flask, request, jsonify, Response
from flask_sock import Sock

import constants
from exceptions.exceptions import CustomError
from services.comfyui_service import ComfyuiStatus, ComfyuiService
from .management_routes import ManagementRoutes
from .serverless_api_routes import ServerlessApiRoutes


class Routes:
    def __init__(self):
        self.app = Flask(__name__)
        self._sock = Sock(self.app)
        self.setup_routes()

    def setup_routes(self):

        management = ManagementRoutes()
        management.register(self.app)
        
        serverless_api = ServerlessApiRoutes()
        serverless_api.register(self.app)

        @self.app.route("/initialize", methods=["POST"])
        def initialize():
            # See FC docs for all the HTTP headers: https://www.alibabacloud.com/help/doc-detail/132044.htm#common-headers
            request_id = request.headers.get("x-fc-request-id", "")
            print("FC Initialize Start RequestId: " + request_id)

            # Use the following code to get temporary credentials
            # access_key_id = request.headers['x-fc-access-key-id']
            # access_key_secret = request.headers['x-fc-access-key-secret']
            # access_security_token = request.headers['x-fc-security-token']

            # API模式需要自动启动comfyui进程
            # TODO 防止抛出5xx导致函数计算一直重试产生大量费用
            service = ComfyuiService()
            service.start(constants.AUTO_LAUNCH_SNAPSHOT_NAME)

            print("FC Initialize End RequestId: " + request_id)
            return "Function is initialized, request_id: " + request_id + "\n"

        @self._sock.route('/<path:path>')
        def comfyui_proxy_ws(ws, path):
            comfyui_status = management.service.status
            if comfyui_status not in (ComfyuiStatus.RUNNING, ComfyuiStatus.SAVING):
                return jsonify({
                    "status": "failed",
                    "message": "Please start your comfyui service first"
                }), 500

            # print(f"Forwarding websocket request for path: {path}")
            target_url = f"ws://{constants.APP_HOST}/{path}"

            def on_message(_, message):
                try:
                    ws.send(message)
                except Exception as ex:
                    logging.error(f"Error sending message to client: {ex}")

            def on_error(_, error):
                logging.error(f"WebSocket client error: {error}")

            def on_close(_, close_status_code, close_msg):
                logging.info(f"WebSocket connection closed: {close_status_code} - {close_msg}")

            ws_client = websocket.WebSocketApp(
                target_url,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )

            ws_thread = threading.Thread(target=ws_client.run_forever)
            ws_thread.daemon = True
            ws_thread.start()

            try:
                while True:
                    message = ws.receive()
                    ws_client.send(message)
            finally:
                ws_client.close()

        @self.app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
        @self.app.route("/", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
        def comfyui_proxy(path=""):
            comfyui_status = management.service.status
            if comfyui_status not in (ComfyuiStatus.RUNNING, ComfyuiStatus.SAVING):
                return jsonify({
                    "status": "failed",
                    "message": "Please start your comfyui service first"
                }), 500

            # print(f"Forwarding request for path: {path}")
            target_url = f"http://{constants.APP_HOST}/{path}"

            # 转发请求头
            headers = {key: value for key, value in request.headers}

            # 转发请求到目标服务器
            resp = requests.request(
                method=request.method,
                url=target_url,
                headers=headers,
                data=request.get_data(),
                cookies=request.cookies,
                params=request.args,
                allow_redirects=False,
                stream=True
            )

            proxy_response = Response(
                resp.content,
                status=resp.status_code,
                headers=dict(resp.headers)
            )
            # print(f"Forward request success, status code: {resp.status_code}")
            return proxy_response

        @self.app.errorhandler(Exception)
        def handle_all_errors(error):
            return _handle_exception(error)

        @self.app.errorhandler(CustomError)
        def handle_base_error(error):
            return _handle_exception(error)

        def _handle_exception(e):
            err_msg = traceback.format_exc()
            print(f"{str(e)}\nStacktrace:\n{err_msg}")

            if isinstance(e, CustomError):
                # 处理自定义异常
                return jsonify({
                    "status": "failed",
                    "message": str(e)
                }), e.code
            else:
                # 处理其他非预期的异常
                return jsonify({
                    "status": "failed",
                    "message": str(e)
                }), 500
