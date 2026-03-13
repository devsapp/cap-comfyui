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
            请求体格式:
            {
                "nodes": {...},       # 可选，null 或不提供 -> 安装所有可用插件；{...} -> 按字典内容安装指定插件
                "timeout": 300,       # 可选，安装超时时间（秒），默认使用 constants.DEFAULT_INSTALL_TIMEOUT
                "options": {
                    "custom_nodes_dirs": ["/path/to/custom_nodes", ...]  # 可选，指定插件父目录列表
                }
            }
            """
            data = request.get_json(force=True, silent=True)
            if isinstance(data, dict):
                nodes_map = data.get('nodes', None)
                timeout = data.get('timeout', constants.DEFAULT_INSTALL_TIMEOUT)
                options = data.get('options', {}) or {}
                custom_nodes_dirs = options.get('custom_nodes_dirs', None)
            else:
                nodes_map = None
                timeout = constants.DEFAULT_INSTALL_TIMEOUT
                custom_nodes_dirs = None

            try:
                result_map = self.service.install_custom_nodes(nodes_map=nodes_map, timeout=timeout, custom_nodes_dirs=custom_nodes_dirs)
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

        @self.bp.post('/clone')
        def clone():
            """
            Clone 自定义节点源码的独立接口。
            请求体格式:
            {
                "nodes": {...},           # 必填，非空字典
                "timeout": 300,           # 可选，全局超时秒数，默认 DEFAULT_INSTALL_TIMEOUT
                "conflict": "skip",       # 可选，"skip"（默认）或 "override"
                "options": {
                    "max_retries": 1,                              # 可选，单个插件 clone 失败后的最大重试次数
                    "clone_timeout": 30,                           # 可选，单次 clone 命令的超时秒数
                    "custom_nodes_dirs": ["/path/to/custom_nodes", ...]  # 可选，冲突检测的插件父目录列表
                }
            }
            """
            data = request.get_json(force=True, silent=True)
            if not isinstance(data, dict):
                return jsonify({"status": "error", "message": "Request body must be a JSON object."}), 400

            nodes_map = data.get('nodes')
            if not isinstance(nodes_map, dict):
                return jsonify({"status": "error", "message": "'nodes' is required and must be a non-null dict."}), 400

            timeout = data.get('timeout', constants.DEFAULT_INSTALL_TIMEOUT)
            conflict_strategy = data.get('conflict', 'skip')

            options = data.get('options') or {}
            max_retries = options.get('max_retries')
            clone_timeout = options.get('clone_timeout')
            custom_nodes_dirs = options.get('custom_nodes_dirs')

            try:
                result_map = self.service.clone_custom_nodes(
                    nodes_map=nodes_map,
                    timeout=timeout,
                    conflict_strategy=conflict_strategy,
                    max_retries=max_retries,
                    clone_timeout=clone_timeout,
                    custom_nodes_dirs=custom_nodes_dirs,
                )
                return jsonify({
                    "data": result_map,
                    "status": "success",
                    "message": "Successfully cloned custom nodes."
                }), 200
            except Exception as e:
                return jsonify({
                    "status": "error",
                    "message": f"Failed to clone custom nodes: {str(e)}"
                }), 500

        @self.bp.post('/shutdown')
        def shutdown():
            print("Executing shutdown immediately...")
            import os
            os._exit(0)
