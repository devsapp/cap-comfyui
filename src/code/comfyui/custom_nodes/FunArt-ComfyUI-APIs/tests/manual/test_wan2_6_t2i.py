"""
DashScope MultimodalConversation (文生图) - Wan 2.6 测试
测试 Wan 2.6 模型的文字生成图像功能

使用方式：
1. 设置环境变量：export DASHSCOPE_API_KEY='your-api-key'
2. 运行测试：python tests/manual/test_wan2_6_t2i.py
"""

import os
from http import HTTPStatus
from urllib.parse import urlparse, unquote
from pathlib import PurePosixPath

# 尝试导入 dashscope
try:
    import dashscope
    from dashscope import MultiModalConversation
    import requests

    DASHSCOPE_AVAILABLE = True
except ImportError:
    dashscope = None
    MultiModalConversation = None
    requests = None
    DASHSCOPE_AVAILABLE = False

# 从环境变量获取 API Key
API_KEY = os.getenv("DASHSCOPE_API_KEY")


def main():
    """手动测试脚本 - Wan 2.6 文生图

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
    # 若使用新加坡地域的模型，需将url替换为：https://dashscope-intl.aliyuncs.com/api/v1
    dashscope.base_http_api_url = "https://dashscope.aliyuncs.com/api/v1"

    print("=" * 60)
    print("🚀 DashScope Wan 2.6 文生图测试")
    print("=" * 60)
    print()

    # 测试：文生图
    print("【测试】Wan 2.6 文生图模型 (wan2.6-t2i)")
    print("-" * 60)

    # 测试提示词
    prompt = "一间有着精致窗户的花店，漂亮的木质门，摆放着花朵"
    negative_prompt = ""

    print(f"📝 提示词: {prompt}")
    print(f"🚫 负面提示词: {negative_prompt or '(无)'}")
    print()

    try:
        print("⏳ 正在调用 Wan 2.6 API...")

        # Wan 2.6 使用新的 messages 格式
        messages = [{"role": "user", "content": [{"text": prompt}]}]

        response = MultiModalConversation.call(
            api_key=API_KEY,
            model="wan2.6-t2i",  # Wan 2.6 文生图模型
            messages=messages,
            parameters={
                "prompt_extend": True,  # 提示词扩展
                "watermark": False,  # 不添加水印
                "n": 1,  # 生成图片数量
                "negative_prompt": negative_prompt,  # 负面提示词
                "size": "1280*1280",  # 输出尺寸
                "seed": 12345,  # 随机种子
            },
        )

        print()
        print(f"📋 完整响应: {response}")
        print()

        if response.status_code == HTTPStatus.OK:
            print("✅ 调用成功!")
            print(f"请求ID: {response.request_id}")
            print()

            # 检查输出格式并保存图片
            if hasattr(response.output, "choices") and response.output.choices:
                print(f"生成图片数量: {len(response.output.choices)}")

                # 保存生成的图片
                for idx, choice in enumerate(response.output.choices):
                    # Wan 2.6 的输出格式可能在 message.content 中
                    if hasattr(choice, "message") and hasattr(choice.message, "content"):
                        for content_idx, content_item in enumerate(choice.message.content):
                            try:
                                # 兼容字典和对象格式
                                image_url = None
                                if isinstance(content_item, dict):
                                    image_url = content_item.get("image")
                                else:
                                    image_url = getattr(content_item, "image", None)

                                if image_url:
                                    # 从URL中提取文件名
                                    file_name = PurePosixPath(unquote(urlparse(image_url).path)).parts[-1]
                                    output_path = f"./output_t2i_wan26_{idx}_{content_idx}_{file_name}"

                                    # 下载并保存图片
                                    print(f"📥 下载图片 {content_idx + 1}...")
                                    with open(output_path, "wb+") as f:
                                        f.write(requests.get(image_url).content)

                                    print(f"  ✅ 已保存: {output_path}")
                                    print(f"  🔗 原始URL: {image_url}")
                                    print()
                            except (AttributeError, KeyError, TypeError):
                                pass
            else:
                print("⚠️ 未找到预期的图片输出格式")
                print(f"输出内容: {response.output}")

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
    print("💡 Wan 2.6 支持的参数:")
    print("   - messages: 使用新的消息格式 (必需)")
    print("     [{'role': 'user', 'content': [{'text': '提示词'}]}]")
    print("   - parameters.prompt_extend: 是否扩展提示词 (默认 True)")
    print("   - parameters.watermark: 是否添加水印 (默认 False)")
    print("   - parameters.n: 生成图片数量 (1-4)")
    print("   - parameters.negative_prompt: 负面提示词")
    print("   - parameters.size: 输出尺寸，如 '1280*1280'")
    print("   - parameters.seed: 随机种子")
    print()

    print("🆕 Wan 2.6 主要变化:")
    print("   - 使用新的 MultiModalConversation API")
    print("   - 采用 messages 消息格式（类似聊天API）")
    print("   - 更灵活的参数配置方式")
    print()

    print("=" * 60)
    print("🎉 测试完成!")
    print("=" * 60)


if __name__ == "__main__":
    # 直接运行此文件时执行测试
    main()
