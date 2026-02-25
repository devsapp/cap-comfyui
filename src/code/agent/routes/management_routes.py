from flask import Blueprint, Flask, request, jsonify

import constants
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
            """
            @deprecated 此接口已废弃，仅用于运维场景。
            服务在实例启动时会自动启动（通过 /initialize 钩子），无需手动调用。
            """
            # --- 步骤 1: 从 URL 查询参数获取 snapshot (向下兼容) ---
            snap = request.args.get('snapshot')

            # --- 步骤 2: 从请求体 (JSON) 获取可选的 nodes_map ---
            data = request.get_json(force=True, silent=True)  # 尝试获取JSON，如果请求体为空或非JSON，data会是None
            if isinstance(data, dict):
                # - 如果请求体是有效的JSON字典，则尝试获取 'nodes'。否则，置为哨兵值跳过依赖安装
                # 注意: "nodes": null时，nodes_map为None，表示全部安装
                nodes_map = data.get('nodes', self.service.SKIP_INSTALL_SENTINEL)
            else:
                # - 请求体为空、不是JSON、或者是JSON但不是字典(例如 "[]" 或 "null")时，跳过依赖安装。
                nodes_map = self.service.SKIP_INSTALL_SENTINEL

            # --- 步骤 3: 调用 service 方法 ---
            result_map = self.service.start(snap, nodes_map=nodes_map)
            return jsonify({
                "data": result_map,
                "status": "success",
                "message": "Successfully initiated backend start process."
            })

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
                    "sub_status": self.service.sub_status
                },
                "status": "success"
            }), 200

        @self.bp.get("/snapshot")
        def snapshot():
            return jsonify({
                "data": {
                    "snapshotName": self.service.cur_snapshot_name or "",
                },
                "status": "success"
            }), 200

        @self.bp.post('/install')
        def install():
            """
            安装自定义节点依赖的独立接口。
            请求体格式: {"nodes": {...}, "timeout": 300} 或 {"nodes": null} 或 空请求体
            - 不提供或 nodes: null -> 安装所有可用插件
            - nodes: {...} -> 按字典内容安装指定插件
            - timeout: 安装超时时间（秒），默认使用 constants.DEFAULT_INSTALL_TIMEOUT
            """
            # 从请求体获取 nodes_map 和 timeout
            data = request.get_json(force=True, silent=True)
            if isinstance(data, dict):
                nodes_map = data.get('nodes', None)  # 默认None表示安装所有
                timeout = data.get('timeout', constants.DEFAULT_INSTALL_TIMEOUT)    # 默认使用常量超时
            else:
                nodes_map = None  # 请求体为空或非JSON时，也表示安装所有
                timeout = constants.DEFAULT_INSTALL_TIMEOUT     # 默认超时时间

            try:
                result_map = self.service.install_custom_nodes(nodes_map=nodes_map, timeout=timeout)
                return jsonify({
                    "data": result_map,
                    "status": "success",
                    "message": "Successfully installed custom nodes dependencies."
                }), 200
            except Exception as e:
                return jsonify({
                    "status": "error",
                    "message": f"Failed to install dependencies: {str(e)}"
                }), 500

        @self.bp.post('/shutdown')
        def shutdown():
            print("Executing shutdown immediately...")
            import os
            os._exit(0)
