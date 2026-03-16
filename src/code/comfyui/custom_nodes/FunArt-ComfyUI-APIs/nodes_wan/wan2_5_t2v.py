"""
Wan 2.5 文生视频节点
使用 DashScope VideoSynthesis API 实现文字生成视频功能
"""

from inspect import cleandoc
import io
import os
import base64
import time
import uuid
from http import HTTPStatus

try:
    import folder_paths

    FOLDER_PATHS_AVAILABLE = True
except ImportError:
    FOLDER_PATHS_AVAILABLE = False

from comfy_api.input_impl import VideoFromFile

try:
    import dashscope
    from dashscope import VideoSynthesis
    import requests

    DASHSCOPE_AVAILABLE = True
except ImportError:
    DASHSCOPE_AVAILABLE = False

# 尝试导入音频处理库
try:
    import scipy.io.wavfile as wavfile
    import numpy as np

    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False


# 支持的视频尺寸 (按分辨率档位分组)
# 480P: 832*480(16:9), 480*832(9:16), 624*624(1:1)
# 720P: 1280*720(16:9), 720*1280(9:16), 960*960(1:1), 1088*832(4:3), 832*1088(3:4)
# 1080P: 1920*1080(16:9), 1080*1920(9:16), 1440*1440(1:1), 1632*1248(4:3), 1248*1632(3:4)
SUPPORTED_SIZES = [
    # 480P
    "832*480",
    "480*832",
    "624*624",
    # 720P
    "1280*720",
    "720*1280",
    "960*960",
    "1088*832",
    "832*1088",
    # 1080P
    "1920*1080",
    "1080*1920",
    "1440*1440",
    "1632*1248",
    "1248*1632",
]


class Wan2_5_T2V:
    """
    Wan 2.5 文生视频节点 - 使用阿里云百炼 DashScope VideoSynthesis API
    通过文字描述生成视频，支持音频驱动

    API文档: https://bailian.console.aliyun.com/?spm=5176.fcnext.console-base_product-drawer-right.dproducts-and-services-sfm.62952f033vAVNr&tab=api#/api/?type=model&url=2865250

    模型: wan2.5-t2v-preview
    支持功能: 文字生成视频，音频驱动，提示词扩展
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": (
                    "STRING",
                    {"multiline": True, "default": "", "tooltip": "视频生成提示词"},
                ),
            },
            "optional": {
                "api_key": (
                    "STRING",
                    {
                        "multiline": False,
                        "default": "",
                        "tooltip": ("DashScope API密钥（可选）。\n" "优先使用此处配置的密钥；若未配置，则使用环境变量 DASHSCOPE_API_KEY"),
                    },
                ),
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
                "size": (
                    SUPPORTED_SIZES,
                    {
                        "default": "1280*720",
                        "tooltip": (
                            "输出视频尺寸。"
                            "480P: 832*480/480*832/624*624; "
                            "720P: 1280*720/720*1280/960*960/1088*832/832*1088; "
                            "1080P: 1920*1080/1080*1920/1440*1440/1632*1248/1248*1632"
                        ),
                    },
                ),
                "duration": (
                    [5, 10],
                    {"default": 5, "tooltip": "视频时长（秒），可选5或10"},
                ),
                "prompt_extend": (
                    "BOOLEAN",
                    {"default": True, "tooltip": "是否扩展提示词"},
                ),
                "negative_prompt": (
                    "STRING",
                    {"multiline": True, "default": "", "tooltip": "负面提示词"},
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

    def get_temp_directory(self):
        """获取临时目录（output/temp）"""
        if FOLDER_PATHS_AVAILABLE:
            output_dir = folder_paths.get_output_directory()
        else:
            # 回退到当前目录下的 output 文件夹
            output_dir = os.path.join(os.getcwd(), "output")

        # 在 output 下创建 temp 子目录
        temp_dir = os.path.join(output_dir, "temp")
        os.makedirs(temp_dir, exist_ok=True)
        return temp_dir

    def download_video(self, url, filename_prefix="wan_t2v"):
        """下载视频到临时目录

        Args:
            url: 视频URL
            filename_prefix: 文件名前缀

        Returns:
            video_path: 保存的视频文件路径
        """
        start_time = time.time()

        # 下载视频
        print("Downloading video...")
        response = requests.get(url, timeout=120)
        response.raise_for_status()

        # 生成唯一文件名
        unique_id = uuid.uuid4().hex[:8]
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"{filename_prefix}_{timestamp}_{unique_id}.mp4"

        # 保存到临时目录
        temp_dir = self.get_temp_directory()
        video_path = os.path.join(temp_dir, filename)

        with open(video_path, "wb") as f:
            f.write(response.content)

        download_time = time.time() - start_time
        file_size_mb = len(response.content) / (1024 * 1024)
        print(f"Video download time: {download_time:.3f}s (file size: {file_size_mb:.2f}MB)")
        print(f"Video saved to temporary directory: {video_path}")

        return video_path

    def audio_to_base64(self, audio):
        """将ComfyUI的AUDIO转换为base64字符串

        ComfyUI AUDIO 格式: {"waveform": torch.Tensor, "sample_rate": int}
        waveform shape: [batch, channels, samples] 或 [channels, samples]
        """
        if not SCIPY_AVAILABLE:
            raise ImportError("scipy 未安装，无法处理音频。请运行: pip install scipy")

        start_time = time.time()

        waveform = audio["waveform"]
        sample_rate = audio["sample_rate"]

        # 处理 waveform tensor
        if len(waveform.shape) == 3:
            waveform = waveform[0]  # 取第一个 batch

        # waveform shape: [channels, samples]
        # 转换为 numpy array
        audio_array = waveform.cpu().numpy()

        # 如果是立体声，转换为 [samples, channels]
        if audio_array.shape[0] <= 2:  # channels first
            audio_array = audio_array.T  # 转置为 [samples, channels]

        # 归一化到 int16 范围
        audio_array = np.clip(audio_array * 32767, -32768, 32767).astype(np.int16)

        # 保存为 WAV 格式
        buffered = io.BytesIO()
        wavfile.write(buffered, sample_rate, audio_array)
        audio_bytes = buffered.getvalue()

        # Base64 编码
        encoded_string = base64.b64encode(audio_bytes).decode("utf-8")

        elapsed_time = time.time() - start_time
        print(f"audio_to_base64 time: {elapsed_time:.3f}s (audio size: {len(encoded_string)//1024}KB)")

        # 返回 data URI 格式
        return f"data:audio/wav;base64,{encoded_string}"

    def generate_video(
        self,
        prompt,
        api_key="",
        audio=None,
        size="832*480",
        duration=5,
        prompt_extend=True,
        negative_prompt="",
        seed=-1,
        watermark=False,
    ):
        """
        使用 DashScope Wan 2.5 模型生成视频（文生视频）
        """
        if not DASHSCOPE_AVAILABLE:
            raise ImportError("dashscope 未安装。请运行: pip install dashscope")

        if not prompt:
            raise ValueError("请提供视频生成提示词")

        # 获取 API Key：优先使用传入的参数，否则从环境变量读取
        effective_api_key = api_key if api_key else os.environ.get("DASHSCOPE_API_KEY", "")
        if not effective_api_key:
            raise ValueError("请提供 DashScope API Key。\n" "方式1：在节点中配置 api_key 参数\n" "方式2：设置环境变量 DASHSCOPE_API_KEY")

        # 设置 API Key
        dashscope.api_key = effective_api_key
        dashscope.base_http_api_url = "https://dashscope.aliyuncs.com/api/v1"

        # 准备 API 调用参数
        params = {
            "model": "wan2.5-t2v-preview",
            "prompt": prompt,
            "size": size,
            "duration": duration,
            "prompt_extend": prompt_extend,
            "watermark": watermark,
        }

        # 添加音频（如果有）
        if audio is not None:
            audio_base64 = self.audio_to_base64(audio)
            params["audio_url"] = audio_base64

        # 添加可选参数
        if negative_prompt:
            params["negative_prompt"] = negative_prompt

        if seed >= 0:
            valid_seed = seed % 2147483648
            if valid_seed != seed:
                print(f"Warning: Seed {seed} out of API range, adjusted to {valid_seed}")
            params["seed"] = valid_seed

        # ========== 步骤1: 异步调用 ==========
        print("Calling DashScope VideoSynthesis API (model: wan2.5-t2v-preview)")
        print(f"Prompt: {prompt[:100]}..." if len(prompt) > 100 else f"Prompt: {prompt}")
        print(f"Size: {size}, Duration: {duration}s")
        print(f"Audio: {'Yes' if audio is not None else 'No'}")

        rsp = VideoSynthesis.async_call(**params)

        print(f"Async call response: Task ID = {rsp.output.task_id if rsp.output else 'N/A'}")

        if rsp.status_code != HTTPStatus.OK:
            raise RuntimeError(f"API async call failed: {rsp.code} - {rsp.message}")

        task_id = rsp.output.task_id
        print(f"Task submitted! Task ID: {task_id}")

        # ========== 步骤2: 等待任务完成 ==========
        print("Waiting for video generation to complete (may take a few minutes)...")

        result = VideoSynthesis.wait(task=rsp, api_key=effective_api_key)

        print(f"Final response status: {result.status_code}")

        if result.status_code != HTTPStatus.OK:
            raise RuntimeError(f"Video generation failed: {result.code} - {result.message}")

        if not result.output or not result.output.video_url:
            print("=" * 60)
            print("API call error: Returned success but no video generated")
            print("-" * 60)
            print(f"Status Code: {result.status_code}")
            print(f"Task ID: {task_id}")
            print(f"Output: {result.output if hasattr(result, 'output') else 'N/A'}")
            print("=" * 60)
            raise RuntimeError("API returned success but no video generated")

        video_url = result.output.video_url
        print("Video generated successfully!")
        print(f"Video URL: {video_url}")

        # 打印扩展后的提示词（如果有）
        try:
            actual_prompt = result.output.actual_prompt
            if actual_prompt:
                print(f"Extended prompt: {actual_prompt[:100]}..." if len(actual_prompt) > 100 else f"Extended prompt: {actual_prompt}")
        except (KeyError, AttributeError):
            pass  # actual_prompt 不存在，跳过

        # 下载视频到临时目录
        video_path = self.download_video(video_url, filename_prefix="wan_t2v")

        # 构造 VIDEO 类型输出 (ComfyUI 官方格式)
        video_output = VideoFromFile(video_path)

        return (video_output,)
