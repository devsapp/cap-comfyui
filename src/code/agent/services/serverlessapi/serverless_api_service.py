import re
import os
import json
import time
import base64
import random
import hashlib
import threading
from traceback import print_exception
import requests
import websocket
from typing import Any

import constants
from store import Store, FileSystem, OSS
from utils.logger import log

from uuid import uuid4, UUID
from flask import request


class ComfyUIException(Exception):
    def __init__(self, message: str, code: str, raw: str):
        super().__init__(message)
        self.raw = raw
        self.code = code

    def response(self):
        raw = self.raw
        try:
            raw = json.loads(raw)
        except:
            pass

        res = {
            "type": "error",
            "error_code": self.code or constants.ERROR_CODE.UNCLASSIFY.value,
            "error_message": str(self),
        }

        if raw:
            res["raw"] = raw

        return res


class ServerlessApiService:
    def __init__(self):
        self.endpoint = f"http://{constants.APP_HOST}"

        # 状态持久化
        # 在异步调用 Serverless API 时，可以通过将状态写至持久化存储来确保在多个实例同时出图时仍然可以正确获取状态
        #
        # 默认实现了基于共享存储的方式实现的状态持久化（需要正确挂载 NAS）
        # 也可以考虑复用上面的 oss_store，将图片和状态均存储至 OSS 中
        # 如 `self.store: Store = self.oss_store`
        #
        # 必要时，也可以参考对应代码实现基于 Redis、TableStore、MySQL 等方式的状态持久化
        self.store: Store = FileSystem(f"{constants.MNT_DIR}/output/serverless_api")

        # 记录启动信息和日志级别
        log("INFO", f"ServerlessApiService initialized with endpoint: {self.endpoint}")
        log("INFO", f"Current log level: {constants.LOG_LEVEL}")

        # 用于检测状态变化的缓存
        self._last_status_cache = {}  # task_id -> last_status_summary
        self._cache_lock = threading.Lock()

    def get_credentials(self):
        """
        获取阿里云访问凭证

        优先从 HTTP 请求 header 中获取，如果获取失败则从环境变量中获取。

        Returns:
            tuple: (access_key_id, access_key_secret, security_token)
        """
        ak = ""
        sk = ""
        sts = ""

        # 优先尝试从 header 获取
        try:
            ak = request.headers.get(constants.HEADER_KEY_ACCESS_KEY_ID, "")
            sk = request.headers.get(constants.HEADER_KEY_ACCESS_KEY_SECRET, "")
            sts = request.headers.get(constants.HEADER_KEY_SECURITY_TOKEN, "")
        except Exception as e:
            print_exception(e)
            log("WARNING", f"an exception occures when get credentials from header, {e}")

        # 如果 header 没有，尝试从 env 获取
        if ak == "" or sk == "":
            log("WARNING", "failed to get credentials from header")

            ak = constants.ALIBABA_CLOUD_ACCESS_KEY_ID
            sk = constants.ALIBABA_CLOUD_ACCESS_KEY_SECRET
            sts = constants.ALIBABA_CLOUD_SECURITY_TOKEN
        if ak == "" or sk == "":
            log("WARNING", "failed to get credentials from env")
        return ak, sk, sts

    def get_oss_store(self):
        """
        创建 OSS 存储客户端

        使用当前请求的凭证创建 OSS 客户端实例，用于上传生成的图片/视频到阿里云 OSS。

        Returns:
            OSS: OSS 客户端实例
        """
        ak, sk, sts = self.get_credentials()

        # OSS 存储，需要时，可以将生成的图片同步至 OSS 中
        return OSS(
            constants.OSS_BUCKET_DOMAIN,
            ak,
            sk,
            sts,
            constants.OSS_KEY_PREFIX,
            constants.OSS_EXPIRES_IN_SECOND,
        )

    def api_prompt(self, client_id: str, prompt: Any):
        """
        提交 ComfyUI 工作流任务

        将处理后的 prompt（工作流定义）提交给 ComfyUI 后端执行。

        Args:
            client_id: WebSocket 客户端 ID，用于关联 WebSocket 连接
            prompt: ComfyUI 工作流定义（节点图）

        Returns:
            dict: 包含 prompt_id 等信息的响应

        Raises:
            ComfyUIException: 当 ComfyUI API 调用失败时抛出
        """
        req = {"client_id": client_id, "prompt": prompt}
        try:
            res = requests.post(
                os.path.join(self.endpoint, "prompt"),
                json=req,
                timeout=30,  # 添加超时设置
            )
        except requests.exceptions.ConnectionError as e:
            error_msg = f"Failed to connect to ComfyUI service at {self.endpoint}. Please ensure ComfyUI is running."
            log("ERROR", f"{error_msg} Error: {e}")
            raise ComfyUIException(
                error_msg,
                constants.ERROR_CODE.EXECUTION_FAILED.value,
                str(e),
            )
        except requests.exceptions.Timeout as e:
            error_msg = f"Request to ComfyUI service at {self.endpoint} timed out."
            log("ERROR", f"{error_msg} Error: {e}")
            raise ComfyUIException(
                error_msg,
                constants.ERROR_CODE.EXECUTION_FAILED.value,
                str(e),
            )
        except requests.exceptions.RequestException as e:
            error_msg = f"Request to ComfyUI service at {self.endpoint} failed: {str(e)}"
            log("ERROR", error_msg)
            raise ComfyUIException(
                error_msg,
                constants.ERROR_CODE.EXECUTION_FAILED.value,
                str(e),
            )

        if res.status_code != 200:
            log("ERROR", f"ComfyUI prompt request failed: {req}")

            data = {}
            try:
                data = res.json()
            except (json.JSONDecodeError, ValueError) as e:
                log("WARNING", f"failed to parse ComfyUI error response as JSON: {e}, raw: {res.text[:200]}")


            raise ComfyUIException(
                f"ComfyUI prompt api failed with {res.status_code}: {data.get('error', {}).get('message', res.text)}",
                constants.ERROR_CODE.PROMPT_ERROR.value,
                res.text,
            )

        return res.json()

    def api_websocket(self, client_id: str, on_message):
        """
        创建 WebSocket 连接到 ComfyUI

        用于实时接收任务执行状态更新（如进度、完成、错误等）。

        Args:
            client_id: 客户端 ID，用于标识此连接
            on_message: 消息回调函数，接收 (ws, message) 参数

        Returns:
            WebSocketApp: WebSocket 应用实例
        """
        endpoint = re.subn(r"^http", "ws", self.endpoint, count=1)[0]

        ws = websocket.WebSocketApp(
            f'{os.path.join(endpoint, "ws")}?clientId={client_id}',
            on_message=on_message,
            keep_running=True,
        )

        return ws

    def api_upload_image(self, content: bytes, overwrite: bool):
        """
        上传图片到 ComfyUI

        将图片内容上传到 ComfyUI 的 input 目录，供工作流节点使用。

        Args:
            content: 图片二进制内容
            overwrite: 是否覆盖同名文件

        Returns:
            dict: 包含上传后的文件信息（如 name 字段）
        """
        # 基于内容生成确定性的 UUID，相同内容产生相同 UUID
        content_hash = hashlib.md5(content).hexdigest()
        uuid = str(UUID(content_hash))
        files = {
            "image": (uuid, content),
        }

        if overwrite:
            files["overwrite"] = bytes("1")

        try:
            res = requests.post(
                os.path.join(self.endpoint, "upload/image"),
                files=files,
                timeout=30,
            )
        except requests.exceptions.ConnectionError as e:
            error_msg = f"Failed to connect to ComfyUI service at {self.endpoint}. Please ensure ComfyUI is running."
            log("ERROR", f"{error_msg} Error: {e}")
            raise ComfyUIException(
                error_msg,
                constants.ERROR_CODE.EXECUTION_FAILED.value,
                str(e),
            )
        except requests.exceptions.RequestException as e:
            error_msg = f"Request to ComfyUI service at {self.endpoint} failed: {str(e)}"
            log("ERROR", error_msg)
            raise ComfyUIException(
                error_msg,
                constants.ERROR_CODE.EXECUTION_FAILED.value,
                str(e),
            )

        return res.json()

    def api_get_history(self, prompt_id: str):
        """
        获取任务执行历史

        Args:
            prompt_id: 任务 ID

        Returns:
            dict: 包含任务执行结果、输出文件等信息
        """
        try:
            res = requests.get(
                os.path.join(self.endpoint, "history", prompt_id),
                timeout=30,
            )
            return res.json()
        except requests.exceptions.ConnectionError as e:
            error_msg = f"Failed to connect to ComfyUI service at {self.endpoint}. Please ensure ComfyUI is running."
            log("ERROR", f"{error_msg} Error: {e}")
            raise ComfyUIException(
                error_msg,
                constants.ERROR_CODE.EXECUTION_FAILED.value,
                str(e),
            )
        except requests.exceptions.RequestException as e:
            error_msg = f"Request to ComfyUI service at {self.endpoint} failed: {str(e)}"
            log("ERROR", error_msg)
            raise ComfyUIException(
                error_msg,
                constants.ERROR_CODE.EXECUTION_FAILED.value,
                str(e),
            )

    def api_view_image(self, filename: str, img_type: str, sub_folder: str):
        """
        下载生成的图片/视频文件

        Args:
            filename: 文件名
            img_type: 文件类型（如 "output", "temp"）
            sub_folder: 子目录名

        Returns:
            bytes: 文件二进制内容
        """
        try:
            res = requests.get(
                os.path.join(self.endpoint, "view"),
                params={
                    "filename": filename,
                    "type": img_type,
                    "subfolder": sub_folder,
                    "rand": random.random(),
                },
                timeout=30,
            )
            return res.content
        except requests.exceptions.ConnectionError as e:
            error_msg = f"Failed to connect to ComfyUI service at {self.endpoint}. Please ensure ComfyUI is running."
            log("ERROR", f"{error_msg} Error: {e}")
            raise ComfyUIException(
                error_msg,
                constants.ERROR_CODE.EXECUTION_FAILED.value,
                str(e),
            )
        except requests.exceptions.RequestException as e:
            error_msg = f"Request to ComfyUI service at {self.endpoint} failed: {str(e)}"
            log("ERROR", error_msg)
            raise ComfyUIException(
                error_msg,
                constants.ERROR_CODE.EXECUTION_FAILED.value,
                str(e),
            )

    def api_clear_history(self):
        """
        清除 ComfyUI 的历史记录

        释放内存和磁盘空间。
        """
        try:
            requests.post(
                os.path.join(self.endpoint, "history"),
                json={"clear": True},
                timeout=30,
            )
        except requests.exceptions.ConnectionError as e:
            error_msg = f"Failed to connect to ComfyUI service at {self.endpoint}. Please ensure ComfyUI is running."
            log("ERROR", f"{error_msg} Error: {e}")
            # 清除历史记录失败不应该阻止其他操作，只记录错误
        except requests.exceptions.RequestException as e:
            error_msg = f"Request to ComfyUI service at {self.endpoint} failed: {str(e)}"
            log("ERROR", error_msg)
            # 清除历史记录失败不应该阻止其他操作，只记录错误

    def parse_prompt(self, prompt: map):
        """
        预处理工作流定义

        自动处理以下内容：
        1. LoadImage/LoadImageMask 节点：支持 HTTP URL、OSS URL、Base64 格式的图片输入
        2. KSampler 节点：自动生成随机种子（当 seed=-1 时）
        3. SaveImage 节点：自动添加实例 ID 到文件名前缀

        Args:
            prompt: ComfyUI 工作流定义（字典格式）

        Returns:
            map: 处理后的工作流定义

        Raises:
            Exception: 当图片加载失败时抛出
        """
        ak, sk, sts = self.get_credentials()

        for key, value in prompt.items():
            class_type = value.get("class_type") if type(value) == dict else None
            
            # 处理图片/音频/视频加载节点
            if class_type in ("LoadImage", "LoadImageMask", "LoadAudio", "VHS_LoadVideo"):
                try:
                    # 根据节点类型确定输入字段名
                    if class_type == "LoadAudio":
                        input_key = "audio"
                        file_type = "audio"
                    elif class_type == "VHS_LoadVideo":
                        input_key = "video"
                        file_type = "video"
                    else:
                        input_key = "image"
                        file_type = "image"

                    file_url = value.get("inputs", {}).get(input_key, "")
                    content = ""

                    if file_url.startswith("http://") or file_url.startswith("https://"):
                        # 文件来源于 HTTP URL
                        log("DEBUG", f"downloading {file_type} from HTTP URL: {file_url}")
                        start_time = time.perf_counter()
                        response = requests.get(file_url)

                        if response.status_code >= 400:
                            raise Exception(
                                f"can not get {file_type} {file_url} from http url, got status code {response.status_code}"
                            )

                        content = response.content
                        if content == "":
                            raise Exception(f"can not get {file_type} {file_url} from http url")

                        elapsed = time.perf_counter() - start_time
                        log("INFO", f"successfully downloaded {file_type} from HTTP URL ({len(content)} bytes) in {elapsed:.2f}s")

                    elif file_url.startswith("oss://"):
                        # 文件来源于 OSS
                        log("DEBUG", f"downloading {file_type} from OSS: {file_url}")
                        start_time = time.perf_counter()
                        arr = file_url.split("/")
                        host = arr[2]
                        path = "/".join(arr[3:])
                        oss = OSS(host, ak, sk, sts, "", 0)
                        content = oss.get(path)
                        elapsed = time.perf_counter() - start_time

                        if content == "":
                            raise Exception(f"can not get {file_type} {file_url} from oss")

                        log("DEBUG", f"successfully downloaded {file_type} from OSS ({len(content)} bytes) in {elapsed:.2f}s")

                    elif len(file_url) > 64:
                        # 文件可能是 base64，尝试解析
                        log("DEBUG", f"decoding {file_type} from Base64")
                        start_time = time.perf_counter()
                        try:
                            content = base64.b64decode(file_url.strip())
                            elapsed = time.perf_counter() - start_time
                            log("DEBUG", f"successfully decoded {file_type} from Base64 ({len(content)} bytes) in {elapsed:.2f}s")
                        except:
                            elapsed = time.perf_counter() - start_time
                            log("DEBUG", f"failed to decode {file_type} from Base64 in {elapsed:.2f}s")
                            pass

                    if content:
                        # 上传文件并更新对应的输入字段
                        log("DEBUG", f"uploading {file_type} to ComfyUI")
                        start_time = time.perf_counter()
                        res = self.api_upload_image(content, False)
                        elapsed = time.perf_counter() - start_time
                        log("INFO", f"successfully uploaded {file_type} to ComfyUI as '{res['name']}' in {elapsed:.2f}s")
                        prompt[key]["inputs"][input_key] = res["name"]

                except Exception as e:
                    raise Exception(f"{class_type} failed: {e}")

            if type(value) == dict and value.get("class_type") == "KSampler":
                if value.get("inputs", {}).get("seed") == -1:
                    prompt[key]["inputs"]["seed"] = random.randint(0, 4294967296)

            if type(value) == dict and value.get("class_type") == "SaveImage":
                try:
                    value["inputs"]["filename_prefix"] = (
                        value.get("inputs", {}).get("filename_prefix", "ComfyUI")
                        + "_"
                        + constants.INSTANCE_ID
                    )
                except:
                    pass

        return prompt

    def get_history_result(self, prompt_id: str, output_base64=False, output_oss=False):
        """
        获取任务执行结果并处理输出文件

        从 ComfyUI 历史记录中提取输出文件（图片/视频），并根据参数选择：
        - 下载文件并转换为 Base64
        - 上传文件到 OSS 并生成签名 URL

        Args:
            prompt_id: 任务 ID
            output_base64: 是否将输出文件转换为 Base64 编码
            output_oss: 是否上传输出文件到 OSS

        Returns:
            dict: 包含所有输出结果的字典，格式：
                {
                    "type": "serverless_api",
                    "data": {
                        "prompt_id": "...",
                        "results": [
                            {
                                "node_id": "58",
                                "batch_id": 0,
                                "output": {
                                    "type": "gifs",
                                    "raw": {...},
                                    "base64": {"content": "..."},
                                    "oss": {"region": "...", "bucket": "...", "object": "...", "url": "..."}
                                }
                            }
                        ]
                    }
                }
        """
        # 出图结果数组
        results = []
        history = self.api_get_history(prompt_id)

        oss_store = self.get_oss_store()
        for node_id, output in history.get(prompt_id, {}).get("outputs", {}).items():
            # TODO: 只上传指定节点结果到 OSS 中
            for output_type, imgs in output.items():
                for index, img in enumerate(imgs):
                    # 调试日志：查看实际的数据类型和结构
                    log("DEBUG", f"node_id={node_id}, output_type={output_type}, index={index}")
                    log("DEBUG", f"img type: {type(img)}, img: {img}")

                    if type(img) != dict or not img.get("filename"):
                        log("DEBUG", f"skipping: type check={type(img) != dict}, filename check={not img.get('filename') if isinstance(img, dict) else 'N/A'}")
                        continue

                    filename = img.get("filename", "")
                    img_type = img.get("type", "")
                    sub_folder = img.get("subfolder", "")
                    img_output = None
                    oss_object_key = None
                    oss_url = None

                    if output_base64 or output_oss:
                        log("DEBUG", f"get file: {filename} (type={img_type}, subfolder={sub_folder})")
                        img_bytes = self.api_view_image(filename, img_type, sub_folder)
                        log("DEBUG", f"get {len(img_bytes)} bytes")

                        if output_base64:
                            img_output = base64.b64encode(img_bytes).decode("ascii")
                            log("DEBUG", f"encoded to base64: {len(img_output)} chars")

                        if output_oss:
                            log("DEBUG", "attempting OSS upload...")
                            try:
                                if not oss_store.ready():
                                    log("ERROR", "OSS client is not initialized")
                                    log("DEBUG", f"OSS_BUCKET_DOMAIN: {constants.OSS_BUCKET_DOMAIN}")
                                else:
                                    ext = filename.split(".")[-1]
                                    uuid = str(uuid4())
                                    oss_filename = f"{uuid}.{ext}" if ext else uuid
                                    log("INFO", f"uploading to OSS as: {oss_filename}")
                                    oss_store.put(oss_filename, img_bytes)
                                    oss_object_key = oss_store.object_key(oss_filename)
                                    oss_url = oss_store.sign(oss_filename)
                                    log("DEBUG", f"OSS upload succeeded with url: {oss_url}")
                            except Exception as e:
                                log("ERROR", f"OSS upload failed: {e}")
                                import traceback
                                traceback.print_exc()
                                pass
                    else:
                        log("DEBUG", f"skipping download/upload (output_base64={output_base64}, output_oss={output_oss})")

                    results.append(
                        {
                            "node_id": node_id,
                            "batch_id": index,
                            "output": {
                                "type": output_type,
                                "raw": {
                                    **img,
                                    "filename": filename,
                                    "type": img_type,
                                    "subfolder": sub_folder,
                                    "filepath": (
                                        os.path.join(img_type, sub_folder, filename)
                                        if sub_folder
                                        else os.path.join(img_type, filename)
                                    ),
                                },
                                "base64": {"content": img_output},
                                "oss": {
                                    "region": oss_store.region,
                                    "bucket": oss_store.bucket_name,
                                    "object": oss_object_key,
                                    "url": oss_url,
                                },
                            },
                        }
                    )

        return {
            "type": "serverless_api",
            "data": {"prompt_id": prompt_id, "results": results},
        }

    def put_status_to_store(self, task_id: str, status: str):
        """
        保存任务状态到持久化存储

        用于异步场景，状态信息以追加方式存储，每条状态占一行。
        这样多个实例可以通过共享存储（如 NAS）查询任务状态。

        Args:
            task_id: 任务 ID
            status: 状态信息（JSON 字符串）
        """
        if task_id and self.store:
            try:
                value = self.store.get(task_id)
                self.store.put(task_id, f"{value}\n{status}")
            except Exception as e:
                log("ERROR", f"put status to store failed, due to {e}")
            finally:
                pass

    def refresh_storage_cache(self):
        """刷新存储缓存，确保能获取到最新文件
        
        用于解决实例冻结导致的 NFS 缓存问题
        """
        if self.store and hasattr(self.store, 'refresh_cache'):
            try:
                self.store.refresh_cache()
            except Exception as e:
                log("WARNING", f"Failed to refresh storage cache: {e}")
    
    def get_status_from_store(self, task_id: str):
        """
        从持久化存储中读取任务状态历史

        Args:
            task_id: 任务 ID

        Returns:
            list: 状态历史列表，每个元素是一条状态消息（已解析为字典）
        """
        if self.store:
            value = self.store.get(task_id)
            result = [json.loads(line) for line in value.split("\n") if line]
            
            return result
        else:
            return []


    def run(
        self,
        prompt: map,
        output_base64=False,
        output_oss=False,
        callback=None,
        task_id: str = None,
    ):
        """
        执行 ComfyUI 工作流（Serverless API 核心方法）

        完整流程：
        1. 预处理工作流定义（parse_prompt）
        2. 建立 WebSocket 连接监听任务状态
        3. 提交任务到 ComfyUI
        4. 等待任务完成
        5. 获取并处理输出结果
        6. 保存状态到持久化存储

        Args:
            prompt: ComfyUI 工作流定义
            output_base64: 是否将输出转换为 Base64（适用于小文件）
            output_oss: 是否上传输出到 OSS（推荐用于生产环境）
            callback: WebSocket 消息回调函数，接收原始消息
            task_id: 任务 ID，用于状态持久化（默认使用 prompt_id）

        Returns:
            dict: 任务执行结果，包含所有输出文件信息

        Raises:
            ComfyUIException: 当 ComfyUI 执行出错时
            Exception: 其他异常
        """

        try:

            # 解析请求中是否存在 base64、http url 形式的图片
            prompt = self.parse_prompt(prompt)

            client_id = ""
            prompt_id = ""

            ws_err = None

            def on_message(ws: websocket.WebSocket, message: str):
                try:
                    # 忽略空消息
                    if not message or not message.strip():
                        return

                    # 尝试解析 JSON
                    try:
                        msg = json.loads(message)
                    except (json.JSONDecodeError, ValueError) as json_err:
                        # 非 JSON 消息，记录日志但不中断连接
                        # 可能是心跳、ping/pong 或其他非 JSON 消息
                        log("WARNING", f"websocket: non-JSON message received (ignored): {message}")
                        
                        return  # 继续等待下一条消息

                    msg_type = msg.get("type", "")
                    node_id = msg.get("data", {}).get("node", "")
                    current_prompt_id = msg.get("data", {}).get("prompt_id", "")

                    # 记录收到的消息类型（DEBUG 级别）
                    log("DEBUG", f"websocket message: type={msg_type}, node={node_id}, prompt_id={current_prompt_id}, message={message}")

                    if msg_type == "status":
                        nonlocal client_id
                        client_id = msg.get("data", {}).get("sid", "")

                    if callback and hasattr(callback, "__call__"):
                        callback(message)

                    if task_id:
                        self.put_status_to_store(task_id, message)

                    if msg_type == "executing":
                        # 节点执行
                        if not node_id:
                            # node 为空，说明没有节点在执行了
                            if current_prompt_id == prompt_id:
                                # prompt_id 匹配，确认完成
                                log("INFO", f"workflow completed, closing websocket for prompt_id={prompt_id}")
                                ws.close()
                            elif not current_prompt_id:
                                # prompt_id 为空，仅此时查询历史记录确认
                                log("WARNING", f"received executing with empty node_id and no prompt_id, checking history")
                                try:
                                    if len(self.api_get_history(prompt_id)) > 0:
                                        log("INFO", f"confirmed completion via history check for prompt_id={prompt_id}")
                                        ws.close()
                                except Exception as e:
                                    log("WARNING", f"history check failed: {e}")
                            else:
                                # prompt_id 不匹配
                                log("WARNING", f"received executing with empty node_id but prompt_id mismatch: expected={prompt_id}, got={current_prompt_id}")
                        else:
                            # 正在执行某个节点
                            log("DEBUG", f"executing node: {node_id} for prompt_id={current_prompt_id}")
                    elif msg_type == "execution_error":
                        # 执行出错
                        error_data = msg.get('data', {})
                        error_msg = error_data.get('exception_message', 'unknown error')
                        node_type = error_data.get('node_type', 'unknown')
                        node_id = error_data.get('node', 'unknown')
                        exception_type = error_data.get('exception_type', 'RuntimeError')
                        log("ERROR", f"[WorkflowExecution] Execution error (prompt_id={current_prompt_id}, task_id={task_id}, node_id={node_id}, node_type={node_type}, exception_type={exception_type}): {error_msg}")
                        ws.close()

                        raise ComfyUIException(
                            f"ComfyUI execution error: {msg.get('data', {}).get('exception_message', '')}",
                            constants.ERROR_CODE.EXECUTION_FAILED.value,
                            msg.get("data"),
                        )
                    elif msg_type == "execution_success":
                        # 执行成功
                        log("INFO", f"[WorkflowExecution] Execution success (prompt_id={current_prompt_id}, task_id={task_id}), closing websocket")
                        ws.close()
                    elif msg_type == "execution_start":
                        log("INFO", f"[WorkflowExecution] Execution started (prompt_id={current_prompt_id}, task_id={task_id})")
                    elif msg_type == "progress":
                        # 进度更新
                        value = msg.get('data', {}).get('value', 0)
                        max_val = msg.get('data', {}).get('max', 0)
                        if max_val > 0:
                            log("DEBUG", f"progress: {value}/{max_val} ({value*100/max_val:.1f}%) for prompt_id={current_prompt_id}")
                    else:
                        # 其他不处理的类型，如 "execution_start", "status", "progress", "execution_cached", "executed"
                        pass

                except Exception as e:
                    # 其他未预期的错误，记录并关闭连接
                    log("ERROR", f"websocket: unexpected error in on_message: {e}")
                    nonlocal ws_err
                    ws_err = e
                    ws.close()

            log("DEBUG", "creating websocket connection to ComfyUI")
            ws = self.api_websocket(client_id, on_message)
            ws_threading = threading.Thread(target=ws.run_forever)
            ws_threading.start()
            log("DEBUG", "websocket thread started")

            # 提交出图任务
            log("DEBUG", "waiting for client_id from websocket status message")
            while client_id == "":
                time.sleep(0.1)
            log("DEBUG", f"got client_id: {client_id}")

            log("DEBUG", "submitting workflow to ComfyUI")
            prompt_result = self.api_prompt(client_id, prompt)
            prompt_id = prompt_result.get("prompt_id", "")
            log("DEBUG", f"workflow submitted, prompt_id: {prompt_id}")
            log("DEBUG", f"received task_id: {task_id}, type: {type(task_id).__name__}")

            # 如果 task id 未指定,则使用 prompt id
            if not task_id:
                task_id = prompt_id
                log("DEBUG", f"task_id not provided, using prompt_id: {task_id}")
            else:
                log("DEBUG", f"using provided task_id: {task_id}")

            if not prompt_id:
                raise Exception("can not get prompt_id from ComfyUI")

            # 记录执行开始时间
            execution_start_time = time.time()
            
            # 已经有结果，则不必等待
            if len(self.api_get_history(prompt_id)) > 0:
                ws.close()
            else:
                # 等待工作流完成：WebSocket（主） + 轮询历史记录（备用）
                check_interval = int(os.getenv("SERVERLESS_API_CHECK_INTERVAL", "60"))
                log("INFO", f"[WorkflowExecution] Waiting for prompt to complete (prompt_id={prompt_id}, task_id={task_id}, check_interval={check_interval}s)")

                while ws_threading.is_alive():
                    # 等待一小段时间
                    ws_threading.join(timeout=check_interval)

                    # 如果线程已结束，退出循环。仅当 ws.close() 被调用时，线程才会结束。
                    if not ws_threading.is_alive():
                        break

                    # 定期检查历史记录（备用检测）
                    try:
                        if len(self.api_get_history(prompt_id)) > 0:
                            log("WARNING", f"detected completion via history check for prompt_id={prompt_id}, closing websocket")
                            ws.close()
                            break
                    except Exception as e:
                        log("DEBUG", f"history check failed: {e}")

            # 计算执行时间
            execution_time = time.time() - execution_start_time
            log("INFO", f"[WorkflowExecution] Workflow completed (prompt_id={prompt_id}, execution_time={execution_time:.2f}s, task_id={task_id})")

            if ws_err:
                log("ERROR", f"[WorkflowExecution] WebSocket error occurred (prompt_id={prompt_id}, task_id={task_id}): {ws_err}")
                raise ws_err

            log("DEBUG", f"fetching results for prompt_id: {prompt_id}")
            result = self.get_history_result(
                prompt_id, output_base64=output_base64, output_oss=output_oss
            )
            
            # 添加执行时间到结果数据中
            if result and "data" in result:
                result["data"]["execution_time"] = execution_time
            
            log("DEBUG", f"saving result to store for task_id: {task_id}")
            self.put_status_to_store(task_id, json.dumps(result))
            log("INFO", f"[WorkflowExecution] Finished running prompt (prompt_id={prompt_id}, task_id={task_id}, execution_time={execution_time:.2f}s, output_base64={output_base64}, output_oss={output_oss})")
            return result
        except ComfyUIException as e:
            self.put_status_to_store(
                task_id,
                json.dumps(e.response()),
            )

            raise e
        except Exception as e:
            self.put_status_to_store(
                task_id,
                json.dumps(
                    {
                        "type": "error",
                        "error_code": constants.ERROR_CODE.UNCLASSIFY.value,
                        "error_message": str(e),
                    }
                ),
            )

            raise e
