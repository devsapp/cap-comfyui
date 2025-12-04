import json
import logging
import os
import threading
import traceback

from flask import Flask, jsonify, request, Response
from flask_sock import Sock
import requests

import constants
from exceptions.exceptions import CustomError
from services.management_service import ManagementService, Action, BackendStatus
from utils.logger import log
from .management_routes import ManagementRoutes
from .serverless_api_routes import ServerlessApiRoutes
from .cpu_routes import CpuRoutes
from services.serverlessapi.serverless_api_service import ServerlessApiService


class Routes:
    def __init__(self):
        self.app = Flask(__name__)
        self._sock = Sock(self.app)
        # 重启锁，防止并发重启
        self._reboot_lock = threading.Lock()
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

        if constants.COMFYUI_MODE == "cpu":
            cpu_router = CpuRoutes()
            cpu_router.register(self.app)

        @self.app.route("/api/manager/reboot", methods=["GET", "POST"])
        def manager_reboot():
            """
            拦截 ComfyUI-Manager 的 reboot 请求，使用管控接口实现重启
            支持从 CPU 函数触发：
            - X-FunArt-Snapshot-Name header: 指定要使用的 snapshot 名称
            - X-Forwarded-By header: 标识请求来源
            
            重启是异步的，立即返回响应，通过/management/status接口查询重启状态
            """
            # 检查是否已有重启在进行中
            if not self._reboot_lock.acquire(blocking=False):
                log("WARNING", "Reboot request rejected: reboot already in progress")
                return jsonify({
                    "status": "failed",
                    "message": "Reboot already in progress, please wait"
                }), 409
            
            # 优先从 header 中获取 snapshot 名称（CPU 函数传递）
            snapshot_from_header = request.headers.get(constants.HEADER_SNAPSHOT_NAME)
            forwarded_by = request.headers.get(constants.HEADER_FORWARDED_BY, 'Direct')
            
            service = ManagementService()
            current_snapshot = service.cur_snapshot_name or 'latest-dev'
            
            log("INFO", f"Intercepted /api/manager/reboot request from {forwarded_by}, current snapshot: {current_snapshot}")
            
            # 异步执行重启逻辑
            def do_reboot():
                try:
                    # 如果是 CPU 函数触发且指定了 snapshot，直接使用，不再保存
                    if snapshot_from_header:
                        log("INFO", f"Using snapshot from CPU function: {snapshot_from_header}")
                        snapshot_to_load = snapshot_from_header
                        skip_save = True
                    else:
                        snapshot_to_load = current_snapshot
                        skip_save = False

                    # Status:Rebooting detailStatus:Saving
                    # 若最近一次管控操作为Start 且未指定 snapshot，则在重启前保存工作空间
                    # TODO： 是否会影响pre-stop逻辑？
                    if not skip_save and service.latest_action and service.latest_action == Action.START:
                        try:
                            from services.workspace.snapshot_manager import SnapshotManager
                            log("INFO", "Saving workspace before reboot...")
                            result_map = service.save(SnapshotManager.TYPE_DEV)
                            log("INFO", f"Save result before reboot: {json.dumps(result_map, indent=2)}")
                            
                            # 使用新保存的 snapshot 名称
                            if 'snapshot' in result_map:
                                snapshot_to_load = result_map['snapshot']
                                log("INFO", f"Will restart with newly saved snapshot: {snapshot_to_load}")
                        except Exception as e:
                            log("WARNING", f"Failed to save workspace before reboot: {str(e)}")
                    else:
                        log("INFO", "Skip saving workspace (latest_action is not START)")
                    
                    # 停止服务
                    try:
                        service.stop()
                    except Exception as e:
                        log("WARNING", f"Error during stop: {e}")
                    
                    # 如果是 CPU 模式，异步触发 GPU 函数的重启
                    if constants.COMFYUI_MODE == 'cpu' and constants.GPU_FUNCTION_URL:
                        def trigger_gpu_reboot():
                            try:
                                gpu_reboot_url = f"{constants.GPU_FUNCTION_URL.rstrip('/')}/api/manager/reboot"
                                log("INFO", f"Triggering GPU function reboot: {gpu_reboot_url}")
                                
                                gpu_headers = {
                                    constants.HEADER_SNAPSHOT_NAME: snapshot_to_load,
                                    constants.HEADER_FORWARDED_BY: 'CPU-Reboot-Trigger',
                                    constants.HEADER_FC_INVOCATION_TYPE: 'Async'
                                }
                                
                                gpu_resp = requests.post(gpu_reboot_url, headers=gpu_headers, timeout=10)
                                log("INFO", f"GPU function reboot triggered: status={gpu_resp.status_code}")
                            except requests.exceptions.Timeout:
                                log("WARNING", "GPU function reboot request timed out (expected for async call)")
                            except Exception as e:
                                log("WARNING", f"Failed to trigger GPU function reboot: {str(e)}")
                        
                        # 触发 GPU 重启
                        threading.Thread(target=trigger_gpu_reboot, daemon=True).start()
                    
                    # 重新启动本地服务（不安装依赖），使用新保存的 snapshot
                    log("INFO", f"Restarting local service with snapshot: {snapshot_to_load}")
                    service.start(snapshot_to_load, nodes_map=service.SKIP_INSTALL_SENTINEL)
                    log("INFO", "Reboot completed successfully")
                    
                except Exception as e:
                    error_msg = f"Failed to restart ComfyUI: {str(e)}"
                    log("ERROR", f"{error_msg}\nStacktrace:\n{traceback.format_exc()}")
                finally:
                    # 释放重启锁
                    self._reboot_lock.release()
            
            # 在后台线程中执行重启
            threading.Thread(target=do_reboot, daemon=True).start()
            
            # 立即返回响应
            return jsonify({
                "status": "success",
                "message": "Reboot request accepted, restarting in background"
            }), 202
        
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
            # 若最近一次管控操作为Start，且实例非预期销毁时，需要在pre-stop中保存工作空间从而兜底;
            # 其他情况：例如按量实例并未启动服务子进程、例如已经使用SaveAndStop保存了工作空间再销毁实例，均不需要在pre-stop中再次保存
            if service.latest_action and service.latest_action == Action.START:
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
            backend_status = self.management.service.status
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
            log("ERROR", f"{str(e)}\nStacktrace:\n{err_msg}")

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
