#!/usr/bin/env python3
"""更新 custom_nodes.json 中每个节点的 version 字段"""

import json
import re
import subprocess
import signal
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple


class TimeoutError(Exception):
    pass


def timeout_handler(signum, frame):
    raise TimeoutError("操作超时")


def extract_repo_info(repo_url: str) -> Optional[Tuple[str, str]]:
    """从 GitHub URL 提取 owner 和 repo 名称"""
    pattern = r'github\.com[:/]([^/]+)/([^/\.]+)'
    match = re.search(pattern, repo_url)
    if match:
        return match.group(1), match.group(2)
    return None


def run_command_with_timeout(cmd, timeout: int = 15) -> Optional[str]:
    """运行命令并设置超时"""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return None
    except (subprocess.TimeoutExpired, Exception) as e:
        return None


def get_latest_tag(repo_url: str) -> Optional[str]:
    """获取最新的 tag"""
    cmd = ['git', 'ls-remote', '--tags', '--sort=-v:refname', repo_url]
    output = run_command_with_timeout(cmd, timeout=10)
    
    if not output:
        return None
    
    for line in output.split('\n'):
        if '^{}' not in line:
            parts = line.split('\t')
            if len(parts) == 2:
                tag_ref = parts[1]
                return tag_ref.split('/')[-1]
    
    return None


def get_latest_commit(repo_url: str) -> Optional[str]:
    """获取最新的 commit SHA"""
    cmd = ['git', 'ls-remote', repo_url, 'HEAD']
    output = run_command_with_timeout(cmd, timeout=10)
    
    if output:
        commit_sha = output.split()[0]
        return commit_sha[:7]
    
    return None


def get_version_for_repo(repo_url: str) -> str:
    """为指定的仓库获取 version"""
    repo_info = extract_repo_info(repo_url)
    if not repo_info:
        return "unknown"
    
    owner, repo = repo_info
    print(f"  {owner}/{repo}", end=" ... ", flush=True)
    
    # 优先使用 tag
    tag = get_latest_tag(repo_url)
    if tag:
        print(f"✓ tag: {tag}")
        return tag
    
    # 使用 commit
    commit = get_latest_commit(repo_url)
    if commit:
        print(f"✓ commit: {commit}")
        return commit
    
    print("✗ 失败")
    return "unknown"


def update_custom_nodes_version(json_path: Path, dry_run: bool = False):
    """更新 custom_nodes.json 中的 version 字段"""
    
    # 检查 git 是否可用
    try:
        subprocess.run(['git', '--version'], capture_output=True, check=True, timeout=5)
    except Exception:
        print("❌ 错误: 需要安装 git")
        return
    
    # 读取 JSON 文件
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ 错误: 无法读取文件 {e}")
        return
    
    custom_nodes = data.get('custom_nodes', [])
    
    print(f"正在更新 {len(custom_nodes)} 个节点的版本...")
    print()
    
    updated_count = 0
    failed_count = 0
    
    for i, node in enumerate(custom_nodes, 1):
        node_id = node.get('id', 'unknown')
        repo_url = node.get('repository', '')
        current_version = node.get('version', 'unknown')
        
        print(f"[{i}/{len(custom_nodes)}] {node_id:<30}", end=" | ")
        
        if not repo_url:
            print("⚠️ 无仓库 URL")
            failed_count += 1
            continue
        
        try:
            new_version = get_version_for_repo(repo_url)
            
            if new_version != "unknown":
                if new_version != current_version:
                    node['version'] = new_version
                    print(f"  {current_version} → {new_version}")
                    updated_count += 1
                else:
                    print(f"  (无变化)")
            else:
                failed_count += 1
                
        except Exception as e:
            print(f"  ❌ {e}")
            failed_count += 1
    
    # 保存更新后的 JSON
    if not dry_run:
        try:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"\n✓ 已保存到: {json_path}")
        except Exception as e:
            print(f"\n❌ 错误: 无法保存文件 {e}")
            return
    else:
        print(f"\n🔍 Dry run 模式，不保存更改")
    
    print(f"\n统计:")
    print(f"  总数: {len(custom_nodes)}")
    print(f"  更新: {updated_count}")
    print(f"  失败: {failed_count}")
    print(f"  无变化: {len(custom_nodes) - updated_count - failed_count}")


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
