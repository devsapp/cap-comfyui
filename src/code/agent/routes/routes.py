import logging
import threading
import requests
from flask import Flask, request, jsonify, Response
from flask_sock import Sock
import websocket
import constants
from services.comfyui_service import ComfyuiService, ComfyuiStatus
import traceback


class Routes:
    def __init__(self):
        self.app = Flask(__name__)
        self._sock = Sock(self.app)
        self._comfyui = ComfyuiService()
        self.setup_routes()

    def setup_routes(self):
        def _handle_exception(e):
            err_msg = traceback.format_exc()
            print(f"{str(e)}\nStacktrace:\n{err_msg}")
            return jsonify({
                "status": "failed",
                "message": f"{str(e)}\n{err_msg}"
            }), 500

        @self.app.route("/management/start", methods=["POST"])
        def start():
            # TODO: 异步
            try:
                self._comfyui.start()
                return jsonify({
                    "status": "success",
                    "message": "Successfully load snapshot and start comfyui process"
                }), 200
            except Exception as e:
                return _handle_exception(e)

        @self.app.route("/management/stop", methods=["POST"])
        def stop():
            try:
                self._comfyui.stop()
                return jsonify({
                    "status": "success",
                    "message": "Successfully shutdown comfyui process"
                }), 200
            except Exception as e:
                return _handle_exception(e)

        @self.app.route("/management/save", methods=["POST"])
        def save():
            # TODO: 异步
            try:
                self._comfyui.stop()
                return jsonify({
                    "status": "success",
                    "message": "Successfully save snapshot"
                }), 200
            except Exception as e:
                return _handle_exception(e)

        @self.app.route("/management/saveAndStop", methods=["POST"])
        def save_and_stop():
            # TODO: 异步
            try:
                self._comfyui.save_and_stop()
                return jsonify({
                    "status": "success",
                    "message": "Successfully save snapshot and stop comfyui process"
                }), 200
            except Exception as e:
                return _handle_exception(e)

        # TODO 检查文件内容有更新的接口

        @self.app.route("/management/status", methods=["GET"])
        def status():
            return jsonify({
                "data": self._comfyui.status.value,
                "status": "success"
            }), 200

        # @self._sock.route('/ws')
        # def websocket_tester(ws):
        #     while True:
        #         message = ws.receive()
        #         ws.send(f"Echo: {message}")

        @self._sock.route('/<path:path>')
        def comfyui_proxy_ws(ws, path):
            comfyui_status = self._comfyui.status
            if comfyui_status not in (ComfyuiStatus.RUNNING, ComfyuiStatus.SAVING):
                return jsonify({
                    "status": "failed",
                    "message": "Please start your comfyui service first"
                }), 500

            # print(f"Forwarding websocket request for path: {path}")
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
                return _handle_exception(e)
            finally:
                ws_client.close()

        @self.app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
        @self.app.route("/", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
        def comfyui_proxy(path=""):
            comfyui_status = self._comfyui.status
            if comfyui_status not in (ComfyuiStatus.RUNNING, ComfyuiStatus.SAVING):
                return jsonify({
                    "status": "failed",
                    "message": "Please start your comfyui service first"
                }), 500

            print(f"Forwarding request for path: {path}")
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
                return _handle_exception(e)
