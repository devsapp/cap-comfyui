import json
import threading
import traceback
from queue import Queue
from traceback import print_exception

from flask import Blueprint, Flask, request, Response, copy_current_request_context
from flask_cors import cross_origin
from flask_sock import Sock
from simple_websocket import Server

import constants
from utils.bool import is_true
from utils.logger import log
from services.serverlessapi.serverless_api_service import (
    ComfyUIException,
    ServerlessApiService,
)


class ServerlessApiRoutes:
    HEADER_KEY_TASK_ID_PRIMARY = "x-fc-async-task-id"
    HEADER_KEY_TASK_ID_SECONDARY = "x-fc-request-id"

    def __init__(self):
        self.bp = Blueprint("serverless_api", __name__, url_prefix="/api/serverless")
        self.service = ServerlessApiService()
        self.sock = Sock()
        self.sock.bp = self.bp
        self.setup_routes()

    def register(self, app: Flask):
        app.register_blueprint(self.bp)

    @staticmethod
    def _extract_task_id():
        """
        从请求头中提取task_id
        
        Returns:
            tuple: (task_id, task_id_source)
        """
        async_task_id = request.headers.get(ServerlessApiRoutes.HEADER_KEY_TASK_ID_PRIMARY)
        fc_request_id = request.headers.get(ServerlessApiRoutes.HEADER_KEY_TASK_ID_SECONDARY)
        
        log("DEBUG", f"[ServerlessApiRoutes] Extracting task_id: x-fc-async-task-id={async_task_id}, x-fc-request-id={fc_request_id}")
        
        if async_task_id:
            log("DEBUG", f"[ServerlessApiRoutes] Using x-fc-async-task-id as task_id: {async_task_id}")
            return async_task_id
        elif fc_request_id:
            log("DEBUG", f"[ServerlessApiRoutes] Using x-fc-request-id as task_id: {fc_request_id}")
            return fc_request_id
        else:
            log("ERROR", f"[ServerlessApiRoutes] No task_id found in headers")
            return None

    def setup_routes(self):

        @self.bp.get("/status")
        @cross_origin()
        def get_status():
            task_id = request.args.get("task_id", "")
            if not task_id:
                return {
                    "type": "error",
                    "error_code": constants.ERROR_CODE.INVALID_PARAMS.value,
                    "error_message": "task_id is required",
                }, 400

            return self.service.get_status_from_store(task_id)

        if constants.COMFYUI_MODE != "cpu":
            @self.bp.post("/run")
            @cross_origin()
            def run_http():
                """
                出图接口，http 协议

                HTTP POST `/api/serverelss/run`

                Query:
                  - `stream`: 流式响应（响应 ComfyUI 原生返回的状态信息，并在最后附加非流式的结果）
                  - `output_base64`: 最终输出结果中，将图片以 base64 形式返回
                  - `output_oss`: 输出结果图片至 OSS，并在值中返回 OSS 的 path

                Header:
                  - `x-serverless-api-task-id`: 指定一个 task id，用于异步获取任务状态，不传输时不会持久化状态

                Body:
                  JSON body, 内容可参考 ComfyUI 原生 prompt 接口
                  针对如下部分进行优化
                    - LoadImage 节点支持 base64 图片、http url 图片
                    - KSampler seed 为 -1 时，支持自动生成随机数

                返回值:
                  输出的图片数组
                """
                body = request.get_json()
                stream = is_true(request.args.get("stream"))
                output_base64 = is_true(request.args.get("output_base64"))
                output_oss = is_true(request.args.get("output_oss"))
                
                task_id = self._extract_task_id()
                log("INFO", f"[HTTP] extracted task_id: {task_id}")

                if not stream:
                    try:
                        return self.service.run(
                            request_body=body,
                            output_base64=output_base64,
                            output_oss=output_oss,
                            task_id=task_id,
                        )
                    except ComfyUIException as e:
                        print_exception(e)
                        return e.response(), 500
                    except Exception as e:
                        error_msg = f"Failed to execute prompt: {str(e)}"
                        print_exception(e)
                        print(f"[ServerlessApi] {error_msg}\nStacktrace:\n{traceback.format_exc()}")
                        return {
                            "type": "error",
                            "error_code": constants.ERROR_CODE.UNCLASSIFY.value,
                            "error_message": error_msg,
                        }, 500

                else:
                    q = Queue()

                    def do_streaming(content):
                        """
                        将 callback 的数据推送到队列中
                        """
                        q.put(content)

                    def output_stream():
                        """
                        从队列将数据以流式返回给客户端
                        """
                        while True:
                            item = q.get(True)
                            yield f"data: {item if type(item) == str else json.dumps(item)}\n\n"

                            if not type(item) == str:
                                return

                    @copy_current_request_context
                    def run_prompt_task():
                        """
                        单独线程需要执行的任务
                        """
                        try:
                            result = self.service.run(
                                request_body=body,
                                output_base64=output_base64,
                                output_oss=output_oss,
                                callback=do_streaming,
                                task_id=task_id,
                            )
                            # 推送最终结果
                            q.put(result)
                        except ComfyUIException as e:
                            print_exception(e)
                            error_response = e.response()
                            q.put(error_response)
                        except Exception as e:
                            error_msg = f"Failed to execute prompt in stream mode: {str(e)}"
                            print_exception(e)
                            print(f"[ServerlessApi] {error_msg}\nStacktrace:\n{traceback.format_exc()}")
                            error_response = {
                                "type": "error",
                                "error_code": constants.ERROR_CODE.UNCLASSIFY.value,
                                "error_message": error_msg,
                            }
                            q.put(error_response)

                    # 出图的流程是同步执行的，需要在单独线程执行，不阻塞 stream 的流程
                    threading.Thread(target=run_prompt_task).start()

                    return Response(
                        output_stream(),
                        status=200,
                        content_type="text/event-stream",
                    )
        
        # WebSocket 路由只在 GPU 模式下注册（CPU 模式使用 gateway 的转发）
        if constants.COMFYUI_MODE != "cpu":
            @self.sock.route("/ws")
            def run_ws(ws: Server):
                """
                出图接口，websocket 协议

                WebSocket `/api/serverelss/ws`

                Query:
                  - `output_base64`: 最终输出结果中，将图片以 base64 形式返回
                  - `output_oss`: 输出结果图片至 OSS，并在值中返回 OSS 的 path

                Header:
                  - `x-serverless-api-task-id`: 指定一个 task id，用于异步获取任务状态，不传输时不会持久化状态

                WebSocket Message:
                  - client -> server: 输入参数，同 Serverless API HTTP 协议输入参数
                  - server -> client: 中间状态，同 Serverless API Stream 模式下中间状态数据
                  - server -> client: 最终结果，同 Serverless API 最终返回结果
                """

                try:
                    output_base64 = is_true(request.args.get("output_base64"))
                    output_oss = is_true(request.args.get("output_oss"))
                    
                    task_id = self._extract_task_id()
                    log("INFO", f"[WebSocket] extracted task_id: {task_id}")

                    # 获取第一个 message 作为输入的 prompt
                    data = ws.receive()
                    body = json.loads(data)

                    def callback(msg):
                        ws.send(msg)

                    results = self.service.run(
                        request_body=body,
                        output_base64=output_base64,
                        output_oss=output_oss,
                        callback=callback,
                        task_id=task_id,
                    )

                    ws.send(json.dumps(results))
                except ComfyUIException as e:
                    print_exception(e)
                    try:
                        ws.send(json.dumps(e.response()))
                    except Exception as send_error:
                        print(f"[GPU ServerlessApi WS] Failed to send error response: {send_error}")
                except Exception as e:
                    print_exception(e)
                    error_msg = f"Unexpected error in WebSocket handler: {str(e)}"
                    print(f"[GPU ServerlessApi WS] {error_msg}\nStacktrace:\n{traceback.format_exc()}")
                    
                    try:
                        ws.send(
                            json.dumps(
                                {
                                    "type": "error",
                                    "error_code": constants.ERROR_CODE.UNCLASSIFY.value,
                                    "error_message": error_msg,
                                }
                            )
                        )
                    except Exception as send_error:
                        print(f"[GPU ServerlessApi WS] Failed to send error response: {send_error}")
                    return
