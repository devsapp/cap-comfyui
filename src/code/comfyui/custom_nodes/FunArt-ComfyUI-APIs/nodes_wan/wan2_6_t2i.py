"""
Wan 2.6 文生图节点
使用 DashScope ImageGeneration API 实现文字生成图像功能
"""

from inspect import cleandoc
import time
from http import HTTPStatus

import torch

try:
    from dashscope.aigc.image_generation import ImageGeneration
    from dashscope.api_entities.dashscope_response import Message

    DASHSCOPE_AVAILABLE = True
except ImportError:
    DASHSCOPE_AVAILABLE = False

# Import util helpers
from ..util import (
    bytesio_to_image_tensor,
    download_url_to_bytes,
    initialize_dashscope,
)


# 支持的模型
SUPPORTED_MODELS = ["wan2.6-t2i"]


class Wan2_6_T2I:
    """
    Wan 2.6 文生图节点 - 使用阿里云百炼 DashScope ImageGeneration API
    通过文字描述生成图像

    支持功能: 文字生成图像，支持提示词扩展，支持批量生成（n=1~4）
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "optional": {
                "api_key": (
                    "STRING",
                    {
                        "multiline": False,
                        "default": "",
                        "tooltip": ("DashScope API密钥（可选）。\n" "优先使用此处配置的密钥；若未配置，则使用环境变量 DASHSCOPE_API_KEY"),
                    },
                ),
                "model": (
                    SUPPORTED_MODELS,
                    {
                        "default": "wan2.6-t2i",
                        "tooltip": "选择使用的模型",
                    },
                ),
                "prompt": ("STRING", {"multiline": True, "default": "", "tooltip": "图像生成提示词"}),
                "negative_prompt": ("STRING", {"multiline": True, "default": "", "tooltip": "负面提示词"}),
                "width": (
                    "INT",
                    {
                        "default": 1280,
                        "min": 256,
                        "max": 2048,
                        "step": 8,
                        "tooltip": (
                            "输出图片宽度。默认值为 1280。\n\n"
                            "限制条件：\n"
                            "• 总像素在 [1280*1280, 1440*1440] 之间\n"
                            "• 宽高比范围为 [1:4, 4:1]\n"
                            "• 例如：768*2700 符合要求\n\n"
                            "常见比例推荐分辨率：\n"
                            "• 1:1 → 1280*1280\n"
                            "• 3:4 → 1104*1472\n"
                            "• 4:3 → 1472*1104\n"
                            "• 9:16 → 960*1696\n"
                            "• 16:9 → 1696*960"
                        ),
                    },
                ),
                "height": (
                    "INT",
                    {
                        "default": 1280,
                        "min": 256,
                        "max": 2048,
                        "step": 8,
                        "tooltip": (
                            "输出图片高度。默认值为 1280。\n\n"
                            "限制条件：\n"
                            "• 总像素在 [1280*1280, 1440*1440] 之间\n"
                            "• 宽高比范围为 [1:4, 4:1]\n"
                            "• 例如：768*2700 符合要求\n\n"
                            "常见比例推荐分辨率：\n"
                            "• 1:1 → 1280*1280\n"
                            "• 3:4 → 1104*1472\n"
                            "• 4:3 → 1472*1104\n"
                            "• 9:16 → 960*1696\n"
                            "• 16:9 → 1696*960"
                        ),
                    },
                ),
                "n": (
                    "INT",
                    {
                        "default": 1,
                        "min": 1,
                        "max": 4,
                        "step": 1,
                        "tooltip": "生成图片数量（1-4张）",
                    },
                ),
                "seed": (
                    "INT",
                    {
                        "default": -1,
                        "min": -1,
                        "max": 2147483647,
                        "step": 1,
                        "tooltip": "随机种子，-1表示随机",
                    },
                ),
                "prompt_extend": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": (
                            "是否开启prompt智能改写。开启后使用大模型对输入prompt进行智能改写。"
                            "对于较短的prompt生成效果提升明显，但会增加耗时。\n\n"
                            "• true：默认值，开启智能改写\n"
                            "• false：不开启智能改写"
                        ),
                    },
                ),
                "watermark": ("BOOLEAN", {"default": False, "tooltip": "是否添加水印"}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    DESCRIPTION = cleandoc(__doc__)
    FUNCTION = "generate_image"
    CATEGORY = "FunArt/Wan"

    def download_and_convert_image(self, url):
        """下载图片并转换为ComfyUI的IMAGE tensor"""
        start_time = time.time()

        # 下载图片
        download_start = time.time()
        image_bytes, file_size_mb = download_url_to_bytes(url, timeout=30)
        download_time = time.time() - download_start

        # 转换为tensor
        convert_start = time.time()
        tensor = bytesio_to_image_tensor(image_bytes, mode="RGB")
        convert_time = time.time() - convert_start

        elapsed_time = time.time() - start_time
        print(
            f"Image processed in {elapsed_time:.3f}s "
            f"(download: {download_time:.3f}s [{file_size_mb:.2f}MB], "
            f"convert: {convert_time:.3f}s, size: {tensor.shape})"
        )

        return tensor

    def _validate_inputs(self, prompt):
        """校验输入参数"""
        if not prompt:
            raise ValueError("请提供图像生成提示词")

    def _build_params(
        self,
        prompt,
        model,
        width,
        height,
        n,
        negative_prompt,
        seed,
        prompt_extend,
        watermark,
    ):
        """构造API调用参数"""
        # 构造 size 字符串
        size = f"{width}*{height}"

        # 构造 Message 对象
        message = Message(role="user", content=[{"text": prompt}])

        # 准备API调用参数（使用扁平结构，而不是 parameters 嵌套）
        params = {
            "model": model,
            "messages": [message],
            "prompt_extend": prompt_extend,
            "watermark": watermark,
            "n": n,
            "size": size,
        }

        # 添加负面提示词
        if negative_prompt:
            params["negative_prompt"] = negative_prompt

        # 添加种子
        if seed >= 0:
            valid_seed = seed % 2147483648
            if valid_seed != seed:
                print(f"Warning: Seed {seed} out of API range, adjusted to {valid_seed}")
            params["seed"] = valid_seed

        return params

    def _parse_and_log_result(self, response):
        """解析API结果并打印日志"""
        # 打印完整的API返回结果
        print("\n" + "=" * 80)
        print("API完整返回结果:")
        print("=" * 80)
        print(response)
        print("=" * 80 + "\n")

        # 检查响应状态
        if response.status_code != HTTPStatus.OK:
            raise RuntimeError(f"API call failed: {response.code} - {response.message}")

        # 验证结果
        if not hasattr(response.output, "choices") or not response.output.choices:
            raise RuntimeError("API returned success but no images generated")

        # 提取所有图片URL（遍历所有choices）
        image_urls = []
        for choice in response.output.choices:
            if not hasattr(choice, "message") or not hasattr(choice.message, "content"):
                continue

            for item in choice.message.content:
                # 支持字典和对象两种格式
                img_url = item.get("image") if isinstance(item, dict) else getattr(item, "image", None)
                if img_url:
                    image_urls.append(img_url)

        if not image_urls:
            raise RuntimeError("No images found in API response")

        print(f"✅ Successfully generated {len(image_urls)} image(s)\n")

        return image_urls

    def generate_image(
        self,
        api_key="",
        model="wan2.6-t2i",
        prompt="",
        negative_prompt="",
        width=1280,
        height=1280,
        n=1,
        seed=-1,
        prompt_extend=True,
        watermark=False,
    ):
        """
        使用 DashScope Wan 2.6 模型生成图像（文生图）
        """
        # 1. 校验输入
        self._validate_inputs(prompt)

        # 2. 初始化 DashScope
        effective_api_key = initialize_dashscope(api_key=api_key)

        # 3. 构造参数
        params = self._build_params(prompt, model, width, height, n, negative_prompt, seed, prompt_extend, watermark)

        # 4. 调用API
        response = ImageGeneration.call(api_key=effective_api_key, **params)

        # 5. 解析结果并打印日志
        image_urls = self._parse_and_log_result(response)

        # 6. 下载并转换所有生成的图片
        tensors = []
        for idx, img_url in enumerate(image_urls):
            print(f"Downloading image {idx + 1}/{len(image_urls)}...")
            tensor = self.download_and_convert_image(img_url)
            tensors.append(tensor)

        # 合并为单个tensor [N, H, W, C]
        if len(tensors) == 1:
            output_tensor = tensors[0]
        else:
            output_tensor = torch.cat(tensors, dim=0)

        return (output_tensor,)
