import logging
import threading
import requests
from flask import Flask, request, jsonify, Response
from flask_sock import Sock
import websocket
import constants
from services import apis


class Routes:
    def __init__(self):
        self.app = Flask(__name__)
        self._sock = Sock(self.app)
        self.setup_routes()

    def setup_routes(self):
        """设置所有路由"""

        @self.app.route("/initialize", methods=["POST"])
        def initialize():
            # See FC docs for all the HTTP headers: https://www.alibabacloud.com/help/doc-detail/132044.htm#common-headers
            request_id = request.headers.get("x-fc-request-id", "")
            print("FC Initialize Start RequestId: " + request_id)

            # do your things
            # Use the following code to get temporary credentials
            # access_key_id = request.headers['x-fc-access-key-id']
            # access_key_secret = request.headers['x-fc-access-key-secret']
            # access_security_token = request.headers['x-fc-security-token']

            print("FC Initialize End RequestId: " + request_id)
            return "Function is initialized, request_id: " + request_id + "\n"

        @self.app.route("/invoke", methods=["POST"])
        def invoke():
            # See FC docs for all the HTTP headers: https://www.alibabacloud.com/help/doc-detail/132044.htm#common-headers
            request_id = request.headers.get("x-fc-request-id", "")
            print("FC Invoke Start RequestId: " + request_id)

            print("hello world！")
            # Get function input, data type is bytes, convert as needed
            # event = request.get_data()
            # event_str = event.decode("utf-8")

            # Use the following code to get temporary STS credentials to access Alibaba Cloud services
            # access_key_id = request.headers['x-fc-access-key-id']
            # access_key_secret = request.headers['x-fc-access-key-secret']
            # access_security_token = request.headers['x-fc-security-token']

            print("FC Invoke End RequestId: " + request_id)
            return "hello world!"

        @self.app.route("/management/start", methods=["POST"])
        def start():
            # TODO: 异步 + 服务状态
            apis.start()
            return jsonify({
                "status": "success",
                "message": "start"
            }), 200

        @self.app.route("/management/stop", methods=["POST"])
        def stop():
            print("stop")
            return jsonify({
                "status": "success",
                "message": "stop"
            }), 200

        @self.app.route("/management/save", methods=["POST"])
        def save():
            # TODO: 异步 + 上传状态
            apis.save()
            return jsonify({
                "status": "success",
                "message": "save"
            }), 200

        @self.app.route("/management/status", methods=["GET"])
        def status():
            print("status")
            return jsonify({
                "status": "success",
                "message": "status"
            }), 200

        # @self._sock.route('/ws')
        # def websocket_tester(ws):
        #     while True:
        #         message = ws.receive()
        #         ws.send(f"Echo: {message}")

        @self._sock.route('/<path:path>')
        def comfyui_proxy_ws(ws, path):
            print(f"Forwarding websocket request for path: {path}")
            target_url = f"ws://{constants.COMFYUI_HOST}/{path}"

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
            except Exception as e:
                print(f"WebSocket proxy error: {e}")
            finally:
                ws_client.close()

        @self.app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
        @self.app.route("/", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
        def comfyui_proxy(path=""):
            print(f"Forwarding request for path: {path}")
            return _forward_requests(path)

        @self.app.errorhandler(Exception)
        def handle_error(error):
            logging.error(f"Unexpected error: {str(error)}")
            return jsonify({
                "status": "error",
                "message": "Internal server error"
            }), 500


def _forward_requests(path):
    """处理所有请求的代理转发"""
    target_url = f"http://{constants.COMFYUI_HOST}/{path}"

    # 转发请求头
    headers = {key: value for key, value in request.headers}

    # 处理请求
    try:
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
        print(f"Forward request success, status code: {resp.status_code}")
        return proxy_response

    except requests.RequestException as e:
        print(f"Forward request failed, reason: {type(e).__name__} {str(e)}")
        return {'error': str(e)}, 200
