"""
DashScope ImageSynthesis (图像生成) - Wan 2.6 异步调用测试
测试 Wan 2.6 模型的图像生成和图文混排功能（异步模式）

使用方式：
1. 设置环境变量：export DASHSCOPE_API_KEY='your-api-key'
2. 运行测试：python tests/manual/test_wan2_6_image_edit.py
"""

import os
import base64
import mimetypes
from urllib.parse import urlparse, unquote
from pathlib import PurePosixPath

# 尝试导入 dashscope
try:
    import dashscope
    from dashscope.aigc.image_generation import ImageGeneration
    from dashscope.api_entities.dashscope_response import Message
    import requests
    from http import HTTPStatus

    DASHSCOPE_AVAILABLE = True
except ImportError:
    dashscope = None
    ImageGeneration = None
    Message = None
    requests = None
    DASHSCOPE_AVAILABLE = False

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


def test_image_editing():
    """测试1: 图像编辑 - 参考多张图片生成新图片"""
    print("\n" + "=" * 60)
    print("【测试1】Wan 2.6 图像编辑 - 参考风格和背景")
    print("=" * 60)
    print()

    # 测试参数
    image_url_1 = "https://cdn.wanx.aliyuncs.com/tmp/pressure/umbrella1.png"
    image_url_2 = "https://img.alicdn.com/imgextra/i3/O1CN01SfG4J41UYn9WNt4X1_!!6000000002530-49-tps-1696-960.webp"
    prompt = "参考图1的风格和图2的背景，生成番茄炒蛋"

    print(f"📝 提示词: {prompt}")
    print(f"📷 参考图1: {image_url_1}")
    print(f"📷 参考图2: {image_url_2}")
    print()

    try:
        # ========== 步骤1: 异步调用 ==========
        print("⏳ 步骤1: 异步调用 ImageGeneration API...")

        # 构建 Message
        message = Message(role="user", content=[{"text": prompt}, {"image": image_url_1}, {"image": image_url_2}])

        # 异步调用
        rsp = ImageGeneration.async_call(
            model="wan2.6-image",
            api_key=API_KEY,
            messages=[message],
            prompt_extend=True,
            watermark=False,
            n=1,
            enable_interleave=False,
            size="1280*1280",
        )

        print(f"📋 异步调用响应: {rsp}")
        print()

        if rsp.status_code != HTTPStatus.OK:
            print("❌ 异步调用失败")
            print(f"状态码: {rsp.status_code}")
            print(f"错误码: {rsp.code}")
            print(f"错误信息: {rsp.message}")
            return

        task_id = rsp.output.task_id
        print(f"✅ 异步调用成功! Task ID: {task_id}")
        print()

        # ========== 步骤2: 等待任务完成 ==========
        print("⏳ 步骤2: 等待任务完成 (图像生成中)...")

        result = ImageGeneration.wait(task=rsp, api_key=API_KEY)

        print()
        print(f"📋 最终响应: {result}")
        print()

        if result.status_code == HTTPStatus.OK:
            print("✅ 图像生成成功!")

            # ========== 打印完整的任务信息（用于计费和审计）==========
            print()
            print("=" * 60)
            print("📋 完整任务信息 (用于计费和审计)")
            print("=" * 60)

            # 基础任务信息
            print(f"Task ID: {result.output.task_id}")
            print(f"Task Status: {result.output.task_status}")
            print(f"Request ID: {result.request_id if hasattr(result, 'request_id') else 'N/A'}")

            # 时间信息
            if hasattr(result.output, "submit_time"):
                print(f"Submit Time: {result.output.submit_time}")
            if hasattr(result.output, "scheduled_time"):
                print(f"Scheduled Time: {result.output.scheduled_time}")
            if hasattr(result.output, "end_time"):
                print(f"End Time: {result.output.end_time}")

            # 💰 计费信息（重要）
            if hasattr(result, "usage") and result.usage:
                print("\n💰 Usage Information (计费信息):")
                usage = result.usage
                try:
                    image_count = getattr(usage, "image_count")
                    if image_count or image_count == 0:
                        print(f"  image_count: {image_count}")
                except (AttributeError, KeyError):
                    pass

            print("=" * 60)
            print()

            # 从 choices[0].message.content 中提取图片
            choice = result.output.choices[0]
            # 使用安全的方式筛选图片（兼容字典和对象格式）
            images = []
            for item in choice.message.content:
                try:
                    img_url = None
                    if isinstance(item, dict):
                        img_url = item.get("image")
                    else:
                        img_url = getattr(item, "image", None)

                    if img_url:
                        images.append(item)
                except (AttributeError, KeyError, TypeError):
                    pass

            print(f"生成图片数量: {len(images)}")
            print()

            for idx, img_item in enumerate(images):
                # 兼容字典和对象格式
                img_url = img_item.get("image") if isinstance(img_item, dict) else img_item.image
                # 从URL中提取文件名
                file_name = PurePosixPath(unquote(urlparse(img_url).path)).parts[-1]
                output_path = f"./output_wan26_edit_{idx}_{file_name}"

                # 下载并保存图片
                print(f"📥 下载图片 {idx + 1}...")
                with open(output_path, "wb+") as f:
                    f.write(requests.get(img_url).content)

                print(f"  ✅ 已保存: {output_path}")
                print(f"  🔗 原始URL: {img_url}")
                print()
        else:
            print("❌ 图像生成失败")
            print(f"状态码: {result.status_code}")
            print(f"错误码: {result.code}")
            print(f"错误信息: {result.message}")

    except Exception as e:
        print(f"❌ 发生异常: {str(e)}")
        import traceback

        traceback.print_exc()


def test_interleaved_output():
    """测试2: 图文混排 - 生成多张图片作为教程"""
    print("\n" + "=" * 60)
    print("【测试2】Wan 2.6 图文混排 - 多图教程生成")
    print("=" * 60)
    print()

    # 测试参数
    prompt = "给我一个3张图辣椒炒肉教程"

    print(f"📝 提示词: {prompt}")
    print("🎬 生成模式: 图文混排 (max_images=3)")
    print()

    try:
        # ========== 步骤1: 异步调用 ==========
        print("⏳ 步骤1: 异步调用 ImageGeneration API (图文混排模式)...")

        # 构建 Message
        message = Message(role="user", content=[{"text": prompt}])

        # 异步调用
        rsp = ImageGeneration.async_call(
            model="wan2.6-image",
            api_key=API_KEY,
            messages=[message],
            size="1280*1280",
            enable_interleave=True,  # 启用图文混排
            max_images=3,  # 最大生成3张图
        )

        print(f"📋 异步调用响应: {rsp}")
        print()

        if rsp.status_code != HTTPStatus.OK:
            print("❌ 异步调用失败")
            print(f"状态码: {rsp.status_code}")
            print(f"错误码: {rsp.code}")
            print(f"错误信息: {rsp.message}")
            return

        task_id = rsp.output.task_id
        print(f"✅ 异步调用成功! Task ID: {task_id}")
        print()

        # ========== 步骤2: 等待任务完成 ==========
        print("⏳ 步骤2: 等待任务完成 (多图生成中)...")
        print("💡 提示: 图文混排模式会生成多张相关图片")
        print()

        result = ImageGeneration.wait(task=rsp, api_key=API_KEY)

        print()
        print(f"📋 最终响应: {result}")
        print()

        if result.status_code == HTTPStatus.OK:
            print("✅ 多图生成成功!")

            # ========== 打印完整的任务信息（用于计费和审计）==========
            print()
            print("=" * 60)
            print("📋 完整任务信息 (用于计费和审计)")
            print("=" * 60)

            # 基础任务信息
            print(f"Task ID: {result.output.task_id}")
            print(f"Task Status: {result.output.task_status}")
            print(f"Request ID: {result.request_id if hasattr(result, 'request_id') else 'N/A'}")

            # 时间信息
            if hasattr(result.output, "submit_time"):
                print(f"Submit Time: {result.output.submit_time}")
            if hasattr(result.output, "scheduled_time"):
                print(f"Scheduled Time: {result.output.scheduled_time}")
            if hasattr(result.output, "end_time"):
                print(f"End Time: {result.output.end_time}")

            # 💰 计费信息（重要）
            if hasattr(result, "usage") and result.usage:
                print("\n💰 Usage Information (计费信息):")
                usage = result.usage
                try:
                    image_count = getattr(usage, "image_count")
                    if image_count or image_count == 0:
                        print(f"  image_count: {image_count}")
                except (AttributeError, KeyError):
                    pass

            print("=" * 60)
            print()

            # 从 choices[0].message.content 中提取图片和文本
            choice = result.output.choices[0]

            # 筛选出图片和文本（兼容字典和对象格式）
            images = []
            texts = []
            for item in choice.message.content:
                try:
                    if isinstance(item, dict):
                        if item.get("image"):
                            images.append(item)
                        elif item.get("text"):
                            texts.append(item)
                    else:
                        if getattr(item, "image", None):
                            images.append(item)
                        elif getattr(item, "text", None):
                            texts.append(item)
                except (AttributeError, KeyError, TypeError):
                    pass

            print(f"生成图片数量: {len(images)}")
            print(f"生成文本段落: {len(texts)}")
            print()

            # 保存生成的图片
            for idx, img_item in enumerate(images):
                # 兼容字典和对象格式
                img_url = img_item.get("image") if isinstance(img_item, dict) else img_item.image
                # 从URL中提取文件名
                file_name = PurePosixPath(unquote(urlparse(img_url).path)).parts[-1]
                output_path = f"./output_wan26_interleave_{idx}_{file_name}"

                # 下载并保存图片
                print(f"📥 下载图片 {idx + 1}...")
                with open(output_path, "wb+") as f:
                    f.write(requests.get(img_url).content)

                print(f"  ✅ 已保存: {output_path}")
                print(f"  🔗 原始URL: {img_url}")
                print()

            # 显示部分文本内容
            if texts:
                print("📄 生成的教程文本片段:")
                for idx, text_item in enumerate(texts[:2]):  # 只显示前2段
                    # 兼容字典和对象格式
                    text_content = text_item.get("text") if isinstance(text_item, dict) else text_item.text
                    print(f"  段落{idx+1}: {text_content[:100]}...")
                print()

            print("🎯 图文混排说明: 生成的图片按顺序展示了教程的各个步骤")
        else:
            print("❌ 图像生成失败")
            print(f"状态码: {result.status_code}")
            print(f"错误码: {result.code}")
            print(f"错误信息: {result.message}")

    except Exception as e:
        print(f"❌ 发生异常: {str(e)}")
        import traceback

        traceback.print_exc()


def main():
    """手动测试脚本 - Wan 2.6 图像生成（异步模式）

    运行前请设置环境变量：
    export DASHSCOPE_API_KEY='your-api-key'
    """
    if not DASHSCOPE_AVAILABLE:
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
    print("🚀 DashScope Wan 2.6 图像生成测试（异步模式）")
    print("=" * 60)

    # 运行测试1：图像编辑
    test_image_editing()

    # 运行测试2：图文混排
    test_interleaved_output()

    # 补充说明
    print("\n" + "=" * 60)
    print("💡 Wan 2.6 图像生成说明")
    print("=" * 60)
    print()
    print("🆕 主要特性:")
    print("   1. 异步调用: 使用 async_call + fetch + wait")
    print("   2. 多图参考: 传入 images 列表支持多张图片")
    print("   3. 图文混排: enable_interleave=True + max_images=N")
    print("   4. 更灵活的生成: 支持教程、步骤等多图输出")
    print()
    print("📝 支持的参数:")
    print("   图像编辑模式:")
    print("     - prompt: 文本提示词（必需）")
    print("     - images: 参考图片列表 [url1, url2, ...]")
    print("     - prompt_extend: 是否扩展提示词")
    print("     - watermark: 是否添加水印")
    print("     - n: 生成图片数量")
    print("     - size: 输出尺寸")
    print()
    print("   图文混排模式:")
    print("     - prompt: 文本提示词（必需）")
    print("     - enable_interleave: 启用图文混排 (True)")
    print("     - max_images: 最大图片数量 (如 3)")
    print("     - size: 输出尺寸")
    print()
    print("🎯 使用场景:")
    print("   - 图像编辑: 参考多张图片的风格/背景生成新图")
    print("   - 图文混排: 生成多张图片作为教程/步骤说明")
    print("   - 风格迁移: 将某种风格应用到特定场景")
    print()

    print("=" * 60)
    print("🎉 测试完成!")
    print("=" * 60)


if __name__ == "__main__":
    # 直接运行此文件时执行测试
    main()
