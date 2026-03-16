"""
DashScope ImageSynthesis (文生图) 本地测试
测试 Wan 模型的文字生成图像功能

使用方式：
1. 设置环境变量：export DASHSCOPE_API_KEY='your-api-key'
2. 运行测试：python tests/manual/test_dashscope_t2i.py
"""

import os
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


def main():
    """手动测试脚本 - 文生图

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
    # 若使用新加坡地域的模型，需将url替换为：https://dashscope-intl.aliyuncs.com/api/v1
    dashscope.base_http_api_url = "https://dashscope.aliyuncs.com/api/v1"

    print("=" * 60)
    print("🚀 DashScope ImageSynthesis 文生图测试")
    print("=" * 60)
    print()

    # 测试：文生图
    print("【测试】Wan 2.5 文生图模型 (wan2.5-t2i-preview)")
    print("-" * 60)

    # 测试提示词
    prompt = "一间有着精致窗户的花店，漂亮的木质门，摆放着花朵"
    negative_prompt = ""

    print(f"📝 提示词: {prompt}")
    print(f"🚫 负面提示词: {negative_prompt or '(无)'}")
    print()

    try:
        print("⏳ 正在调用 ImageSynthesis API...")

        response = ImageSynthesis.call(
            api_key=API_KEY,
            model="wan2.5-t2i-preview",  # Wan 2.5 文生图模型
            prompt=prompt,
            negative_prompt=negative_prompt,
            n=1,  # 生成图片数量
            size="1280*1280",  # 输出尺寸（默认值）
            prompt_extend=True,  # 提示词扩展
            watermark=False,  # 不添加水印
            seed=12345,  # 随机种子，用于复现结果
        )

        print()
        print(f"📋 完整响应: {response}")
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
                output_path = f"./output_t2i_{idx}_{file_name}"

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
    print("💡 支持的参数:")
    print("   - prompt: 图像生成提示词 (必需)")
    print("   - negative_prompt: 负面提示词")
    print("   - n: 生成图片数量 (1-4)")
    print("   - size: 输出尺寸，默认 '1280*1280'")
    print("     限制: 总像素在[768*768, 1440*1440]之间，宽高比在[1:4, 4:1]之间")
    print("   - prompt_extend: 是否扩展提示词 (默认 True)")
    print("   - seed: 随机种子")
    print("   - watermark: 是否添加水印")
    print()

    print("=" * 60)
    print("🎉 测试完成!")
    print("=" * 60)


if __name__ == "__main__":
    # 直接运行此文件时执行测试
    main()
