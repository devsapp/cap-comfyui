import json
import logging
import threading
import traceback

import requests
import websocket
from flask import Flask, request, jsonify, Response
from flask_sock import Sock

import constants
from exceptions.exceptions import CustomError
from services.management_service import BackendStatus, ManagementService, Action
from .management_routes import ManagementRoutes
from .serverless_api_routes import ServerlessApiRoutes
from services.serverlessapi.serverless_api_service import ServerlessApiService


class Routes:
    def __init__(self):
        self.app = Flask(__name__)
        self._sock = Sock(self.app)
        self.setup_routes()
        import logging
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR)

    def setup_routes(self):

        management = ManagementRoutes()
        management.register(self.app)

        if constants.BACKEND_TYPE == constants.TYPE_COMFYUI:
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
            service = ManagementService()
            service.start(constants.AUTO_LAUNCH_SNAPSHOT_NAME)

            if (
                constants.PREWARM_PROMPT
                and constants.BACKEND_TYPE == constants.TYPE_COMFYUI
            ):
                try:
                    print("prewarm models")
                    prompt = json.loads(constants.PREWARM_PROMPT)
                    api = ServerlessApiService()
                    api.run(prompt)
                    api.api_clear_history()
                    print("prewarm models done")
                except Exception as e:
                    print(f"prewarm models got exception:\n{e}")

            print("FC Initialize End RequestId: " + request_id)
            return "Function is initialized, request_id: " + request_id + "\n"

        @self.app.route("/pre-stop", methods=["GET"])
        def pre_stop():
            request_id = request.headers.get("x-fc-request-id", "")
            print("FC PreStop Start RequestId: " + request_id)

            service = ManagementService()  # singleton
            # 若最近一次管控操作为Start，且实例非预期销毁时，需要在pre-stop中保存工作空间从而兜底;
            # 其他情况：例如按量实例并未启动服务子进程、例如已经使用SaveAndStop保存了工作空间再销毁实例，均不需要在pre-stop中再次保存
            if service.latest_action and service.latest_action == Action.START:
                try:
                    from services.workspace.snapshot_manager import SnapshotManager
                    result_map = service.save(SnapshotManager.TYPE_DEV)
                    print(f"save resp when preStop: {json.dumps(result_map, indent=2)}")
                except Exception as e:
                    print(f"error occur when preStop: {str(e)}")
            else:
                print("Do nothing in pre-stop")
            print("FC PreStop End RequestId: " + request_id)
            return "OK"

        @self._sock.route('/<path:path>')
        def proxy_ws(ws, path):
            backend_status = management.service.status
            if backend_status not in (BackendStatus.RUNNING, BackendStatus.SAVING):
                return jsonify({
                    "status": "failed",
                    "message": "Please start your comfyui/sd service first"
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

            from services.process.websocket.websocket_manager import ws_manager
            try:
                ws_manager.add_connection(ws)
                while True:
                    message = ws.receive()
                    ws_client.send(message)
            except Exception as e:
                print(f"ws event occurs: {e}")
            finally:
                ws_manager.remove_connection(ws)
                ws_client.close()

        @self.app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
        @self.app.route("/", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
        def proxy(path=""):
            backend_status = management.service.status
            if backend_status not in (BackendStatus.RUNNING, BackendStatus.SAVING):
                return jsonify({
                    "status": "failed",
                    "message": "Please start your comfyui/sd service first"
                }), 500

            # issue: https://teambition.alibaba-inc.com/task/67c96194e6efb1c42a7ee904
            original_uri = request.environ['RAW_URI']
            target_url = f"http://{constants.APP_HOST}{original_uri}"
            # print(f"Forwarding http request to path: {target_url}")

            resp = requests.request(
                method=request.method,
                url=target_url,
                headers=dict(request.headers),
                params=request.args,
                data=request.get_data(),
                cookies=request.cookies,
                allow_redirects=False,
                verify=False  # 如果需要验证SSL证书，将其设置为True
            )

            # issue: 实际内容被requests库解码，若保留content-encoding，可能会导致客户端试图重复解码，导致浏览器渲染SD页面失败
            excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
            response_headers = {}
            for name, value in resp.headers.items():
                if name.lower() not in excluded_headers:
                    response_headers[name] = value

            return Response(
                response=resp.content,
                status=resp.status_code,
                headers=response_headers
            )

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
