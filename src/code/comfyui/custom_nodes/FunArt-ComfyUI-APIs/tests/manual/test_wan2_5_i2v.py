"""
DashScope VideoSynthesis (图生视频) 本地测试
测试 Wan 模型的首帧图生视频功能

使用方式：
1. 设置环境变量：export DASHSCOPE_API_KEY='your-api-key'
2. 运行测试：python tests/manual/test_dashscope_i2v.py
"""

import os
from http import HTTPStatus

# 尝试导入 dashscope
try:
    import dashscope
    from dashscope import VideoSynthesis

    DASHSCOPE_AVAILABLE = True
except ImportError:
    dashscope = None
    VideoSynthesis = None
    DASHSCOPE_AVAILABLE = False

# 从环境变量获取 API Key
API_KEY = os.getenv("DASHSCOPE_API_KEY")


def main():
    """手动测试脚本 - 图生视频 (I2V)

    运行前请设置环境变量：
    export DASHSCOPE_API_KEY='your-api-key'
    """
    if not DASHSCOPE_AVAILABLE:
        print("❌ 错误: dashscope 未安装")
        print("请运行: pip install dashscope")
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
    print("🚀 DashScope VideoSynthesis 图生视频测试")
    print("=" * 60)
    print()

    # 测试：图生视频
    print("【测试】Wan 2.5 图生视频模型 (wan2.5-i2v-preview)")
    print("-" * 60)

    # 测试参数
    img_url = "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20250925/wpimhv/rap.png"
    audio_url = "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20250925/ozwpvi/rap.mp3"
    prompt = "一幅都市奇幻艺术的场景。一个充满动感的涂鸦艺术角色。一个由喷漆所画成的少年，正从一面混凝土墙上活过来。他一边用极快的语速演唱一首英文rap，一边摆着一个经典的、充满活力的说唱歌手姿势。场景设定在夜晚一个充满都市感的铁路桥下。灯光来自一盏孤零零的街灯，营造出电影般的氛围，充满高能量和惊人的细节。视频的音频部分完全由少年的rap构成，没有其他对话或杂音。"

    print(f"🖼️  首帧图片: {img_url}")
    print(f"🎵 音频URL: {audio_url}")
    print(f"📝 提示词: {prompt[:50]}...")
    print()

    try:
        # ========== 步骤1: 异步调用 ==========
        print("⏳ 步骤1: 异步调用 VideoSynthesis API...")

        rsp = VideoSynthesis.async_call(
            api_key=API_KEY,
            model="wan2.5-i2v-preview",  # Wan 2.5 图生视频模型
            prompt=prompt,
            img_url=img_url,
            audio_url=audio_url,
            resolution="480P",  # 分辨率: 480P / 720P
            duration=5,  # 视频时长（秒）
            prompt_extend=True,  # 提示词扩展
            watermark=False,  # 不添加水印
            negative_prompt="",  # 负面提示词
            seed=12345,  # 随机种子
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

        # ========== 步骤2: 查询任务状态 ==========
        print("⏳ 步骤2: 查询任务状态...")

        status = VideoSynthesis.fetch(task=rsp, api_key=API_KEY)

        if status.status_code == HTTPStatus.OK:
            print(f"📊 任务状态: {status.output.task_status}")
        else:
            print(f"❌ 查询失败: {status.code} - {status.message}")
        print()

        # ========== 步骤3: 等待任务完成 ==========
        print("⏳ 步骤3: 等待任务完成 (视频生成中，可能需要几分钟)...")

        result = VideoSynthesis.wait(task=rsp, api_key=API_KEY)

        print()
        print(f"📋 最终响应: {result}")
        print()

        if result.status_code == HTTPStatus.OK:
            print("✅ 视频生成成功!")
            print(f"🎬 视频URL: {result.output.video_url}")
            print()
            print("💡 提示: 请复制上方URL到浏览器查看/下载视频")
        else:
            print("❌ 视频生成失败")
            print(f"状态码: {result.status_code}")
            print(f"错误码: {result.code}")
            print(f"错误信息: {result.message}")

    except Exception as e:
        print(f"❌ 发生异常: {str(e)}")
        import traceback

        traceback.print_exc()

    print("-" * 60)
    print()

    # 补充说明
    print("💡 支持的参数:")
    print("   - prompt: 视频生成提示词 (必需)")
    print("   - img_url: 首帧图片URL (必需)")
    print("   - audio_url: 音频URL (可选，用于音频驱动)")
    print("   - resolution: 分辨率 '480P' 或 '720P'")
    print("   - duration: 视频时长（秒）")
    print("   - prompt_extend: 是否扩展提示词 (默认 True)")
    print("   - negative_prompt: 负面提示词")
    print("   - seed: 随机种子")
    print("   - watermark: 是否添加水印")
    print()

    print("=" * 60)
    print("🎉 测试完成!")
    print("=" * 60)


if __name__ == "__main__":
    # 直接运行此文件时执行测试
    main()
