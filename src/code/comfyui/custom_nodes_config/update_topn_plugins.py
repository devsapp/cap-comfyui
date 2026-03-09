#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
获取 ComfyUI Top N 插件列表并保存

用法：
    python update_topn_plugins.py 200
    python update_topn_plugins.py 50 --output custom_nodes_top50.json
"""

import json
import sys
import argparse
from datetime import datetime
from pathlib import Path


def load_existing_plugins(file_path: str) -> list:
    """
    加载现有的插件列表（包含 stars 数据）
    支持两种格式：
    1. custom_nodes 数组格式（旧格式）
    2. node_packs 对象格式（新的官方格式）
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
            # 格式1：custom_nodes 数组格式（旧格式）
            if 'custom_nodes' in data:
                return data.get('custom_nodes', [])
            
            # 格式2：node_packs 对象格式（ComfyUI Manager 官方格式）
            elif 'node_packs' in data:
                node_packs = data.get('node_packs', {})
                plugins = []
                
                for plugin_id, plugin_info in node_packs.items():
                    # 转换为统一格式
                    plugin = {
                        'id': plugin_info.get('id', plugin_id),
                        'name': plugin_info.get('title', plugin_id),
                        'repository': plugin_info.get('repository') or plugin_info.get('reference', ''),
                        'version': plugin_info.get('version', 'latest'),
                        'stars': plugin_info.get('stars', 0),
                        'enabled': True,
                        'description': plugin_info.get('description', ''),
                        'author': plugin_info.get('author', ''),
                        'last_update': plugin_info.get('last_update', '')
                    }
                    plugins.append(plugin)
                
                print(f"✅ 成功从 node_packs 格式转换 {len(plugins)} 个插件")
                return plugins
            
            else:
                print(f"❌ 未知的文件格式，需要 'custom_nodes' 或 'node_packs' 字段")
                return []
                
    except FileNotFoundError:
        print(f"❌ 文件不存在: {file_path}")
        return []
    except json.JSONDecodeError as e:
        print(f"❌ JSON 解析错误: {e}")
        return []


def extract_topn_plugins(plugins: list, n: int) -> list:
    """
    从插件列表中提取 Top N 的插件
    
    Args:
        plugins: 插件列表
        n: 提取的数量
    
    Returns:
        Top N 插件列表
    """
    # 过滤出有 stars 数据的插件
    plugins_with_stars = [p for p in plugins if p.get('stars', 0) > 0]
    
    # 按 stars 降序排序
    sorted_plugins = sorted(
        plugins_with_stars,
        key=lambda x: x.get('stars', 0),
        reverse=True
    )
    
    # 取前 N 个
    return sorted_plugins[:n]


def save_plugins(plugins: list, output_file: str, topn: int, source_file: str):
    """
    保存插件列表到文件
    
    Args:
        plugins: 插件列表
        output_file: 输出文件路径
        topn: Top N 数量
        source_file: 源文件名
    """
    output_data = {
        "metadata": {
            "description": f"Top {topn} ComfyUI custom nodes sorted by GitHub stars",
            "total_plugins": len(plugins),
            "source": source_file,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "min_stars": plugins[-1]['stars'] if plugins else 0,
            "max_stars": plugins[0]['stars'] if plugins else 0
        },
        "custom_nodes": plugins
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"✅ 成功保存 {len(plugins)} 个插件到: {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description='获取 ComfyUI Top N 插件列表',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  %(prog)s 50                                    # 获取 top 50，保存到默认文件
  %(prog)s 200 --output top200.json             # 获取 top 200，自定义文件名
  %(prog)s 100 --source custom_nodes.json       # 从指定源文件获取
        """
    )
    
    parser.add_argument(
        'n',
        type=int,
        help='Top N 数量（如: 50, 100, 200）'
    )
    
    parser.add_argument(
        '--output',
        type=str,
        default=None,
        help='输出文件名（默认: custom_nodes_topn_YYYYMMDD.json）'
    )
    
    parser.add_argument(
        '--source',
        type=str,
        default='comfyui_manager_official_list.json',
        help='源数据文件（默认: comfyui_manager_official_list.json）'
    )
    
    args = parser.parse_args()
    
    # 获取脚本所在目录
    script_dir = Path(__file__).parent
    
    # 源文件路径
    source_file = script_dir / args.source
    
    print(f"📂 从文件加载插件列表: {source_file}")
    
    # 加载现有插件列表
    plugins = load_existing_plugins(str(source_file))
    
    if not plugins:
        print("❌ 没有找到有效的插件数据")
        sys.exit(1)
    
    print(f"📊 源文件包含: {len(plugins)} 个插件")
    
    # 统计有 stars 数据的插件数量
    plugins_with_stars = [p for p in plugins if p.get('stars', 0) > 0]
    print(f"📊 其中有 stars 数据的: {len(plugins_with_stars)} 个插件")
    
    # 提取 Top N
    topn_plugins = extract_topn_plugins(plugins, args.n)
    
    if len(topn_plugins) < args.n:
        print(f"⚠️  警告: 请求 top {args.n}，但只找到 {len(topn_plugins)} 个有 stars 数据的插件")
        print(f"💡 提示: 当前源文件最多支持 {len(plugins_with_stars)} 个插件")
        
        if args.n > len(plugins_with_stars):
            print(f"\n💡 建议：将 n 设置为 <= {len(plugins_with_stars)}")
    
    # 生成输出文件名
    if args.output:
        output_file = script_dir / args.output
    else:
        date_str = datetime.now().strftime("%Y%m%d")
        output_file = script_dir / f"custom_nodes_top{args.n}_{date_str}.json"
    
    # 保存结果
    save_plugins(topn_plugins, str(output_file), args.n, args.source)
    
    # 输出统计信息
    print("\n" + "=" * 60)
    print("📊 Top N 插件统计信息")
    print("=" * 60)
    
    if topn_plugins:
        print(f"排名 #1: {topn_plugins[0]['name']} ({topn_plugins[0]['stars']:,} stars)")
        if len(topn_plugins) >= 10:
            print(f"排名 #10: {topn_plugins[9]['name']} ({topn_plugins[9]['stars']:,} stars)")
        if len(topn_plugins) >= 50:
            print(f"排名 #50: {topn_plugins[49]['name']} ({topn_plugins[49]['stars']:,} stars)")
        print(f"排名 #{len(topn_plugins)}: {topn_plugins[-1]['name']} ({topn_plugins[-1]['stars']:,} stars)")
    
    print("\n✅ 任务完成！")


if __name__ == '__main__':
    main()
