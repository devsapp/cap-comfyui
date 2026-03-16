"""
Wan 2.6 图像编辑节点
使用 DashScope HTTP API 实现图生图和图文混排功能（异步模式）
"""

from inspect import cleandoc
import time

import torch

try:
    from dashscope.aigc.image_generation import ImageGeneration
    from dashscope.api_entities.dashscope_response import Message

    DASHSCOPE_AVAILABLE = True
except ImportError:
    DASHSCOPE_AVAILABLE = False

# Import util helpers
from ..util import (
    async_call_and_wait,
    bytesio_to_image_tensor,
    download_url_to_bytes,
    initialize_dashscope,
    tensor_to_data_uri,
)


# 支持的模型
SUPPORTED_MODELS = ["wan2.6-image"]


class Wan2_6_ImageEdit:
    """
    Wan 2.6 图像编辑节点 - 使用阿里云百炼 DashScope HTTP API (异步模式)
    支持通过自然语言描述对图像进行编辑和合成，以及图文混排功能

    支持功能:
    - 图像编辑：多图输入（最多4张），通过文字描述进行图像编辑和合成
    - 图文混排：生成多张图片构成教程或步骤说明
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "optional": {
                "image_1": (
                    "IMAGE",
                    {
                        "tooltip": (
                            "第一张输入图像（可选）。\n\n"
                            "图像数量限制：\n"
                            "• enable_interleave=true（图文混排）：可输入 0~1 张图像\n"
                            "• enable_interleave=false（图像编辑）：必须输入 1~4 张图像\n"
                            "• 多张图像时，按照入参顺序定义图像顺序"
                        )
                    },
                ),
                "image_2": (
                    "IMAGE",
                    {
                        "tooltip": (
                            "第二张输入图像（可选）。\n\n"
                            "图像数量限制：\n"
                            "• enable_interleave=true（图文混排）：可输入 0~1 张图像\n"
                            "• enable_interleave=false（图像编辑）：必须输入 1~4 张图像\n"
                            "• 多张图像时，按照入参顺序定义图像顺序"
                        )
                    },
                ),
                "image_3": (
                    "IMAGE",
                    {
                        "tooltip": (
                            "第三张输入图像（可选）。\n\n"
                            "图像数量限制：\n"
                            "• enable_interleave=true（图文混排）：可输入 0~1 张图像\n"
                            "• enable_interleave=false（图像编辑）：必须输入 1~4 张图像\n"
                            "• 多张图像时，按照入参顺序定义图像顺序"
                        )
                    },
                ),
                "image_4": (
                    "IMAGE",
                    {
                        "tooltip": (
                            "第四张输入图像（可选）。\n\n"
                            "图像数量限制：\n"
                            "• enable_interleave=true（图文混排）：可输入 0~1 张图像\n"
                            "• enable_interleave=false（图像编辑）：必须输入 1~4 张图像\n"
                            "• 多张图像时，按照入参顺序定义图像顺序"
                        )
                    },
                ),
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
                        "default": "wan2.6-image",
                        "tooltip": "选择使用的模型",
                    },
                ),
                "prompt": ("STRING", {"multiline": True, "default": "", "tooltip": "图像生成提示词"}),
                "width": (
                    "INT",
                    {
                        "default": 1280,
                        "min": 256,
                        "max": 2048,
                        "step": 8,
                        "tooltip": (
                            "输出图像宽度。默认值为 1280。\n\n"
                            "限制条件：\n"
                            "• 总像素在 [768*768, 1280*1280] 之间（即 589824 至 1638400 像素）\n"
                            "• 宽高比范围为 [1:4, 4:1]\n"
                            "• 例如：1024*1536 符合要求\n\n"
                            "常见比例推荐分辨率：\n"
                            "• 1:1 → 1280*1280 或 1024*1024\n"
                            "• 2:3 → 800*1200\n"
                            "• 3:2 → 1200*800\n"
                            "• 3:4 → 960*1280\n"
                            "• 4:3 → 1280*960\n"
                            "• 9:16 → 720*1280\n"
                            "• 16:9 → 1280*720\n"
                            "• 21:9 → 1344*576"
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
                            "输出图像高度。默认值为 1280。\n\n"
                            "限制条件：\n"
                            "• 总像素在 [768*768, 1280*1280] 之间（即 589824 至 1638400 像素）\n"
                            "• 宽高比范围为 [1:4, 4:1]\n"
                            "• 例如：1024*1536 符合要求\n\n"
                            "常见比例推荐分辨率：\n"
                            "• 1:1 → 1280*1280 或 1024*1024\n"
                            "• 2:3 → 800*1200\n"
                            "• 3:2 → 1200*800\n"
                            "• 3:4 → 960*1280\n"
                            "• 4:3 → 1280*960\n"
                            "• 9:16 → 720*1280\n"
                            "• 16:9 → 1280*720\n"
                            "• 21:9 → 1344*576"
                        ),
                    },
                ),
                "enable_interleave": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "tooltip": (
                            "是否启用图文混排模式。\n\n"
                            "• false：图像编辑模式，必须输入 1~4 张图像\n"
                            "• true：图文混排模式，可输入 0~1 张图像，生成多张图片（如教程步骤）"
                        ),
                    },
                ),
                "max_images": (
                    "INT",
                    {
                        "default": 5,
                        "min": 1,
                        "max": 5,
                        "step": 1,
                        "tooltip": (
                            "仅在图文混排模式（enable_interleave=true）下生效。\n\n"
                            "作用：指定模型在单次回复中生成图像的最大数量。\n\n"
                            "取值范围：1~5，默认值为 5。\n\n"
                            "注意：该参数仅代表【数量上限】。实际生成的图像数量由模型推理决定，"
                            "可能会少于设定值（例如：设置为 5，模型可能根据内容仅生成 3 张）。"
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
                        "tooltip": "随机种子，-1表示随机",
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
        image_1,
        image_2,
        image_3,
        image_4,
        model,
        width,
        height,
        enable_interleave,
        max_images,
        seed,
        watermark,
    ):
        """构造API调用参数"""
        # 构建 messages 内容
        content = [{"text": prompt}]

        # 转换图片为 data URI
        print("Converting images to base64...")
        convert_start = time.time()
        if image_1 is not None:
            content.append({"image": tensor_to_data_uri(image_1, total_pixels=4096 * 4096)})
        if image_2 is not None:
            content.append({"image": tensor_to_data_uri(image_2, total_pixels=4096 * 4096)})
        if image_3 is not None:
            content.append({"image": tensor_to_data_uri(image_3, total_pixels=4096 * 4096)})
        if image_4 is not None:
            content.append({"image": tensor_to_data_uri(image_4, total_pixels=4096 * 4096)})
        convert_time = time.time() - convert_start
        if len(content) > 1:
            print(f"{len(content) - 1} image(s) converted in {convert_time:.3f}s")

        # 构建参数
        size = f"{width}*{height}"
        params = {
            "model": model,
            "messages": [Message(role="user", content=content)],
            "size": size,
            "watermark": watermark,
        }

        # 根据模式设置不同的参数
        if enable_interleave:
            # 图文混排模式
            params["enable_interleave"] = True
            params["max_images"] = max_images
        else:
            # 图像编辑模式
            params["prompt_extend"] = True
            params["n"] = 1
            params["enable_interleave"] = False

        # 添加种子
        if seed >= 0:
            valid_seed = seed % 2147483648
            if valid_seed != seed:
                print(f"Warning: Seed {seed} out of API range, adjusted to {valid_seed}")
            params["seed"] = valid_seed

        return params

    def _parse_and_log_result(self, result):
        """解析API结果并打印日志"""
        # 打印完整的API返回结果
        print("\n" + "=" * 80)
        print("API完整返回结果:")
        print("=" * 80)
        print(result)
        print("=" * 80 + "\n")

        # 验证结果
        if not hasattr(result.output, "choices") or not result.output.choices:
            task_id = result.output.task_id if result.output else "N/A"
            raise RuntimeError(f"API returned success but no images generated (Task ID: {task_id})")

        # 提取所有图片URL（遍历所有choices）
        image_urls = []
        for choice in result.output.choices:
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
        image_1=None,
        image_2=None,
        image_3=None,
        image_4=None,
        api_key="",
        model="wan2.6-image",
        prompt="",
        width=1280,
        height=1280,
        enable_interleave=False,
        max_images=5,
        seed=-1,
        watermark=False,
    ):
        """
        使用 DashScope Wan 2.6 模型生成图像（图生图 / 图文混排）
        """
        # 1. 校验输入
        self._validate_inputs(prompt)

        # 2. 初始化 DashScope
        effective_api_key = initialize_dashscope(api_key=api_key)

        # 3. 构造参数
        params = self._build_params(
            prompt, image_1, image_2, image_3, image_4, model, width, height, enable_interleave, max_images, seed, watermark
        )

        # 4. 调用API
        result = async_call_and_wait(
            async_call_func=ImageGeneration.async_call,
            wait_func=ImageGeneration.wait,
            params=params,
            api_key=effective_api_key,
            task_name="Image Generation (Edit/Interleave)",
        )

        # 5. 解析结果并打印日志
        image_urls = self._parse_and_log_result(result)

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
