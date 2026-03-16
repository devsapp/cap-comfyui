"""
Wan 2.6 文生视频节点
使用 DashScope VideoSynthesis API 实现文字生成视频功能（支持多镜头叙事）
"""

from inspect import cleandoc
import time

try:
    from dashscope import VideoSynthesis

    DASHSCOPE_AVAILABLE = True
except ImportError:
    DASHSCOPE_AVAILABLE = False

# Import util helpers
from ..util import (
    async_call_and_wait,
    audio_to_base64_string,
    bytesio_to_video_output,
    download_url_to_bytes,
    initialize_dashscope,
    validate_audio_duration,
)


# 支持的模型
SUPPORTED_MODELS = ["wan2.6-t2v"]

# 支持的视频尺寸（按档位和宽高比分组）
SUPPORTED_SIZES = [
    # 720P档位
    "720p: 1:1 (960*960)",
    "720p: 16:9 (1280*720)",
    "720p: 9:16 (720*1280)",
    "720p: 4:3 (1088*832)",
    "720p: 3:4 (832*1088)",
    # 1080P档位
    "1080p: 1:1 (1440*1440)",
    "1080p: 16:9 (1920*1080)",
    "1080p: 9:16 (1080*1920)",
    "1080p: 4:3 (1632*1248)",
    "1080p: 3:4 (1248*1632)",
]

# 支持的镜头类型
SHOT_TYPES = ["single", "multi"]


class Wan2_6_T2V:
    """
    Wan 2.6 文生视频节点 - 使用阿里云百炼 DashScope VideoSynthesis API
    通过文字描述生成视频，支持音频驱动和多镜头叙事

    支持功能: 文字生成视频，音频驱动，提示词扩展，多镜头叙事
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "optional": {
                "audio": (
                    "AUDIO",
                    {
                        "tooltip": (
                            "音频输入（可选，用于音频驱动）。"
                            "格式: wav/mp3; 时长: 3~30秒; 大小: 不超过15MB。"
                            "若音频超过视频时长则自动截取，不足则超出部分无声"
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
                        "default": "wan2.6-t2v",
                        "tooltip": "选择使用的模型",
                    },
                ),
                "prompt": (
                    "STRING",
                    {"multiline": True, "default": "", "tooltip": "视频生成提示词"},
                ),
                "negative_prompt": (
                    "STRING",
                    {"multiline": True, "default": "", "tooltip": "负面提示词"},
                ),
                "size": (
                    SUPPORTED_SIZES,
                    {
                        "default": "720p: 16:9 (1280*720)",
                        "tooltip": "输出视频尺寸（格式：档位: 宽高比 (分辨率)）",
                    },
                ),
                "duration": (
                    "INT",
                    {
                        "default": 5,
                        "min": 2,
                        "max": 15,
                        "step": 1,
                        "tooltip": "视频时长（秒），取值范围 2-15 秒",
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
                "shot_type": (
                    SHOT_TYPES,
                    {
                        "default": "single",
                        "tooltip": (
                            "指定生成视频的镜头类型，即视频是由一个连续镜头还是多个切换镜头组成。\n\n"
                            "生效条件：仅当 prompt_extend 为 true 时生效。\n\n"
                            "参数优先级：shot_type > prompt。例如，若 shot_type 设置为 'single'，即使 prompt 中包含'生成多镜头视频'，模型仍会输出单镜头视频。\n\n"
                            "可选值：\n"
                            "  • single：默认值，输出单镜头视频（固定视角）\n"
                            "  • multi：输出多镜头视频（自动切换场景，适合故事性内容）"
                        ),
                    },
                ),
                "watermark": (
                    "BOOLEAN",
                    {"default": False, "tooltip": "是否添加水印"},
                ),
            },
        }

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("video",)
    OUTPUT_NODE = True
    DESCRIPTION = cleandoc(__doc__)
    FUNCTION = "generate_video"
    CATEGORY = "FunArt/Wan"

    def download_and_convert_video(self, url):
        """下载视频并转换为ComfyUI的VIDEO输出

        Args:
            url: 视频URL

        Returns:
            VIDEO: ComfyUI VIDEO输出对象
        """
        start_time = time.time()

        # 下载视频
        download_start = time.time()
        video_bytes, file_size_mb = download_url_to_bytes(url, timeout=120)
        download_time = time.time() - download_start

        # 转换为VIDEO输出
        convert_start = time.time()
        video_output = bytesio_to_video_output(video_bytes)
        convert_time = time.time() - convert_start

        elapsed_time = time.time() - start_time
        print(
            f"Video processed in {elapsed_time:.3f}s "
            f"(download: {download_time:.3f}s [{file_size_mb:.2f}MB], "
            f"convert: {convert_time:.3f}s)"
        )

        return video_output

    def parse_size(self, size_str):
        """从格式化的尺寸字符串中提取实际分辨率

        例如: "720p: 16:9 (1280*720)" -> "1280*720"
        """
        import re

        # 匹配括号内的分辨率
        match = re.search(r"\((\d+\*\d+)\)", size_str)
        if match:
            return match.group(1)
        # 如果没有匹配到，返回原始字符串（向后兼容）
        return size_str

    def _validate_inputs(self, prompt):
        """校验输入参数"""
        if not prompt:
            raise ValueError("请提供视频生成提示词")

    def _build_params(
        self,
        prompt,
        audio,
        model,
        size,
        duration,
        negative_prompt,
        seed,
        prompt_extend,
        shot_type,
        watermark,
    ):
        """构造API调用参数"""
        # 解析 size 参数，提取实际分辨率
        actual_size = self.parse_size(size)

        # 准备基础参数
        params = {
            "model": model,
            "prompt": prompt,
            "size": actual_size,
            "duration": duration,
            "prompt_extend": prompt_extend,
            "watermark": watermark,
        }

        # shot_type 仅在 prompt_extend=True 时添加
        if prompt_extend:
            params["shot_type"] = shot_type

        # 添加音频（如果有）
        if audio is not None:
            audio_start = time.time()
            # DashScope API 要求音频时长在 3~30秒之间
            validate_audio_duration(audio, 3.0, 30.0)
            audio_base64 = audio_to_base64_string(audio, "mp3", "libmp3lame")
            audio_time = time.time() - audio_start
            print(f"Audio converted in {audio_time:.3f}s")
            params["audio_url"] = f"data:audio/mp3;base64,{audio_base64}"

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

    def _parse_and_log_result(self, result):
        """解析API结果并打印日志"""
        # 打印完整的API返回结果
        print("\n" + "=" * 80)
        print("API完整返回结果:")
        print("=" * 80)
        print(result)
        print("=" * 80 + "\n")

        # 验证结果
        if not result.output or not result.output.video_url:
            task_id = result.output.task_id if result.output else "N/A"
            raise RuntimeError(f"API returned success but no video generated (Task ID: {task_id})")

        video_url = result.output.video_url
        return video_url

    def generate_video(
        self,
        audio=None,
        api_key="",
        model="wan2.6-t2v",
        prompt="",
        negative_prompt="",
        size="720p: 16:9 (1280*720)",
        duration=5,
        seed=-1,
        prompt_extend=True,
        shot_type="single",
        watermark=False,
    ):
        """
        使用 DashScope Wan 2.6 模型生成视频（文生视频）
        """
        # 1. 校验输入
        self._validate_inputs(prompt)

        # 2. 初始化 DashScope
        effective_api_key = initialize_dashscope(api_key=api_key)

        # 3. 构造参数
        params = self._build_params(prompt, audio, model, size, duration, negative_prompt, seed, prompt_extend, shot_type, watermark)

        # 4. 调用API
        result = async_call_and_wait(
            async_call_func=VideoSynthesis.async_call,
            wait_func=VideoSynthesis.wait,
            params=params,
            api_key=effective_api_key,
            task_name="Video Generation (T2V)",
        )

        # 5. 解析结果并打印日志
        video_url = self._parse_and_log_result(result)

        # 6. 下载视频并转换为VIDEO输出
        video_output = self.download_and_convert_video(video_url)

        return (video_output,)
