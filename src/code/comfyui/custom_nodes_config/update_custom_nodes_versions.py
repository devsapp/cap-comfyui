#!/usr/bin/env python3
"""
Resolve each custom_nodes.json entry to a concrete git ref (prefer latest semver tag,
else default-branch tip) and rewrite version fields.

Usage (from repo root or this directory):
  python3 update_custom_nodes_versions.py [--dry-run] [--input custom_nodes.json]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

try:
    from packaging.version import InvalidVersion, Version
except ImportError:
    print("Requires: pip install packaging", file=sys.stderr)
    sys.exit(1)

HERE = Path(__file__).resolve().parent
DEFAULT_INPUT = HERE / "custom_nodes.json"


def _run_git(args: list[str], timeout: int = 60) -> tuple[int, str, str]:
    p = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return p.returncode, p.stdout or "", p.stderr or ""


def _normalize_tag_for_version(tag: str) -> str:
    """Return ref suitable for git checkout (strip refs/tags/ prefix)."""
    if tag.startswith("refs/tags/"):
        tag = tag[len("refs/tags/") :]
    if tag.endswith("^{}"):
        tag = tag[:-3]
    return tag


def _parse_tags(ls_remote_out: str) -> list[str]:
    tags: list[str] = []
    for line in ls_remote_out.splitlines():
        line = line.strip()
        if not line or "\t" not in line:
            continue
        _sha, ref = line.split("\t", 1)
        if not ref.startswith("refs/tags/"):
            continue
        if ref.endswith("^{}"):
            continue
        tags.append(_normalize_tag_for_version(ref))
    return tags


def _version_sort_key(tag: str) -> tuple:
    t = tag.strip()
    if t.startswith("v."):
        t = "v" + t[2:]
    if t.startswith("v"):
        core = t[1:]
    else:
        core = t
    core = core.removesuffix("-main")
    try:
        return (0, Version(core))
    except InvalidVersion:
        return (1, tag)


def _latest_semver_tag(repo: str) -> str | None:
    code, out, err = _run_git(["ls-remote", "--refs", "--tags", repo])
    if code != 0:
        return None
    tags = _parse_tags(out)
    semver_tags = [t for t in tags if _version_sort_key(t)[0] == 0]
    if not semver_tags:
        return None
    semver_tags.sort(key=_version_sort_key)
    return semver_tags[-1]


def _default_branch_tip(repo: str) -> str | None:
    code, out, _ = _run_git(["ls-remote", "--symref", repo, "HEAD"])
    if code != 0 or not out.strip():
        return None
    # ref: refs/heads/main\tHEAD
    m = re.search(r"ref:\s+refs/heads/(\S+)\s+HEAD", out)
    branch = m.group(1) if m else None
    if not branch:
        for b in ("main", "master"):
            code2, out2, _ = _run_git(["ls-remote", repo, f"refs/heads/{b}"])
            if code2 == 0 and out2.strip():
                branch = b
                break
        else:
            return None
    code3, out3, _ = _run_git(["ls-remote", repo, f"refs/heads/{branch}"])
    if code3 != 0 or not out3.strip():
        return None
    sha = out3.strip().split("\t", 1)[0]
    return sha[:12] if len(sha) >= 12 else sha


def _resolve_version(repo: str, old_version: str) -> tuple[str | None, str]:
    if old_version.lower() == "latest" or old_version == "":
        tip = _default_branch_tip(repo)
        if tip:
            return tip, "default-branch-tip"
        return None, "no-default-branch"

    tag = _latest_semver_tag(repo)
    if tag:
        return tag, "latest-semver-tag"

    tip = _default_branch_tip(repo)
    if tip:
        return tip, "fallback-default-branch-tip"
    return None, "unresolved"


def _process_node(n: dict) -> tuple[str, str, str, str | None, str]:
    """Returns (id, repo, old_version, new_version_or_None, how_or_reason)."""
    repo = n.get("repository") or ""
    if not repo:
        return (str(n.get("id", "")), "", "", None, "no-repository")
    old = str(n.get("version") or "")
    nid = str(n.get("id", repo))
    new_v, how = _resolve_version(repo, old)
    return (nid, repo, old, new_v, how)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--jobs", type=int, default=8, help="parallel git ls-remote workers")
    args = ap.parse_args()

    data = json.loads(args.input.read_text(encoding="utf-8"))
    nodes = data.get("custom_nodes") or []
    failures: list[tuple[str, str, str]] = []

    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
        futs = {ex.submit(_process_node, n): n for n in nodes}
        for fut in as_completed(futs):
            nid, repo, old, new_v, how = fut.result()
            n = futs[fut]
            if not new_v:
                failures.append((nid, repo, how))
                continue
            if new_v == old:
                continue
            print(f"{nid}: {old!r} -> {new_v!r} ({how})", flush=True)
            if not args.dry_run:
                n["version"] = new_v

    meta = data.setdefault("metadata", {})
    meta["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    meta["version_resolve_note"] = (
        "versions resolved by update_custom_nodes_versions.py "
        "(prefer latest semver tag, else default-branch SHA prefix)"
    )

    if args.dry_run:
        print("\n--dry-run: not writing file")
        if failures:
            print("\nFailures:", file=sys.stderr)
            for row in failures:
                print("  ", row, file=sys.stderr)
        return 1 if failures else 0

    args.input.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {args.input}")
    if failures:
        print("\nUnresolved (left unchanged where applicable):", file=sys.stderr)
        for row in failures:
            print("  ", row, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
