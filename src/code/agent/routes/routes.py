import json
import logging
import os
import threading
import traceback

from flask import Flask, jsonify, request, Response, g
from flask_sock import Sock
import requests

import constants
from exceptions.exceptions import CustomError
from services.management_service import ManagementService, BackendStatus
from utils.logger import log
from utils.error_handler import ErrorResponse
from utils.user_identity import identify_user_or_default
from .management_routes import ManagementRoutes
from .serverless_api_routes import ServerlessApiRoutes
from .gateway_routes import GatewayRoutes
from services.serverlessapi.serverless_api_service import ServerlessApiService


def _start_cleanup_thread(clean_archived: bool, timeout: int = 300):
    if constants.COMFYUI_MODE != "cpu":
        return None
    from services.cleanup import OutputFileCleanupService
    cleanup_service = OutputFileCleanupService()

    cleanup_thread = threading.Thread(
        target=cleanup_service.cleanup,
        args=(clean_archived, timeout),
        daemon=True
    )

    cleanup_thread.start()
    return cleanup_thread


def _wait_cleanup_thread(cleanup_thread, timeout: int = 300):
    if cleanup_thread:
        cleanup_thread.join(timeout=timeout + 10)  # 等待最多timeout+10秒


def parse_auto_install_nodes(raw):
    """
    将 AUTO_INSTALL_NODES 原始字符串解析为 start() 所需的 nodes_map。
    "*" → None（安装所有）；非空 JSON dict → dict；其他 → SKIP_INSTALL_SENTINEL（跳过安装）
    """
    raw = (raw or '').strip()
    if raw == '*':
        return None
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and parsed:
                return parsed
        except (json.JSONDecodeError, TypeError):
            log("WARNING", f"AUTO_INSTALL_NODES is not valid JSON, skipping node installation: {raw!r}")
    return constants.SKIP_INSTALL_SENTINEL


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

            # 执行文件清理：只清理 serverless_api（在返回前等待完成，超时5分钟）
            cleanup_thread = _start_cleanup_thread(clean_archived=False, timeout=300)

            # API模式需要自动启动comfyui进程
            # TODO 防止抛出5xx导致函数计算一直重试产生大量费用
            service = ManagementService()
            
            # 使用环境变量指定的snapshot，默认为latest-dev
            snapshot_name = constants.AUTO_LAUNCH_SNAPSHOT_NAME
            nodes_map = parse_auto_install_nodes(constants.AUTO_INSTALL_NODES)
            install_desc = 'all' if nodes_map is None else f'{len(nodes_map)} node(s)' if isinstance(nodes_map, dict) else 'skip'
            log("INFO", f"Initializing function with ComfyUI mode: {constants.COMFYUI_MODE}, snapshot: {snapshot_name}, install_nodes: {install_desc}")
            service.start(snapshot_name, nodes_map=nodes_map)

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

            # 等待清理线程完成
            _wait_cleanup_thread(cleanup_thread, timeout=300)

            log("INFO", f"FC Initialize End RequestId: {request_id}")
            return "Function is initialized, request_id: " + request_id + "\n"

        @self.app.route("/pre-stop", methods=["GET"])
        def pre_stop():
            request_id = request.headers.get("x-fc-request-id", "")
            log("INFO", f"FC PreStop Start RequestId: {request_id}")

            # 执行文件清理：清理 serverless_api 和 serverless_api_archived（在返回前等待完成，超时5分钟）
            # cleanup_thread = _start_cleanup_thread(clean_archived=True, timeout=300)

            service = ManagementService()  # singleton

            # PreStop 兜底保存策略：只在非预期实例销毁时保存
            # 如果已主动调用 stop 或 saveAndStop，则跳过保存
            if service._is_stopped:
                log("INFO", "Skip pre-stop save: service already stopped by user")
                log("INFO", f"FC PreStop End RequestId: {request_id}")
                return "OK"

            # 只有在 RUNNING 状态下才需要在 pre-stop 中保存工作空间
            # 其他状态不保存：
            # - SAVING: 已经在保存中
            # - REBOOTING: 正在重启中
            # - REBOOT_FAILED: 重启失败，无法保存
            if service.status != BackendStatus.RUNNING:
                log("INFO", f"Skip pre-stop save, current status: {service.status.value}")
                log("INFO", f"FC PreStop End RequestId: {request_id}")
                return "OK"

            # 避免fallback ECS产生的短命实例PreStop中保存dev快照
            # issue: https://project.aone.alibaba-inc.com/v2/project/2148315/bug/78756665#
            import time
            uptime = time.time() - service._init_time
            if uptime < constants.PRESTOP_MIN_UPTIME:
                log("INFO", f"Skip pre-stop save: instance uptime too short ({uptime:.0f}s < {constants.PRESTOP_MIN_UPTIME}s)")
                log("INFO", f"FC PreStop End RequestId: {request_id}")
                return "OK"

            def do_save(result_queue, target_snapshot_name):
                """在子进程中执行 save 操作"""
                try:
                    from services.workspace.snapshot_manager import SnapshotManager

                    mgr = SnapshotManager()
                    # 使用主进程预生成的 snapshot_name
                    result_map = mgr.save(SnapshotManager.TYPE_DEV, snapshot_name=target_snapshot_name)

                    result_queue.put({"success": True, "result": result_map})
                except Exception as e:
                    import traceback
                    result_queue.put({"success": False, "error": str(e), "traceback": traceback.format_exc()})

            # 启动子进程完成工作站生图环境保存，并在PreStop超时时间到达前进行不完整目录清理
            import multiprocessing
            from datetime import datetime
            from services.workspace.snapshot_manager import SnapshotManager
            snapshot_mgr = SnapshotManager()
            snapshot_name_suffix = datetime.utcnow().strftime(constants.SNAPSHOT_PATTERN)
            snapshot_name = f"{SnapshotManager.TYPE_DEV}-{snapshot_name_suffix}"
            result_queue = multiprocessing.Queue()
            save_process = multiprocessing.Process(target=do_save, args=(result_queue, snapshot_name))

            try:
                save_process.start()
                log("INFO", f"Started save process with PID: {save_process.pid}, snapshot: {snapshot_name}")

                # 等待进程完成或超时
                save_process.join(timeout=constants.PRESTOP_TIMEOUT)

                if save_process.is_alive():
                    # 超时：强制终止进程（子进程没有 SIGTERM 处理逻辑，直接 SIGKILL）
                    log("WARNING", f"preStop save timeout after {constants.PRESTOP_TIMEOUT}s, killing process {save_process.pid}...")
                    save_process.kill()
                    save_process.join(timeout=5)

                    log("INFO", f"Save process killed, cleaning up incomplete save...")
                    # 进程终止后清理未完成的保存，传入预生成的 snapshot_name
                    snapshot_mgr.cleanup_incomplete_save(snapshot_name)
                    log("INFO", "preStop cleanup completed due to timeout")
                else:
                    # 进程正常结束，检查结果
                    try:
                        result = result_queue.get_nowait()
                        if result.get("success"):
                            log("INFO", f"save resp when preStop: {json.dumps(result.get('result'), indent=2)}")
                        else:
                            log("ERROR", f"error occur when preStop: {result.get('error')}")
                            if result.get("traceback"):
                                log("ERROR", f"traceback: {result.get('traceback')}")
                            snapshot_mgr.cleanup_incomplete_save(snapshot_name)
                    except Exception:
                        log("WARNING", "Could not get result from save process")
            except Exception as e:
                log("ERROR", f"error occur when preStop: {str(e)}")
                # 发生异常时确保进程被终止并清理
                if save_process.is_alive():
                    save_process.kill()
                    save_process.join(timeout=5)
                try:
                    snapshot_mgr.cleanup_incomplete_save(snapshot_name)
                except Exception as cleanup_error:
                    log("ERROR", f"error during cleanup: {str(cleanup_error)}")
            else:
                log("INFO", "save completed successfully")

            # 等待清理线程完成
            # _wait_cleanup_thread(cleanup_thread, timeout=300)

            log("INFO", f"FC PreStop End RequestId: {request_id}")
            return "OK"

        @self.app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
        @self.app.route("/", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
        @identify_user_or_default
        def proxy(path=""):
            backend_status = self.management.service.status
            # 只有 RUNNING 和 SAVING 状态允许请求通过
            if backend_status not in (BackendStatus.RUNNING, BackendStatus.SAVING):
                return ErrorResponse.create(
                    error_type="service_not_running",
                    message="Please start your comfyui service first",
                    status_code=503
                )

            # issue: https://teambition.alibaba-inc.com/task/67c96194e6efb1c42a7ee904
            original_uri = request.environ['RAW_URI']
            target_url = f"http://{constants.APP_HOST}{original_uri}"
            # print(f"Forwarding http request to path: {target_url}")

            # 准备转发的 headers（添加用户标识用于多租户支持）
            forward_headers = dict(request.headers)  
            forward_headers.pop(constants.HEADER_FUNART_COMFY_USERID, None)
            
            user_id = getattr(g, 'user_id', None)
            if user_id:
                forward_headers[constants.HEADER_FUNART_COMFY_USERID] = user_id

            # 对 POST /prompt 请求，将 user_id 注入到 extra_data 中
            # 确保 ComfyUI 执行线程能正确获取用户上下文（execution_patch 从 extra_data 读取）
            data = request.get_data()
            if user_id and path == 'prompt' and request.method == 'POST':
                try:
                    json_data = json.loads(data)
                    if 'extra_data' not in json_data:
                        json_data['extra_data'] = {}
                    json_data['extra_data'][constants.HEADER_FUNART_COMFY_USERID.lower()] = user_id
                    data = json.dumps(json_data)
                except (json.JSONDecodeError, TypeError):
                    pass

            resp = requests.request(
                method=request.method,
                url=target_url,
                headers=forward_headers,
                params=request.args,
                data=data,
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
