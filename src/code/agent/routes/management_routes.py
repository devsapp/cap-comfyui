import threading

from flask import Blueprint, Flask, request, jsonify

from services.management_service import ManagementService


class ManagementRoutes:

    def __init__(self):
        self.bp = Blueprint("management", __name__, url_prefix="/management")
        self.service = ManagementService()
        self.setup_routes()

    def register(self, app: Flask):
        app.register_blueprint(self.bp)

    # TODO: Runfunction -> /initialize & /management/* 配置http trigger匿名访问，防止拿到域名的人管控实例
    def setup_routes(self):

        @self.bp.post("/start")
        def start():
            snapshot = request.args.get('snapshot')
            result_map = self.service.start(snapshot)
            return jsonify({
                "data": result_map,
                "status": "success",
                "message": "Successfully load snapshot and start backend process"
            }), 200

        @self.bp.post("/stop")
        def stop():
            result_map = self.service.stop()
            return jsonify({
                "data": result_map,
                "status": "success",
                "message": "Successfully shutdown backend process"
            }), 200

        @self.bp.post("/save")
        def save():
            snapshot_type = request.args.get('type')
            result_map = self.service.save(snapshot_type)
            return jsonify({
                "data": result_map,
                "status": "success",
                "message": "Successfully save snapshot"
            }), 200

        @self.bp.post("/saveAndStop")
        def save_and_stop():
            snapshot_type = request.args.get('type')
            result_map = self.service.save_and_stop(snapshot_type)
            return jsonify({
                "data": result_map,
                "status": "success",
                "message": "Successfully save snapshot and stop backend process"
            }), 200

        # TODO 检查文件内容有更新的接口

        @self.bp.get("/status")
        def status():
            return jsonify({
                "data": {
                    "status": self.service.status.value,
                    "latest_action": getattr(self.service.latest_action, 'value', None),
                },
                "status": "success"
            }), 200

        @self.bp.get("/snapshots")
        def snapshots():
            return jsonify({
                "data": self.service.find_snapshots(),
                "status": "success"
            }), 200

        @self.bp.post('/shutdown')
        def shutdown():
            threading.Thread(target=self.service.shutdown).start()
            return jsonify({
                "message": "Tried to exit the main process",
                "status": "success"
            }), 200
