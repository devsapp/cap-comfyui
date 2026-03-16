"""
DashScope VideoSynthesis (图生视频) - Wan 2.6 多镜头叙事测试
测试 Wan 2.6 模型的首帧图生视频 + 多镜头叙事功能

使用方式：
1. 设置环境变量：export DASHSCOPE_API_KEY='your-api-key'
2. 运行测试：python tests/manual/test_wan2_6_i2v.py
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
    """手动测试脚本 - Wan 2.6 图生视频 + 多镜头叙事 (I2V Multi-Shot)

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
    print("🚀 DashScope VideoSynthesis Wan 2.6 多镜头叙事测试")
    print("=" * 60)
    print()

    # 测试：图生视频 + 多镜头叙事
    print("【测试】Wan 2.6 图生视频模型 (wan2.6-i2v-flash)")
    print("【功能】多镜头叙事 (Multi-Shot Narrative)")
    print("-" * 60)

    # 测试参数
    img_url = "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20250925/wpimhv/rap.png"
    audio_url = "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20250925/ozwpvi/rap.mp3"
    prompt = "一幅都市奇幻艺术的场景。一个充满动感的涂鸦艺术角色。一个由喷漆所画成的少年，正从一面混凝土墙上活过来。他一边用极快的语速演唱一首英文rap，一边摆着一个经典的、充满活力的说唱歌手姿势。场景设定在夜晚一个充满都市感的铁路桥下。灯光来自一盏孤零零的街灯，营造出电影般的氛围，充满高能量和惊人的细节。视频的音频部分完全由少年的rap构成，没有其他对话或杂音。"

    print(f"🖼️  首帧图片: {img_url}")
    print(f"🎵 音频URL: {audio_url}")
    print(f"📝 提示词: {prompt[:50]}...")
    print("🎬 镜头类型: multi (多镜头叙事)")
    print()

    try:
        # ========== 步骤1: 异步调用 ==========
        print("⏳ 步骤1: 异步调用 VideoSynthesis API...")

        rsp = VideoSynthesis.async_call(
            api_key=API_KEY,
            model="wan2.6-i2v-flash",  # Wan 2.6 图生视频模型
            prompt=prompt,
            img_url=img_url,
            audio_url=audio_url,
            resolution="720P",  # 分辨率: 480P / 720P
            duration=10,  # 视频时长（秒），Wan 2.6 支持更长时长
            prompt_extend=True,  # 提示词扩展
            shot_type="multi",  # 🆕 多镜头叙事模式 (single/multi)
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
        print("⏳ 步骤3: 等待任务完成 (多镜头视频生成中，可能需要几分钟)...")
        print("💡 提示: 多镜头模式会生成包含多个场景切换的视频")

        result = VideoSynthesis.wait(task=rsp, api_key=API_KEY)

        print()
        print(f"📋 最终响应: {result}")
        print()

        if result.status_code == HTTPStatus.OK:
            print("✅ 多镜头视频生成成功!")
            print(f"🎬 视频URL: {result.output.video_url}")
            print()

            # ========== 打印完整的任务信息（用于计费和审计）==========
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

            # 原始提示词
            if hasattr(result.output, "orig_prompt"):
                orig_prompt = result.output.orig_prompt
                print(f"Original Prompt: {orig_prompt[:100]}..." if len(orig_prompt) > 100 else f"Original Prompt: {orig_prompt}")

            # 💰 计费信息（重要）
            if hasattr(result, "usage") and result.usage:
                print("\n💰 Usage Information (计费信息):")
                usage = result.usage
                for attr in ["video_count", "duration", "input_video_duration", "output_video_duration", "video_ratio", "SR", "audio"]:
                    try:
                        value = getattr(usage, attr)
                        if value or value == 0:
                            print(f"  {attr}: {value}")
                    except (AttributeError, KeyError):
                        pass

            print("=" * 60)
            print()

            print("💡 提示: 请复制上方URL到浏览器查看/下载视频")
            print("🎥 视频特点: 包含多个镜头切换，具有电影般的叙事效果")
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
    print("💡 Wan 2.6 支持的参数:")
    print("   - prompt: 视频生成提示词 (必需)")
    print("   - img_url: 首帧图片URL (必需)")
    print("   - audio_url: 音频URL (可选，用于音频驱动)")
    print("   - resolution: 分辨率 '480P' 或 '720P'")
    print("   - duration: 视频时长（秒），支持更长时长")
    print("   - shot_type: 🆕 镜头类型 'single'(单镜头) 或 'multi'(多镜头)")
    print("   - prompt_extend: 是否扩展提示词 (默认 True)")
    print("   - negative_prompt: 负面提示词")
    print("   - seed: 随机种子")
    print("   - watermark: 是否添加水印")
    print()

    print("🎬 多镜头叙事说明:")
    print("   - single: 单镜头模式，视角固定")
    print("   - multi: 多镜头模式，自动生成多个场景切换")
    print("   - 多镜头模式适合故事性强的内容，增强叙事效果")
    print()

    print("=" * 60)
    print("🎉 测试完成!")
    print("=" * 60)


if __name__ == "__main__":
    # 直接运行此文件时执行测试
    main()
