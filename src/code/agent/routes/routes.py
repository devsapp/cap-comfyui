import logging
from flask import Flask, request, jsonify
from services import apis


class Routes:
    def __init__(self):
        self._app = None
        self._app = self.get_app()

    def get_app(self):
        if self._app is None:
            self._app = Flask(__name__)
            self.setup_routes()
        return self._app

    def setup_routes(self):
        """设置所有路由"""

        @self._app.route("/initialize", methods=["POST"])
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

        @self._app.route("/invoke", methods=["POST"])
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

        @self._app.route("/management/start", methods=["POST"])
        def start():
            # TODO: 异步 + 服务状态
            apis.start()
            return jsonify({
                "status": "success",
                "message": "start"
            }), 200

        @self._app.route("/management/stop", methods=["POST"])
        def stop():
            print("stop")
            return jsonify({
                "status": "success",
                "message": "stop"
            }), 200

        @self._app.route("/management/save", methods=["POST"])
        def save():
            # TODO: 异步 + 上传状态
            apis.save()
            return jsonify({
                "status": "success",
                "message": "save"
            }), 200

        @self._app.route("/management/status", methods=["GET"])
        def status():
            print("status")
            return jsonify({
                "status": "success",
                "message": "status"
            }), 200

        @self._app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
        @self._app.route("/", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
        def catch_all(path=""):
            print(f"Redirecting request for path: {path}")
            return "", 200

        @self._app.errorhandler(Exception)
        def handle_error(error):
            logging.error(f"Unexpected error: {str(error)}")
            return jsonify({
                "status": "error",
                "message": "Internal server error"
            }), 500
