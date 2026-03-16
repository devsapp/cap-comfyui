"""
DashScope ImageSynthesis (图像生成) 本地测试
测试 Wan 模型的图像生成功能

使用方式：
1. 设置环境变量：export DASHSCOPE_API_KEY='your-api-key'
2. 运行测试：python tests/test_dashscope_image.py
"""

import os
import base64
import mimetypes
from http import HTTPStatus
from urllib.parse import urlparse, unquote
from pathlib import PurePosixPath

# 尝试导入 dashscope
try:
    import dashscope
    from dashscope import ImageSynthesis
    import requests
except ImportError:
    dashscope = None
    ImageSynthesis = None
    requests = None

# 从环境变量获取 API Key
API_KEY = os.getenv("DASHSCOPE_API_KEY")


# 工具函数：将本地图片编码为 Base64
def encode_file(file_path):
    """将本地图片文件编码为 Base64 格式

    Args:
        file_path: 图片文件路径

    Returns:
        Base64 编码的字符串，格式：data:{MIME_type};base64,{base64_data}
    """
    mime_type, _ = mimetypes.guess_type(file_path)
    if not mime_type or not mime_type.startswith("image/"):
        raise ValueError("不支持或无法识别的图像格式")

    with open(file_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode("utf-8")

    return f"data:{mime_type};base64,{encoded_string}"


def main():
    """手动测试脚本 - 图像生成

    运行前请设置环境变量：
    export DASHSCOPE_API_KEY='your-api-key'
    """
    if not dashscope:
        print("❌ 错误: dashscope 未安装")
        print("请运行: pip install dashscope requests")
        return

    if not API_KEY:
        print("❌ 错误: 未设置 DASHSCOPE_API_KEY")
        print("\n设置方法:")
        print("  export DASHSCOPE_API_KEY='your-api-key'")
        print("\n获取API Key:")
        print("  https://dashscope.console.aliyun.com/apiKey")
        return

    dashscope.api_key = API_KEY
    # 设置为北京地域URL
    dashscope.base_http_api_url = "https://dashscope.aliyuncs.com/api/v1"

    print("=" * 60)
    print("🚀 DashScope ImageSynthesis 图像生成测试")
    print("=" * 60)
    print()

    # 测试：图像生成（图生图）
    print("【测试】Wan 2.5 图生图模型")
    print("-" * 60)

    # 图片输入方式说明
    print("\n📌 图片输入方式（三选一）：")
    print("1. 公网URL  - 使用公开可访问的图片链接")
    print("2. 本地文件 - file://path/to/image.png")
    print("3. Base64   - encode_file('path/to/image.png')")
    print()

    # 使用公网URL方式（默认）
    image_url_1 = "https://img.alicdn.com/imgextra/i3/O1CN0157XGE51l6iL9441yX_!!6000000004770-49-tps-1104-1472.webp"
    image_url_2 = "https://img.alicdn.com/imgextra/i3/O1CN01SfG4J41UYn9WNt4X1_!!6000000002530-49-tps-1696-960.webp"

    print("📷 输入图片:")
    print(f"  图1: {image_url_1}")
    print(f"  图2: {image_url_2}")
    print()

    try:
        print("⏳ 正在调用 ImageSynthesis API...")

        response = ImageSynthesis.call(
            api_key=API_KEY,
            model="wan2.5-i2i-preview",  # Wan 2.5 图生图模型
            prompt="将图1中的闹钟放置到图2的餐桌的花瓶旁边位置",
            images=[image_url_1, image_url_2],
            negative_prompt="",  # 负面提示词
            n=1,  # 生成图片数量
            # size="1280*1280",  # 可选：指定输出尺寸
            watermark=False,  # 不添加水印
            seed=12345,  # 随机种子，用于复现结果
        )

        print()
        if response.status_code == HTTPStatus.OK:
            print("✅ 调用成功!")
            print(f"请求ID: {response.request_id}")
            print(f"生成图片数量: {len(response.output.results)}")
            print()

            # 保存生成的图片
            for idx, result in enumerate(response.output.results):
                # 从URL中提取文件名
                file_name = PurePosixPath(unquote(urlparse(result.url).path)).parts[-1]
                output_path = f"./output_wan_{idx}_{file_name}"

                # 下载并保存图片
                print(f"📥 下载图片 {idx + 1}...")
                with open(output_path, "wb+") as f:
                    f.write(requests.get(result.url).content)

                print(f"  ✅ 已保存: {output_path}")
                print(f"  🔗 原始URL: {result.url}")
                print()

        else:
            print("❌ 调用失败")
            print(f"状态码: {response.status_code}")
            print(f"错误码: {response.code}")
            print(f"错误信息: {response.message}")

    except Exception as e:
        print(f"❌ 发生异常: {str(e)}")
        import traceback

        traceback.print_exc()

    print("-" * 60)
    print()

    # 补充说明
    print("💡 使用提示:")
    print("1. 如需使用本地图片，请使用: file://path/to/image.png")
    print("2. 如需Base64编码，使用: encode_file('path/to/image.png')")
    print("3. 支持的参数:")
    print("   - prompt: 图像生成提示词")
    print("   - negative_prompt: 负面提示词")
    print("   - n: 生成图片数量 (1-4)")
    print("   - size: 输出尺寸，如 '1024*1024'")
    print("   - seed: 随机种子")
    print("   - watermark: 是否添加水印")
    print()

    print("=" * 60)
    print("🎉 测试完成!")
    print("=" * 60)


if __name__ == "__main__":
    # 直接运行此文件时执行测试
    main()
