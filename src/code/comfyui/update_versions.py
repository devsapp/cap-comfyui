#!/usr/bin/env python3

"""
更新 custom_nodes.json 中每个节点的 version 字段

规则:
- 如果仓库有 tag 且最新 tag 在近 3 个月内，使用 tag 作为 version
- 否则使用最新的 commit SHA 作为 version

使用方法:
# 直接运行（会更新 custom_nodes.json）
python3 update_versions.py

# 测试模式（不保存更改）
python3 update_versions.py --dry-run

# 指定文件路径
python3 update_versions.py --file /path/to/custom_nodes.json
"""

import json
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple


def extract_repo_info(repo_url: str) -> Optional[Tuple[str, str]]:
    """从 GitHub URL 提取 owner 和 repo 名称"""
    pattern = r'github\.com[:/]([^/]+)/([^/\.]+)'
    match = re.search(pattern, repo_url)
    if match:
        return match.group(1), match.group(2)
    return None


def get_latest_tag_and_date(repo_url: str) -> Optional[Tuple[str, datetime]]:
    """获取最新的 tag 及其创建日期"""
    try:
        # 使用 git ls-remote 获取所有 tags
        cmd = [
            'git', 'ls-remote', '--tags', '--sort=-v:refname', repo_url
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0 or not result.stdout.strip():
            return None
        
        # 解析输出，过滤掉 ^{} 的引用，获取最新的 tag
        lines = result.stdout.strip().split('\n')
        for line in lines:
            if '^{}' not in line:
                parts = line.split('\t')
                if len(parts) == 2:
                    commit_sha = parts[0]
                    tag_ref = parts[1]  # refs/tags/v1.0.0
                    tag_name = tag_ref.split('/')[-1]  # v1.0.0
                    
                    # 获取这个 commit 的日期
                    tag_date = get_commit_date(repo_url, commit_sha)
                    if tag_date:
                        return tag_name, tag_date
        
        return None
        
    except Exception as e:
        print(f"  ⚠️  获取 tag 失败: {e}")
        return None


def get_commit_date(repo_url: str, commit_sha: str) -> Optional[datetime]:
    """获取指定 commit 的日期"""
    try:
        cmd = [
            'git', 'ls-remote', repo_url, commit_sha
        ]
        # 先验证 commit 存在
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return None
        
        # 使用临时目录进行浅克隆来获取 commit 日期
        # 注意：这里我们使用 GitHub API 会更高效
        repo_info = extract_repo_info(repo_url)
        if repo_info:
            owner, repo = repo_info
            cmd = [
                'gh', 'api',
                f'/repos/{owner}/{repo}/commits/{commit_sha}',
                '--jq', '.commit.committer.date'
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0 and result.stdout.strip():
                date_str = result.stdout.strip()
                return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        
        return None
        
    except Exception as e:
        return None


def get_latest_commit(repo_url: str) -> Optional[str]:
    """获取最新的 commit SHA"""
    try:
        # 使用 git ls-remote 获取 HEAD
        cmd = [
            'git', 'ls-remote', repo_url, 'HEAD'
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0 and result.stdout.strip():
            # 解析输出: commit_sha\tHEAD
            commit_sha = result.stdout.strip().split()[0]
            # 返回短 SHA (前 7 位)
            return commit_sha[:7]
        
        return None
        
    except Exception as e:
        print(f"  ⚠️  获取 commit 失败: {e}")
        return None


def get_version_for_repo(repo_url: str, three_months_ago: datetime) -> str:
    """为指定的仓库获取 version"""
    repo_info = extract_repo_info(repo_url)
    if not repo_info:
        print(f"  ⚠️  无法解析仓库 URL: {repo_url}")
        return "unknown"
    
    owner, repo = repo_info
    print(f"  处理: {owner}/{repo}")
    
    # 尝试获取最新 tag
    tag_info = get_latest_tag_and_date(repo_url)
    
    if tag_info:
        tag_name, tag_date = tag_info
        # 检查 tag 是否在近 3 个月内
        if tag_date >= three_months_ago:
            print(f"    ✓ 使用 tag: {tag_name} (日期: {tag_date.strftime('%Y-%m-%d')})")
            return tag_name
        else:
            print(f"    ✗ tag 过旧: {tag_name} (日期: {tag_date.strftime('%Y-%m-%d')})")
    else:
        print(f"    ℹ  未找到 tag")
    
    # 使用最新 commit
    commit_sha = get_latest_commit(repo_url)
    if commit_sha:
        print(f"    ✓ 使用 commit: {commit_sha}")
        return commit_sha
    
    print(f"    ✗ 无法获取版本信息")
    return "unknown"


def update_custom_nodes_version(json_path: Path, dry_run: bool = False):
    """更新 custom_nodes.json 中的 version 字段"""
    
    # 检查 git 和 gh CLI 是否可用
    try:
        subprocess.run(['git', '--version'], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ 错误: 需要安装 git")
        return
    
    try:
        subprocess.run(['gh', '--version'], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ 错误: 需要安装 GitHub CLI (gh)")
        print("   安装方法: https://cli.github.com/")
        return
    
    # 读取 JSON 文件
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    custom_nodes = data.get('custom_nodes', [])
    three_months_ago = datetime.now(datetime.now().astimezone().tzinfo) - timedelta(days=90)
    
    print(f"开始更新 {len(custom_nodes)} 个节点的版本信息...")
    print(f"参考日期: {three_months_ago.strftime('%Y-%m-%d')} (3个月前)\n")
    
    updated_count = 0
    failed_count = 0
    
    for i, node in enumerate(custom_nodes, 1):
        node_id = node.get('id', 'unknown')
        repo_url = node.get('repository', '')
        current_version = node.get('version', 'unknown')
        
        print(f"[{i}/{len(custom_nodes)}] {node_id}")
        print(f"  当前版本: {current_version}")
        
        if not repo_url:
            print(f"  ⚠️  跳过: 没有仓库 URL")
            failed_count += 1
            continue
        
        try:
            new_version = get_version_for_repo(repo_url, three_months_ago)
            
            if new_version != "unknown":
                if new_version != current_version:
                    node['version'] = new_version
                    print(f"  ✓ 更新: {current_version} -> {new_version}")
                    updated_count += 1
                else:
                    print(f"  - 无变化")
            else:
                failed_count += 1
                
        except Exception as e:
            print(f"  ❌ 错误: {e}")
            failed_count += 1
        
        print()
    
    # 保存更新后的 JSON
    if not dry_run:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"\n✓ 已保存到: {json_path}")
    else:
        print(f"\n🔍 Dry run 模式，不保存更改")
    
    print(f"\n统计:")
    print(f"  - 总数: {len(custom_nodes)}")
    print(f"  - 更新: {updated_count}")
    print(f"  - 失败: {failed_count}")
    print(f"  - 未变化: {len(custom_nodes) - updated_count - failed_count}")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='更新 custom_nodes.json 的 version 字段')
    parser.add_argument(
        '--file',
        type=Path,
        default=Path(__file__).parent / 'custom_nodes.json',
        help='custom_nodes.json 文件路径'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='仅测试，不实际保存更改'
    )
    
    args = parser.parse_args()
    
    if not args.file.exists():
        print(f"❌ 错误: 文件不存在: {args.file}")
        return
    
    update_custom_nodes_version(args.file, args.dry_run)


if __name__ == '__main__':
    main()
