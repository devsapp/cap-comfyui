"""
Wan 2.5 图像编辑节点
使用 DashScope ImageSynthesis API 实现图生图功能
"""

from inspect import cleandoc
import io
import os
import base64
import time
from http import HTTPStatus

import torch
import numpy as np
from PIL import Image

try:
    import dashscope
    from dashscope import ImageSynthesis
    import requests

    DASHSCOPE_AVAILABLE = True
except ImportError:
    DASHSCOPE_AVAILABLE = False


class Wan2_5_ImageEdit:
    """
    Wan 2.5 图像编辑节点 - 使用阿里云百炼 DashScope ImageSynthesis API
    支持通过自然语言描述对图像进行编辑和合成

    API文档: https://bailian.console.aliyun.com/?spm=5176.fcnext.console-base_product-drawer-right.dproducts-and-services-sfm.62952f033vAVNr&tab=api#/api/?type=model&url=2982258

    模型: wan2.5-i2i-preview
    支持功能: 多图输入（最多3张），通过文字描述进行图像编辑和合成
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": "", "tooltip": "图像生成提示词"}),
                "image_1": ("IMAGE", {"tooltip": "第一张输入图像"}),
            },
            "optional": {
                "api_key": (
                    "STRING",
                    {
                        "multiline": False,
                        "default": "",
                        "tooltip": (
                            "DashScope API密钥（可选）。\n"
                            "优先使用此处配置的密钥；若未配置，则使用环境变量 DASHSCOPE_API_KEY"
                        ),
                    },
                ),
                "image_2": ("IMAGE", {"tooltip": "第二张输入图像（可选）"}),
                "image_3": ("IMAGE", {"tooltip": "第三张输入图像（可选）"}),
                "negative_prompt": ("STRING", {"multiline": True, "default": "", "tooltip": "负面提示词"}),
                "width": (
                    "INT",
                    {
                        "default": -1,
                        "min": -1,
                        "max": 2048,
                        "step": 8,
                        "tooltip": (
                            "输出图像宽度。默认-1表示自动。\n"
                            "设为-1时：单图输入保持输入图像宽高比，多图输入保持最后一张图像宽高比（总像素1280*1280）。\n"
                            "自定义时：总像素需在[768*768, 1280*1280]之间，宽高比在[1:4, 4:1]之间"
                        ),
                    },
                ),
                "height": (
                    "INT",
                    {
                        "default": -1,
                        "min": -1,
                        "max": 2048,
                        "step": 8,
                        "tooltip": (
                            "输出图像高度。默认-1表示自动。\n"
                            "设为-1时：单图输入保持输入图像宽高比，多图输入保持最后一张图像宽高比（总像素1280*1280）。\n"
                            "自定义时：总像素需在[768*768, 1280*1280]之间，宽高比在[1:4, 4:1]之间"
                        ),
                    },
                ),
                "seed": (
                    "INT",
                    {
                        "default": -1,
                        "min": -1,
                        "max": 2147483647,
                        "step": 1,
                        "tooltip": "随机种子，-1表示随机，范围[0,2147483647]",
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

    def tensor_to_base64(self, tensor):
        """将ComfyUI的IMAGE tensor转换为base64字符串"""
        start_time = time.time()

        # tensor shape: [B, H, W, C] 或 [H, W, C]
        if len(tensor.shape) == 4:
            tensor = tensor[0]  # 取第一张图片

        # 转换为 numpy array (H, W, C)，值范围 [0, 1]
        img_array = tensor.cpu().numpy()

        # 转换为 0-255 范围的 uint8
        img_array = np.clip(img_array * 255.0, 0, 255).astype(np.uint8)

        # 转换为 PIL Image
        pil_image = Image.fromarray(img_array, mode="RGB")

        # 转换为 bytes
        buffered = io.BytesIO()
        pil_image.save(buffered, format="PNG")
        img_bytes = buffered.getvalue()

        # Base64 编码
        encoded_string = base64.b64encode(img_bytes).decode("utf-8")

        elapsed_time = time.time() - start_time
        print(f"tensor_to_base64 time: {elapsed_time:.3f}s (image size: {len(encoded_string)//1024}KB)")

        # 返回 data URI 格式
        return f"data:image/png;base64,{encoded_string}"

    def download_and_convert_image(self, url):
        """下载图片并转换为ComfyUI的IMAGE tensor"""
        start_time = time.time()

        # 下载图片
        download_start = time.time()
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        download_time = time.time() - download_start

        # 从字节流创建PIL图像
        pil_image = Image.open(io.BytesIO(response.content))

        # 转换为RGB
        if pil_image.mode != "RGB":
            pil_image = pil_image.convert("RGB")

        # 转换为numpy array并归一化到[0, 1]
        img_array = np.array(pil_image).astype(np.float32) / 255.0

        # 转换为tensor [1, H, W, C]
        tensor = torch.from_numpy(img_array)[None,]

        elapsed_time = time.time() - start_time
        print(
            f"download_and_convert_image time: {elapsed_time:.3f}s (download: {download_time:.3f}s, convert: {elapsed_time-download_time:.3f}s, size: {tensor.shape})"
        )

        return tensor

    def generate_image(self, prompt, image_1, api_key="", image_2=None, image_3=None, negative_prompt="", width=-1, height=-1, seed=-1, watermark=False):
        """
        使用 DashScope Wan 2.5 模型生成图像（图生图）
        支持1-3张图片输入
        """
        if not DASHSCOPE_AVAILABLE:
            raise ImportError("dashscope 未安装。请运行: pip install dashscope requests")

        # 获取 API Key：优先使用传入的参数，否则从环境变量读取
        effective_api_key = api_key if api_key else os.environ.get("DASHSCOPE_API_KEY", "")
        if not effective_api_key:
            raise ValueError(
                "请提供 DashScope API Key。\n"
                "方式1：在节点中配置 api_key 参数\n"
                "方式2：设置环境变量 DASHSCOPE_API_KEY"
            )

        # 设置 API Key
        dashscope.api_key = effective_api_key
        dashscope.base_http_api_url = "https://dashscope.aliyuncs.com/api/v1"

        # 将 IMAGE tensor 转换为 base64
        image_base64_list = [self.tensor_to_base64(image_1)]
        if image_2 is not None:
            image_base64_list.append(self.tensor_to_base64(image_2))
        if image_3 is not None:
            image_base64_list.append(self.tensor_to_base64(image_3))

        # 准备API调用参数
        params = {
            "model": "wan2.5-i2i-preview",
            "prompt": prompt,
            "images": image_base64_list,
            "n": 1,  # 固定生成1张图片
            "watermark": watermark,
        }

        # 添加可选参数
        if negative_prompt:
            params["negative_prompt"] = negative_prompt

        if seed >= 0:
            # 确保 seed 在 DashScope API 允许的范围内 [0, 2147483647]
            # 如果超出范围，使用模运算限制到有效范围
            valid_seed = seed % 2147483648  # 2^31
            if valid_seed != seed:
                print(f"Warning: Seed {seed} out of API range, adjusted to {valid_seed}")
            params["seed"] = valid_seed

        # 处理 size 参数（宽*高）
        # 如果 width 和 height 都大于 0，则使用自定义尺寸
        # 如果为 -1（默认值），则不传 size 参数，让 API 根据输入图片自动调整宽高比
        if width > 0 and height > 0:
            # 验证总像素在 [768*768, 1280*1280] 范围内
            total_pixels = width * height
            min_pixels = 768 * 768  # 589,824
            max_pixels = 1280 * 1280  # 1,638,400
            
            if total_pixels < min_pixels or total_pixels > max_pixels:
                raise ValueError(
                    f"Total pixels ({width}*{height}={total_pixels}) out of range. "
                    f"Must be between {min_pixels} (768*768) and {max_pixels} (1280*1280)"
                )
            
            # 验证宽高比在 [1:4, 4:1] 范围内
            aspect_ratio = width / height
            if aspect_ratio < 0.25 or aspect_ratio > 4.0:
                raise ValueError(
                    f"Aspect ratio ({width}:{height} = {aspect_ratio:.2f}) out of range. "
                    f"Must be between 1:4 (0.25) and 4:1 (4.0)"
                )
            
            params["size"] = f"{width}*{height}"
            print(f"Output size: {width}*{height} (total pixels: {total_pixels}, aspect ratio: {aspect_ratio:.2f})")
        elif width == -1 and height == -1:
            # 不传 size 参数，使用输入图片的宽高比
            print("Output size: Auto (maintaining input image aspect ratio with total pixels ~1280*1280)")
        else:
            # width 和 height 必须同时为 -1 或同时大于 0
            raise ValueError(
                f"Width and height must be both -1 (auto) or both > 0 (custom). "
                f"Got width={width}, height={height}"
            )

        # 调用 API
        print("Calling DashScope API (model: wan2.5-i2i-preview)")
        print(f"Prompt: {prompt[:100]}..." if len(prompt) > 100 else f"Prompt: {prompt}")
        print(f"Number of images: {len(image_base64_list)}")

        response = ImageSynthesis.call(**params)

        print(f"API response status: {response.status_code}")
        print(f"Request ID: {response.request_id if hasattr(response, 'request_id') else 'N/A'}")

        # 检查响应状态
        if response.status_code != HTTPStatus.OK:
            raise RuntimeError(f"API call failed: {response.code} - {response.message}")

        # 检查结果是否为空
        if not response.output or not response.output.results:
            print("=" * 60)
            print("API call error: Returned success but no images generated")
            print("-" * 60)
            print(f"Status Code: {response.status_code}")
            print(f"Request ID: {response.request_id if hasattr(response, 'request_id') else 'N/A'}")
            print(f"Code: {response.code if hasattr(response, 'code') else 'N/A'}")
            print(f"Message: {response.message if hasattr(response, 'message') else 'N/A'}")
            print(f"Output: {response.output if hasattr(response, 'output') else 'N/A'}")
            print("=" * 60)

            error_msg = "API returned success but no images generated, possibly due to quota limit, rate limit or other API issues"
            raise RuntimeError(error_msg)

        print(f"Successfully generated {len(response.output.results)} image(s)")

        # 下载并转换生成的图片（只有一张）
        result = response.output.results[0]
        output_tensor = self.download_and_convert_image(result.url)

        # 返回单张图片，shape: [1, H, W, C]
        return (output_tensor,)
