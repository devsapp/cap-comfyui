#!/usr/bin/env python3
"""
计算并验证模型文件的 SHA256 完整性

功能：
- 扫描指定目录下的所有模型文件
- 计算本地文件的 SHA256
- 从 Hugging Face 获取远程文件的 SHA256
- 比较并报告不一致的文件

依赖：
    pip install huggingface_hub

使用方法：
    python3 cal_checksum.py /path/to/models models_20251225.json
    python3 cal_checksum.py /path/to/models models_20251225.json --dir unet
    python3 cal_checksum.py /path/to/models models_20251225.json --json-only
"""

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from huggingface_hub import HfApi
except ImportError:
    print("❌ 错误: 请先安装 huggingface_hub")
    print("运行: pip install huggingface_hub")
    sys.exit(1)


def calculate_sha256(filepath: str) -> str:
    """计算本地文件的 SHA256"""
    sha256_hash = hashlib.sha256()
    file_size = os.path.getsize(filepath)
    
    print(f"    计算中... (文件大小: {file_size / (1024**3):.2f} GB)")
    
    with open(filepath, "rb") as f:
        # 使用较大的缓冲区以提高性能
        for byte_block in iter(lambda: f.read(8192 * 1024), b""):
            sha256_hash.update(byte_block)
    
    return sha256_hash.hexdigest()


def parse_hf_url(url: str) -> Optional[Dict[str, str]]:
    """
    解析 Hugging Face URL，提取 repo_id 和 file_path
    
    URL 格式: 
    - https://huggingface.co/{repo_id}/resolve/{revision}/{file_path}
    - https://huggingface.co/{repo_id}/blob/{revision}/{file_path}
    """
    if not url or not url.startswith('https://huggingface.co/'):
        return None
    
    # 移除 query string
    url = url.split('?')[0]
    
    # 匹配模式
    pattern = r'https://huggingface\.co/([^/]+/[^/]+)/(resolve|blob)/([^/]+)/(.+)'
    match = re.match(pattern, url)
    
    if match:
        repo_id = match.group(1)
        revision = match.group(3)
        file_path = match.group(4)
        return {
            'repo_id': repo_id,
            'revision': revision,
            'file_path': file_path
        }
    
    return None


def get_hf_file_sha256(repo_id: str, filename: str, revision: str = "main") -> Optional[str]:
    """通过 HuggingFace Hub SDK 获取文件的 SHA256"""
    try:
        # 使用 HfApi，会自动使用 HF_ENDPOINT 环境变量
        api = HfApi()
        
        # 获取仓库文件树
        repo_files = api.list_repo_tree(
            repo_id=repo_id,
            revision=revision,
            recursive=True
        )
        
        # 查找目标文件
        for file_info in repo_files:
            # 跳过目录
            if not hasattr(file_info, 'path'):
                continue
                
            file_path = file_info.path
            
            # 匹配文件路径
            if file_path == filename or file_path.endswith('/' + filename):
                # 检查是否有 LFS 信息
                if hasattr(file_info, 'lfs') and file_info.lfs:
                    if hasattr(file_info.lfs, 'sha256'):
                        return file_info.lfs.sha256.lower()
                    # 有些文件可能在 oid 中
                    if hasattr(file_info.lfs, 'oid') and file_info.lfs.oid.startswith('sha256:'):
                        return file_info.lfs.oid.replace('sha256:', '').lower()
        
        return None
        
    except Exception as e:
        print(f"    ⚠️  获取远程 SHA256 失败: {e}")
        return None


def find_model_files(base_dir: str, target_subdir: Optional[str] = None) -> List[Tuple[str, str, str]]:
    """
    查找所有模型文件
    
    返回: [(完整路径, 相对目录, 文件名), ...]
    """
    base_path = Path(base_dir)
    if not base_path.exists():
        print(f"❌ 错误: 目录不存在: {base_dir}")
        sys.exit(1)
    
    model_extensions = {'.safetensors', '.ckpt', '.pt', '.pth', '.bin'}
    found_files = []
    
    # 如果指定了子目录
    if target_subdir:
        search_path = base_path / target_subdir
        if not search_path.exists():
            print(f"❌ 错误: 子目录不存在: {search_path}")
            sys.exit(1)
        search_paths = [search_path]
    else:
        # 搜索所有子目录
        search_paths = [base_path]
    
    for search_path in search_paths:
        for root, dirs, files in os.walk(search_path):
            for filename in files:
                if any(filename.endswith(ext) for ext in model_extensions):
                    full_path = os.path.join(root, filename)
                    # 计算相对于 base_dir 的目录
                    rel_dir = os.path.relpath(root, base_path)
                    found_files.append((full_path, rel_dir, filename))
    
    return sorted(found_files)


def load_models_mapping(json_file: str) -> Dict[str, Dict]:
    """从 models_*.json 加载模型映射"""
    json_path = Path(json_file)
    
    if not json_path.exists():
        print(f"❌ 错误: 文件不存在: {json_file}")
        sys.exit(1)
    
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ 错误: 读取 {json_file} 失败: {e}")
        sys.exit(1)


def verify_model_file(
    file_path: str,
    rel_dir: str,
    filename: str,
    models_mapping: Dict
) -> Dict:
    """
    验证单个模型文件
    
    返回验证结果字典
    """
    result = {
        'path': file_path,
        'dir': rel_dir,
        'filename': filename,
        'local_sha256': None,
        'remote_sha256': None,
        'match': None,
        'error': None
    }
    
    # 计算本地 SHA256
    try:
        print(f"  计算本地 SHA256...")
        result['local_sha256'] = calculate_sha256(file_path)
    except Exception as e:
        result['error'] = f"计算 SHA256 失败: {e}"
        return result
    
    # 查找对应的远程 URL
    model_info = models_mapping.get(filename)
    
    if not model_info or not model_info.get('url'):
        result['error'] = "未找到下载 URL"
        return result
    
    url = model_info['url']
    
    # 解析 URL
    parsed = parse_hf_url(url)
    if not parsed:
        result['error'] = f"无法解析 URL (非 Hugging Face 链接)"
        return result
    
    # 从 Hugging Face 获取 SHA256
    print(f"  从 Hugging Face 获取 SHA256...")
    print(f"    Repo: {parsed['repo_id']}")
    print(f"    File: {parsed['file_path']}")
    
    remote_sha256 = get_hf_file_sha256(
        parsed['repo_id'],
        parsed['file_path'],
        parsed['revision']
    )
    
    if not remote_sha256:
        result['error'] = "无法从 Hugging Face 获取 SHA256"
        return result
    
    result['remote_sha256'] = remote_sha256
    result['match'] = (result['local_sha256'].lower() == remote_sha256.lower())
    
    return result


def print_result(result: Dict):
    """打印单个文件的验证结果"""
    print("=" * 80)
    print(f"📁 目录: {result['dir']}")
    print(f"📄 文件: {result['filename']}")
    print("-" * 80)
    
    if result['error']:
        print(f"❌ 错误: {result['error']}")
        print("=" * 80)
        return
    
    print(f"本地 SHA256:  {result['local_sha256']}")
    print(f"远程 SHA256:  {result['remote_sha256']}")
    
    if result['match']:
        print(f"✅ 状态: 一致")
    else:
        print(f"❌ 状态: 不一致")
    
    print("=" * 80)


def print_summary(results: List[Dict]):
    """打印验证总结"""
    total = len(results)
    matched = sum(1 for r in results if r['match'] is True)
    mismatched = sum(1 for r in results if r['match'] is False)
    errors = sum(1 for r in results if r['error'] is not None)
    
    print()
    print("=" * 80)
    print("📊 验证总结")
    print("=" * 80)
    print(f"总文件数: {total}")
    print(f"✅ 一致:   {matched}")
    print(f"❌ 不一致: {mismatched}")
    print(f"⚠️  错误:   {errors}")
    print()
    
    if mismatched > 0:
        print("⚠️  以下模型 SHA256 不一致，建议重新下载:")
        print("-" * 80)
        for result in results:
            if result['match'] is False:
                print(f"  • {result['dir']}/{result['filename']}")
        print()
    
    if errors > 0:
        print("⚠️  以下模型验证时出错:")
        print("-" * 80)
        for result in results:
            if result['error']:
                print(f"  • {result['dir']}/{result['filename']}")
                print(f"    原因: {result['error']}")
        print()
    
    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description='计算并验证本地模型文件的 SHA256 完整性',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s /root/models models_20251225.json
  %(prog)s /root/models models_20251225.json --dir unet
  %(prog)s ~/ComfyUI/models models_20251225.json --dir loras
  %(prog)s /root/models models_20251225.json --json-only
        """
    )
    
    parser.add_argument(
        'base_dir',
        help='模型文件所在的基础目录'
    )
    
    parser.add_argument(
        'models_json',
        help='models_*.json 文件路径'
    )
    
    parser.add_argument(
        '--dir', '-d',
        dest='subdir',
        help='只验证指定子目录（如 unet, loras, vae 等）'
    )

    parser.add_argument(
        '--json-only',
        action='store_true',
        help='只验证 JSON 文件中列出的模型，而非扫描整个目录'
    )

    args = parser.parse_args()
    
    print("=" * 80)
    print("🔍 ComfyUI 模型 SHA256 验证工具")
    print("=" * 80)
    
    # 显示是否使用镜像
    hf_endpoint = os.environ.get('HF_ENDPOINT')
    if hf_endpoint:
        print(f"✓ 使用 Hugging Face 镜像: {hf_endpoint}")
    else:
        print("ℹ️  使用官方 Hugging Face API (huggingface.co)")
        print("   提示: 如需使用镜像，请设置环境变量: export HF_ENDPOINT=\"https://hf-mirror.com\"")
    print()
    
    # 加载模型映射
    print(f"📋 加载模型映射: {args.models_json}")
    models_mapping = load_models_mapping(args.models_json)
    print(f"✓ 找到 {len(models_mapping)} 个模型的信息")
    print()
    
    # 查找模型文件
    if args.json_only:
        print(f"🔎 仅验证 JSON 中列出的模型（共 {len(models_mapping)} 个）")
        base_path = Path(args.base_dir)
        model_files = []
        for filename, info in models_mapping.items():
            directory = info.get('directory', '')
            full_path = str(base_path / directory / filename)
            if not Path(full_path).exists():
                print(f"  ⚠️  文件不存在，跳过: {directory}/{filename}")
                continue
            model_files.append((full_path, directory, filename))
    else:
        print(f"🔎 扫描目录: {args.base_dir}")
        if args.subdir:
            print(f"   子目录: {args.subdir}")
        model_files = find_model_files(args.base_dir, args.subdir)

    if not model_files:
        print("⚠️  未找到任何模型文件")
        return

    print(f"✓ 找到 {len(model_files)} 个模型文件")
    print()
    
    # 验证每个文件
    results = []
    
    for i, (file_path, rel_dir, filename) in enumerate(model_files, 1):
        print(f"[{i}/{len(model_files)}] 验证: {rel_dir}/{filename}")
        
        result = verify_model_file(
            file_path,
            rel_dir,
            filename,
            models_mapping
        )
        
        results.append(result)
        print_result(result)
        print()
    
    # 打印总结
    print_summary(results)


if __name__ == "__main__":
    main()

