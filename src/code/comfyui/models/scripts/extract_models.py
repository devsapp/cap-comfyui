#!/usr/bin/env python3
"""
从 templates 目录的 ComfyUI JSON 文件中提取模型信息

功能：
- 扫描 templates 目录下所有 JSON 文件
- 提取模型名称、下载地址、存储目录
- 输出为 models_{date}.json 格式

使用方法：
    python3 extract_models.py
    python3 extract_models.py --templates-dir ../workflow_templates/templates
"""

import json
import os
import re
from datetime import datetime
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple
import argparse


def extract_url_with_balanced_parens(text: str, start_pos: int) -> Tuple[str, int]:
    """提取URL，处理平衡的括号"""
    depth = 1
    pos = start_pos
    while pos < len(text) and depth > 0:
        char = text[pos]
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
            if depth == 0:
                break
        elif char in ' \t\n\r':
            break
        pos += 1
    return text[start_pos:pos], pos


def find_markdown_links(obj, links_list):
    """递归查找所有markdown链接"""
    if isinstance(obj, dict):
        for v in obj.values():
            find_markdown_links(v, links_list)
    elif isinstance(obj, list):
        for v in obj:
            find_markdown_links(v, links_list)
    elif isinstance(obj, str):
        # Markdown链接格式: [filename.safetensors](url)
        pattern = r'\[([^\]]+?\.(?:safetensors|ckpt|pt|pth|bin))\]\('
        for match in re.finditer(pattern, obj):
            text_name = match.group(1)
            start_pos = match.end()
            url, _ = extract_url_with_balanced_parens(obj, start_pos)
            links_list.append({
                'name': text_name,
                'url': url
            })


def get_model_directory(node_type: str, file_name: str = '') -> str:
    """根据节点类型和文件名确定模型存储目录"""
    node_type_lower = node_type.lower()
    file_name_lower = file_name.lower()
    
    # 基于节点类型的映射
    if 'unet' in node_type_lower:
        return 'unet'
    elif 'vae' in node_type_lower:
        return 'vae'
    elif 'clip' in node_type_lower:
        if 'vision' in node_type_lower:
            return 'clip_vision'
        return 'clip'
    elif 'lora' in node_type_lower:
        return 'loras'
    elif 'checkpoint' in node_type_lower:
        return 'checkpoints'
    elif 'controlnet' in node_type_lower:
        return 'controlnet'
    elif 'upscale' in node_type_lower or 'upscaler' in node_type_lower:
        return 'upscale_models'
    elif 'audio' in node_type_lower:
        return 'audio'
    elif 'sam' in node_type_lower or 'sam2' in node_type_lower:
        return 'sams'
    elif 'style' in node_type_lower:
        return 'style_models'
    
    # 基于文件名的推断
    if 'lora' in file_name_lower:
        return 'loras'
    elif 'vae' in file_name_lower:
        return 'vae'
    elif 'controlnet' in file_name_lower or 'control' in file_name_lower:
        return 'controlnet'
    elif 'upscale' in file_name_lower:
        return 'upscale_models'
    
    return 'unknown'


def analyze_template_file(file_path: str) -> Dict:
    """分析单个模板文件"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        return {'error': str(e)}
    
    result = {
        'file': os.path.basename(file_path),
        'models': []
    }
    
    # 提取所有markdown链接
    markdown_links = []
    find_markdown_links(data, markdown_links)
    
    # 创建URL查找字典
    url_map = {link['name']: link['url'] for link in markdown_links}
    
    # 分析节点
    nodes = data.get('nodes', [])
    for node in nodes:
        node_type = node.get('type', '')
        node_id = node.get('id', '')
        widgets_values = node.get('widgets_values', [])
        
        # 跳过 MarkdownNote 节点（它们只是文档说明）
        if node_type.lower() in ['markdownnote', 'note']:
            continue
        
        # 查找所有包含模型文件的widgets_values
        for widget_value in widgets_values:
            if isinstance(widget_value, str) and any(ext in widget_value for ext in ['.safetensors', '.ckpt', '.pt', '.pth', '.bin']):
                model_dir = get_model_directory(node_type, widget_value)
                url = url_map.get(widget_value, '')
                
                result['models'].append({
                    'name': widget_value,
                    'url': url,
                    'directory': model_dir,
                    'node_type': node_type
                })
    
    return result


def analyze_all_templates(templates_dir: str) -> Dict:
    """分析所有模板文件"""
    all_models = defaultdict(lambda: {
        'url': '',
        'directory': '',
        'node_types': set(),
        'used_in_templates': []
    })
    
    template_files = []
    for filename in sorted(os.listdir(templates_dir)):
        if filename.endswith('.json') and not filename.startswith('index.'):
            template_files.append(filename)
    
    print(f"找到 {len(template_files)} 个模板文件")
    
    for filename in template_files:
        file_path = os.path.join(templates_dir, filename)
        result = analyze_template_file(file_path)
        
        if 'error' in result:
            print(f"⚠️  处理 {filename} 时出错: {result['error']}")
            continue
        
        for model in result['models']:
            model_name = model['name']
            if not all_models[model_name]['url'] and model['url']:
                all_models[model_name]['url'] = model['url']
            if not all_models[model_name]['directory'] and model['directory']:
                all_models[model_name]['directory'] = model['directory']
            all_models[model_name]['node_types'].add(model['node_type'])
            if filename not in all_models[model_name]['used_in_templates']:
                all_models[model_name]['used_in_templates'].append(filename)
    
    # 转换为最终格式
    output = {}
    for model_name, info in all_models.items():
        output[model_name] = {
            'url': info['url'],
            'directory': info['directory'],
            'node_types': sorted(list(info['node_types'])),
            'used_in_templates': info['used_in_templates']
        }
    
    return output


def main():
    parser = argparse.ArgumentParser(
        description='从 ComfyUI 模板文件中提取模型信息',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        '--templates-dir',
        default='../workflow_templates/templates',
        help='模板文件所在目录（默认: ../workflow_templates/templates）'
    )
    
    args = parser.parse_args()
    
    templates_dir = Path(__file__).parent / args.templates_dir
    
    if not templates_dir.exists():
        print(f"❌ 错误: 目录不存在: {templates_dir}")
        return
    
    print("=" * 60)
    print("提取 ComfyUI 模板中的模型信息")
    print("=" * 60)
    print(f"模板目录: {templates_dir}")
    print()
    
    print("正在分析模板文件...")
    models_data = analyze_all_templates(str(templates_dir))
    
    print(f"✓ 找到 {len(models_data)} 个独特的模型文件")
    
    # 生成输出文件名
    date_str = datetime.now().strftime("%Y%m%d")
    output_file = f"models_{date_str}.json"
    
    # 保存JSON
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(models_data, f, indent=2, ensure_ascii=False)
    
    print(f"✓ 已生成: {output_file}")
    
    # 打印统计信息
    print()
    print("=" * 60)
    print("统计信息")
    print("=" * 60)
    
    # 按目录统计
    by_dir = defaultdict(int)
    models_with_url = 0
    models_without_url = 0
    
    for model_name, info in models_data.items():
        by_dir[info['directory']] += 1
        if info['url']:
            models_with_url += 1
        else:
            models_without_url += 1
    
    print(f"总模型数: {len(models_data)}")
    print(f"  有下载地址: {models_with_url}")
    print(f"  无下载地址: {models_without_url}")
    print()
    print("按目录分布:")
    for directory in sorted(by_dir.keys()):
        print(f"  {directory:20s}: {by_dir[directory]:3d} 个")
    
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()

