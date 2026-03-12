"""
ComfyUI 内置插件 Top N 筛选脚本

用法：
    python get_topn.py --top 100
    python get_topn.py --top 50 --output-dir ./

说明：
    1. 从 ComfyUI Manager GitHub 下载 github-stats.json（star 数）和 custom-node-list.json（插件列表）
    2. 合并数据，按 star 数降序排序
    3. 排除 excluded_custom_nodes.json 中的插件（repository URL 完全匹配）
    4. 取前 N 个，写入 custom_nodes_top_N_YYYY-MM-DD.json

输出文件供人工审核，确认后重命名为 custom_nodes.json 作为 Dockerfile 安装依据。
"""

import argparse
import json
import os
import subprocess
import urllib.request
import urllib.error
from datetime import date

STATS_URL = "https://raw.githubusercontent.com/Comfy-Org/ComfyUI-Manager/main/github-stats.json"
LIST_URL = "https://raw.githubusercontent.com/Comfy-Org/ComfyUI-Manager/main/custom-node-list.json"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EXCLUDED_FILE = os.path.join(SCRIPT_DIR, "excluded_custom_nodes.json")


def fetch_json(url: str) -> dict:
    """下载 JSON 数据"""
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        raise


def get_github_token() -> str:
    """尝试获取 GitHub Token"""
    try:
        # 尝试从 gh cli 获取
        return subprocess.check_output(["gh", "auth", "token"], text=True).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        # 尝试从环境变量获取
        return os.environ.get("GITHUB_TOKEN", "")


def get_latest_version(repo_url: str, token: str) -> str:
    """获取最新版本（Tag 或 Commit SHA）"""
    if not repo_url or "github.com" not in repo_url:
        return ""

    try:
        # 清理 URL，移除 .git 后缀
        clean_url = repo_url.rstrip("/")
        if clean_url.endswith(".git"):
            clean_url = clean_url[:-4]
        
        parts = clean_url.split("/")
        if len(parts) < 2:
            return ""
        
        owner = parts[-2]
        repo = parts[-1]
        
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "ComfyUI-TopN-Fetcher"
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        # 1. 尝试获取最新的 Tag
        tags_url = f"https://api.github.com/repos/{owner}/{repo}/tags"
        try:
            req = urllib.request.Request(tags_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    tags = json.loads(response.read().decode("utf-8"))
                    if tags and isinstance(tags, list) and len(tags) > 0:
                        return tags[0].get("name", "")
        except (urllib.error.URLError, json.JSONDecodeError):
            pass

        # 2. 如果没有 Tag，获取最新的 Commit
        commits_url = f"https://api.github.com/repos/{owner}/{repo}/commits?per_page=1"
        try:
            req = urllib.request.Request(commits_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    commits = json.loads(response.read().decode("utf-8"))
                    if commits and isinstance(commits, list) and len(commits) > 0:
                        sha = commits[0].get("sha", "")
                        return sha[:7] if sha else ""
        except (urllib.error.URLError, json.JSONDecodeError):
            pass

    except Exception as e:
        print(f"[get_topn] 获取版本失败 {repo_url}: {e}")
    
    return ""


def enrich_with_versions(nodes: list, token: str):
    """为节点列表添加 version 信息"""
    total = len(nodes)
    print(f"正在获取 {total} 个插件的版本信息...")
    for i, node in enumerate(nodes):
        repo = node.get("repository", "")
        if repo:
            print(f"[{i+1}/{total}] Fetching version for {node.get('name')} ({repo})...")
            version = get_latest_version(repo, token)
            if version:
                node["version"] = version
            else:
                print(f"  -> Failed to get version for {repo}")


def merge_and_rank(stats: dict, node_list: dict) -> list:
    """合并 stats 和 node_list，按 star 数降序排序"""
    nodes = node_list.get("custom_nodes", [])
    result = []
    for node in nodes:
        ref = node.get("reference") or node.get("repository", "")
        if not ref:
            continue
        # Normalize URL for lookup (stats keys may have slight variations)
        stars = 0
        if ref in stats:
            stars = stats[ref].get("stars") or 0
        result.append({
            "id": node.get("id", _url_to_id(ref)),
            "name": node.get("title", node.get("name", "")),
            "repository": ref,
            "stars": stars,
            "enabled": True,
            "description": node.get("description", ""),
        })
    result.sort(key=lambda x: x["stars"], reverse=True)
    return result


def filter_excluded(ranked: list, excluded: dict) -> list:
    """排除 excluded 列表中的插件（repository URL 完全匹配）"""
    excluded_urls = set()
    for node in excluded.get("custom_nodes", []):
        url = node.get("repository") or node.get("reference", "")
        if url:
            excluded_urls.add(url)
    return [r for r in ranked if r["repository"] not in excluded_urls]


def generate_output(items: list, top_n: int, output_dir: str, excluded_count: int = 0) -> str:
    """生成 top N 输出文件，返回文件路径"""
    os.makedirs(output_dir, exist_ok=True)
    today = date.today().isoformat()
    filename = f"custom_nodes_top_{top_n}_{today}.json"
    filepath = os.path.join(output_dir, filename)

    taken = items[:top_n]
    data = {
        "metadata": {
            "generated_at": today,
            "top_n": top_n,
            "total": len(taken),
            "source_stats_url": STATS_URL,
            "source_list_url": LIST_URL,
            "excluded_count": excluded_count,
        },
        "custom_nodes": taken,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return filepath


def get_topn_plugins(top_n: int = 100, output_dir: str = SCRIPT_DIR) -> str:
    """主流程：下载数据 → 合并排序 → 过滤排除 → 写文件"""
    if top_n <= 0:
        raise ValueError(f"top_n must be a positive integer, got {top_n}")
    stats = fetch_json(STATS_URL)
    node_list = fetch_json(LIST_URL)
    ranked = merge_and_rank(stats, node_list)

    excluded = {"custom_nodes": []}
    if os.path.exists(EXCLUDED_FILE):
        try:
            with open(EXCLUDED_FILE, encoding="utf-8") as f:
                excluded = json.load(f)
        except json.JSONDecodeError as e:
            print(f"[get_topn] 警告: excluded 文件解析失败，跳过排除逻辑: {e}")
            excluded = {"custom_nodes": []}

    before_count = len(ranked)
    ranked = filter_excluded(ranked, excluded)
    excluded_count = before_count - len(ranked)

    # 取前 N 个
    top_nodes = ranked[:top_n]

    # 获取版本信息
    token = get_github_token()
    if not token:
        print("[get_topn] 警告: 未找到 GitHub Token，API 请求可能会受限")
    
    enrich_with_versions(top_nodes, token)

    return generate_output(top_nodes, top_n, output_dir, excluded_count)


def _url_to_id(url: str) -> str:
    """将 repository URL 转换为 id（取 owner/repo 格式的 repo 部分）"""
    if not url:
        return ""
    parts = url.rstrip("/").split("/")
    repo_name = parts[-1] if parts else ""
    return repo_name.lower()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成 ComfyUI 内置插件 Top N 候选列表")
    parser.add_argument("--top", type=int, default=100, help="取前 N 个（默认 100）")
    parser.add_argument("--output-dir", type=str, default=SCRIPT_DIR, help="输出目录（默认脚本所在目录）")
    args = parser.parse_args()
    path = get_topn_plugins(top_n=args.top, output_dir=args.output_dir)
    print(f"Written: {path}")
