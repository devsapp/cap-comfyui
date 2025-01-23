import re
import os
import json
import base64
import random
import asyncio
import requests
import websocket
from typing import Any

import constants
from store import Store, FileSystem

from uuid import uuid4


class ServerlessApiService:
    def __init__(self):
        self.endpoint = f"http://{constants.COMFYUI_HOST}"

        # 状态持久化
        # 在异步调用 Serverless API 时，可以通过将状态写至持久化存储来确保在多个实例同时出图时仍然可以正确获取状态
        #
        # 默认实现了基于共享存储的方式实现的状态持久化（需要正确挂载 NAS）
        # 必要时，也可以参考对应代码实现基于 Redis、TableStore、MySQL 等方式的状态持久化
        self.store: Store = FileSystem(f"{constants.MNT_DIR}/output/serverless_api")
        self.store_lock = asyncio.Lock()

    def api_prompt(self, client_id: str, prompt: Any):
        """
        出图
        """
        req = {"client_id": client_id, "prompt": prompt}
        res = requests.post(
            os.path.join(self.endpoint, "prompt"),
            json=req,
        )

        if res.status_code != 200:
            print({"prompt request": req})
            raise Exception(
                f"ComfyUI prompt api failed with {res.status_code}: {res.text}"
            )

        return res.json()

    def api_websocket(self, client_id: str, on_message):
        endpoint = re.subn(r"^http", "ws", self.endpoint, count=1)[0]

        ws = websocket.WebSocketApp(
            f'{os.path.join(endpoint, "ws")}?clientId={client_id}',
            on_message=on_message,
            keep_running=True,
        )

        return ws

    def api_upload_image(self, content: bytes, overwrite: bool):
        uuid = str(uuid4())
        files = {
            "image": (uuid, content),
        }

        if overwrite:
            files["overwrite"] = bytes("1")

        res = requests.post(
            os.path.join(self.endpoint, "/upload/image"),
            files=files,
        )

        return res.json()

    def api_get_history(self, prompt_id: str):
        return requests.get(os.path.join(self.endpoint, "history", prompt_id)).json()

    def parse_prompt(self, prompt: map):
        """
        预处理 prompt 的内容
        - 如果以 base64、url 形式传输的图片，自动完成上传行为
        """
        for key, value in prompt.items():
            if type(value) == dict and value.get("class_type") == "LoadImage":
                try:
                    image = value.get("inputs", {}).get("image", "")
                    content = ""

                    if image.startswith("http://") or image.startwith("https://"):
                        # 图片来源于 url
                        content = requests.get(image).text
                    elif len(image) > 64:
                        # 图像可能是 base64，尝试使用 base64 解析
                        content = base64.b64decode(image.strip())

                    if content:
                        res = self.api_upload_image(content, False)
                        prompt[key]["inputs"]["image"] = res["name"]

                except Exception as e:
                    print(e)
            if type(value) == dict and value.get("class_type") == "KSampler":
                if value.get("inputs", {}).get("seed") == -1:
                    prompt[key]["inputs"]["seed"] = random.randint(0, 4294967296)
        return prompt

    def get_history_result(self, prompt_id: str, output_base64=False, output_oss=False):
        # 出图结果数组
        results = []
        history = self.api_get_history(prompt_id)

        for node_id, output in history.get(prompt_id, {}).get("outputs", {}).items():
            images = output.get("images", [])
            for index, img in enumerate(images):
                filename = img.get("filename", "")
                img_type = img.get("type", "")
                sub_folder = img.get("subfolder", "")
                img_output = None

                if output_base64 or output_oss:
                    img_bytes = requests.get(
                        os.path.join(self.endpoint, "view"),
                        params={
                            "filename": filename,
                            "type": img_type,
                            "subfolder": sub_folder,
                            "rand": random.random(),
                        },
                    ).content

                    if output_base64:
                        img_output = base64.b64encode(img_bytes)

                    if output_oss:
                        # TODO
                        pass

                results.append(
                    {
                        "node_id": node_id,
                        "index": index,
                        "filename": filename,
                        "img_type": img_type,
                        "sub_folder": sub_folder,
                        "image": img_output,
                    }
                )

        return results

    def put_status_to_store(self, task_id: str, status: str):
        """
        同步状态至持久化存储

        Args:
            task_id: 任务 id
            status: 增量的状态信息
        """
        if task_id and self.store and self.store_lock:
            try:
                # self.store_lock.acquire()
                value = self.store.get(task_id)
                self.store.put(task_id, f"{value}\n{status}")
            finally:
                pass
                # self.store_lock.release()

    def get_status_from_store(self, task_id: str):
        if self.store:
            value = self.store.get(task_id)
            return [json.loads(line) for line in value.split("\n") if line]
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
        Serverless API 的核心逻辑
        """

        # 解析请求中是否存在 base64、http url 形式的图片
        prompt = self.parse_prompt(prompt)

        client_id = str(uuid4())
        prompt_id = ""

        def on_message(ws: websocket.WebSocket, message: str):
            try:
                msg = json.loads(message)

                msg_type = msg.get("type", "")
                node_id = msg.get("data", {}).get("node", "")
                current_prompt_id = msg.get("data", {}).get("prompt_id", "")
                node = prompt.get(node_id, {})

                if prompt_id != current_prompt_id:
                    # 非当前出图任务，忽略
                    return

                if callback and hasattr(callback, "__call__"):
                    callback(message)

                self.put_status_to_store(task_id, message)

                if msg_type == "executing":
                    # 节点执行
                    if not node_id:
                        # 当前正在执行的 node 为空，说明 prompt 执行结束了
                        ws.close()
                        pass
                elif msg_type == "execution_error":
                    # 执行出错
                    pass
                else:
                    # 其他不处理的类型，如 "execution_start", "status", "progress", "execution_cached", "executed"
                    pass

            except Exception as e:
                print(e)

        ws = self.api_websocket(client_id, on_message)

        # 提交出图任务
        prompt_result = self.api_prompt(client_id, prompt)
        prompt_id = prompt_result.get("prompt_id", "")

        if not prompt_id:
            raise Exception("can not get prompt_id from ComfyUI")

        # 先尝试获取一下，如果之前出过同样的图，不需要再等待 websocket
        results = self.get_history_result(
            prompt_id, output_base64=output_base64, output_oss=output_oss
        )
        if results:
            self.put_status_to_store(task_id, json.dumps(results))
            ws.close()
            return results

        ws.run_forever()

        results = self.get_history_result(
            prompt_id, output_base64=output_base64, output_oss=output_oss
        )
        self.put_status_to_store(task_id, json.dumps(results))
        return results
