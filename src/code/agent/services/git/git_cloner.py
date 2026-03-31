# Git clone service: clone custom nodes from nodes_map (see DESIGN.md).
import os
import shlex
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ValidationError

import constants
from utils.logger import log
from services.git.models import (
    NodeMapValue,
    CloneDetail,
    CloneSummary,
    STATUS_CLONED,
    STATUS_SKIPPED,
    STATUS_OVERRIDDEN,
    STATUS_FAILED,
)

CONFLICT_SKIP = "skip"
CONFLICT_OVERRIDE = "override"

VERSION_TAG = "tag"
VERSION_COMMIT_ID = "commit"

MAX_CLONE_RETRIES = 1
CLONE_TIMEOUT = 30  # 单次 clone 命令的超时秒数，独立于全局超时

_LOG_PREFIX = "[GitManager]"


def _run_cmd(cmd: List[str], timeout: float, cwd: Optional[str] = None) -> None:
    """执行 git 子命令，失败时抛出 subprocess.CalledProcessError，超时时抛出 subprocess.TimeoutExpired。"""
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout, cwd=cwd)


def _parse_nodes_map(nodes_map: Optional[Dict[str, Any]]) -> Dict[str, NodeMapValue]:
    """
    解析 nodes_map，将 Dict[str, Any] 转为 Dict[str, NodeMapValue]。
    key 保持与 nodes_map 一致（插件名），value 由 Pydantic 负责校验与反序列化；
    校验失败（ValidationError）的条目自动跳过。
    """
    if not nodes_map:
        return {}
    result: Dict[str, NodeMapValue] = {}
    for key, raw in nodes_map.items():
        if not isinstance(raw, dict):
            continue
        try:
            result[key] = NodeMapValue.model_validate(raw)
        except ValidationError:
            continue
    return result


def _custom_nodes_dir() -> str:
    return os.path.join(constants.COMFYUI_DIR, "custom_nodes")


def _node_path(node_name: str) -> str:
    return os.path.join(_custom_nodes_dir(), node_name)


class GitCloner:
    """根据 nodes_map 将插件源码 git clone 到 custom_nodes 目录。"""

    def __init__(self) -> None:
        pass

    def clone_all(
        self,
        nodes_map: Optional[Dict[str, Any]] = None,
        timeout: int = constants.DEFAULT_INSTALL_TIMEOUT,
        conflict_strategy: str = CONFLICT_SKIP,
        max_retries: int = MAX_CLONE_RETRIES,
        clone_timeout: float = CLONE_TIMEOUT,
        custom_nodes_dirs: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        完整 clone 流程：解析 nodes_map → 逐插件冲突处理 + clone → 汇总返回。

        Args:
            nodes_map:         key=插件名，value=含 source、version 等的配置。None/{} 表示不处理任何插件。
            timeout:           全局超时秒数。
            conflict_strategy: "skip" | "override"，默认 "skip"。
            max_retries:       单个插件 clone 失败后的最大重试次数，默认 MAX_CLONE_RETRIES。
            clone_timeout:     单次 clone 命令的超时秒数（独立于全局超时），默认 CLONE_TIMEOUT。
            custom_nodes_dirs: 存放插件的父目录列表（即 custom_nodes 这一层），支持多个。
                               None = 使用默认的 {COMFYUI_DIR}/custom_nodes 目录。
                               冲突检测会遍历所有目录；clone 目标固定为列表中的第一个目录。
                               多个目录中存在同名插件时，以列表中先出现的目录为准。

        Returns:
            {"details": {插件名: {status, duration, ...}}, "summary": {total, cloned, skipped, overridden, failed, duration}}
        """
        if custom_nodes_dirs is None:
            custom_nodes_dirs = [_custom_nodes_dir()]

        start_time = time.time()
        summary = CloneSummary()
        self._timed_out = False

        # Step 1: 解析 nodes_map
        parsed = _parse_nodes_map(nodes_map)
        if not parsed:
            if nodes_map:
                log("WARNING", f"{_LOG_PREFIX} nodes_map provided but no valid entries parsed, nothing to clone.")
            return {"details": {}, "summary": summary.to_dict(), "timed_out": False}

        summary.total = len(parsed)
        plugin_list = ", ".join(parsed.keys())
        log("INFO", f"{_LOG_PREFIX} Starting clone for {summary.total} plugin(s): [{plugin_list}]")

        # Step 2+3: 逐插件冲突处理 + clone（合并为单一方法，避免批量重命名后中断导致多个插件目录不一致）
        details = self._process_and_clone_nodes(parsed, conflict_strategy, timeout, start_time, max_retries, clone_timeout, custom_nodes_dirs)

        # 从 details 汇总 summary 计数
        for detail in details.values():
            if detail.status == STATUS_SKIPPED:
                summary.skipped += 1
            elif detail.status == STATUS_CLONED:
                summary.cloned += 1
            elif detail.status == STATUS_OVERRIDDEN:
                summary.overridden += 1
            elif detail.status == STATUS_FAILED:
                summary.failed += 1

        summary.duration = round(time.time() - start_time, 2)
        log("INFO", (
            f"{_LOG_PREFIX} Clone finished in {summary.duration:.2f}s – "
            f"total={summary.total}, cloned={summary.cloned}, overridden={summary.overridden}, "
            f"skipped={summary.skipped}, failed={summary.failed}, timed_out={self._timed_out}"
        ))
        return {
            "details": {k: v.to_dict() for k, v in details.items()},
            "summary": summary.to_dict(),
            "timed_out": self._timed_out,
        }

    def _process_and_clone_nodes(
        self,
        parsed: Dict[str, NodeMapValue],
        conflict_strategy: str,
        timeout: float,
        start_time: float,
        max_retries: int = MAX_CLONE_RETRIES,
        clone_timeout: float = CLONE_TIMEOUT,
        custom_nodes_dirs: Optional[List[str]] = None,
    ) -> Dict[str, CloneDetail]:
        """
        逐个插件依次完成「冲突检测 → (重命名旧目录) → git clone → (删除/还原旧目录)」。

        设计原则：对覆盖策略，每个插件的重命名、clone、删除三步紧邻执行，
        而非先批量重命名再批量 clone。这样即使流程被中断，也只有当前插件
        处于中间态，不会影响其他插件目录。

        Args:
            parsed:            解析后的 nodes_map。
            conflict_strategy: "skip" | "override"；未知策略保守处理为 skip。
            timeout:           全局超时秒数。
            start_time:        流程起始时间戳（time.time()）。
            max_retries:       单个插件 clone 失败后的最大重试次数。
            clone_timeout:     单次 clone 命令的超时秒数。
            custom_nodes_dirs: 插件父目录列表；None 时退回默认目录。

        Returns:
            Dict[node_name, CloneDetail]：每个插件的处理结果。
        """
        if custom_nodes_dirs is None:
            custom_nodes_dirs = [_custom_nodes_dir()]

        details: Dict[str, CloneDetail] = {}

        # 一次性扫描所有目录的一级子目录，构建「小写名 → 完整路径」映射；多目录同名时以先出现的为准
        existing_lower = self._get_existing_lower(custom_nodes_dirs)

        for node_name, info in parsed.items():
            # ── 超时检测：将剩余未处理插件标记为 failed ──────────────────────────
            if time.time() - start_time >= timeout:
                self._timed_out = True
                remaining = [n for n in parsed if n not in details]
                log("WARNING", (
                    f"{_LOG_PREFIX} Global timeout ({timeout}s) reached, "
                    f"marking {len(remaining)} remaining plugin(s) as failed: [{', '.join(remaining)}]"
                ))
                for rest_name in remaining:
                    details[rest_name] = CloneDetail(status=STATUS_FAILED, error_msg="timeout")
                break

            detail = self._clone_single_node(
                node_name, info, existing_lower, conflict_strategy, max_retries, clone_timeout
            )
            details[node_name] = detail

            if detail.status == STATUS_CLONED:
                log("INFO", f"{_LOG_PREFIX} [{node_name}] cloned successfully ({detail.duration:.2f}s) → {detail.path}")
            elif detail.status == STATUS_OVERRIDDEN:
                log("INFO", f"{_LOG_PREFIX} [{node_name}] overridden successfully ({detail.duration:.2f}s) → {detail.path}")
            elif detail.status == STATUS_SKIPPED:
                log("INFO", f"{_LOG_PREFIX} [{node_name}] skipped: {detail.reason}")
            elif detail.status == STATUS_FAILED:
                log("ERROR", f"{_LOG_PREFIX} [{node_name}] clone failed: {detail.error_msg}")

        return details

    def _clone_single_node(
        self,
        node_name: str,
        info: NodeMapValue,
        existing_lower: Dict[str, str],
        conflict_strategy: str,
        max_retries: int = MAX_CLONE_RETRIES,
        clone_timeout: float = CLONE_TIMEOUT,
    ) -> CloneDetail:
        """
        对单个插件执行完整处理，分三种情况：

        1. 覆盖策略（conflict_strategy == "override"）：
           1.1 已有插件在默认目录（NAS / 可写）：
               备份旧目录 → clone → 删除备份；失败则还原备份。
           1.2 已有插件在其他目录（镜像层 / 只读）：
               无需备份，直接 clone 到默认目录。

        2. 跳过策略及其他（含未知策略）：
           插件已存在于任意目录 → 直接返回 STATUS_SKIPPED；
           无冲突 → 直接 clone 到默认目录。

        Args:
            node_name:         插件名（与 nodes_map key 一致）。
            info:              插件配置（source、version 等）。
            existing_lower:    小写目录名 → 已存在插件完整路径的映射（由调用方统一扫描）。
            conflict_strategy: "skip" | "override"。
            max_retries:       单个插件 clone 失败后的最大重试次数。
            clone_timeout:     单次 clone 命令的超时秒数。

        Returns:
            CloneDetail：本插件的处理结果。
        """
        node_path = _node_path(node_name)
        existing_path: Optional[str] = existing_lower.get(node_name.lower())

        if existing_path is not None and conflict_strategy == CONFLICT_OVERRIDE:
            if os.path.dirname(existing_path) == _custom_nodes_dir():
                # ── 1.1 覆盖：已有插件在默认目录（可写）────────────────────────
                # 先备份旧目录，clone 成功后删除备份，失败则还原
                existing_name = os.path.basename(existing_path)
                previous_path = self._rename_existing_dir(existing_path, existing_name)
                log("INFO", f"{_LOG_PREFIX} [{node_name}] existing directory backed up → {previous_path}")

                t0 = time.time()
                ok, err = self._run_clone(info, node_path, max_retries=max_retries, clone_timeout=clone_timeout)
                duration = round(time.time() - t0, 2)

                if ok:
                    shutil.rmtree(previous_path, ignore_errors=True)
                    return CloneDetail(status=STATUS_OVERRIDDEN, duration=duration, path=node_path, previous_path=previous_path)

                if os.path.isdir(node_path):
                    shutil.rmtree(node_path)
                if os.path.isdir(previous_path):
                    log("WARNING", f"{_LOG_PREFIX} [{node_name}] clone failed, restoring backup from {previous_path}")
                    os.rename(previous_path, existing_path)
                return CloneDetail(status=STATUS_FAILED, duration=duration, error_msg=err or "clone failed")

            else:
                # ── 1.2 覆盖：已有插件在其他目录（只读）────────────────────────
                # 其他目录不可写，直接 clone 到默认目录即可
                t0 = time.time()
                ok, err = self._run_clone(info, node_path, max_retries=max_retries, clone_timeout=clone_timeout)
                duration = round(time.time() - t0, 2)

                if ok:
                    return CloneDetail(status=STATUS_OVERRIDDEN, duration=duration, path=node_path)

                if os.path.isdir(node_path):
                    shutil.rmtree(node_path)
                return CloneDetail(status=STATUS_FAILED, duration=duration, error_msg=err or "clone failed")

        else:
            # ── 2. 跳过及其他策略 ────────────────────────────────────────────
            if existing_path is not None:
                return CloneDetail(status=STATUS_SKIPPED, reason="directory_exists")

            # 无冲突，直接 clone
            t0 = time.time()
            ok, err = self._run_clone(info, node_path, max_retries=max_retries, clone_timeout=clone_timeout)
            duration = round(time.time() - t0, 2)

            if ok:
                return CloneDetail(status=STATUS_CLONED, duration=duration, path=node_path)

            if os.path.isdir(node_path):
                shutil.rmtree(node_path)
            return CloneDetail(status=STATUS_FAILED, duration=duration, error_msg=err or "clone failed")

    def _get_existing_lower(self, nodes_dirs: List[str]) -> Dict[str, str]:
        """
        扫描多个 custom_nodes 父目录的一级子目录，返回「小写目录名 → 完整路径」映射。
        仅扫一级，不递归，防止耗时过长。
        多个目录中存在同名插件时，以列表中先出现的目录为准。
        以下目录视为无效，不计入结果：
          - 非目录（文件）
          - 以 .disabled 结尾的目录
          - __pycache__
        不存在的目录跳过。
        """
        result: Dict[str, str] = {}
        for nodes_dir in nodes_dirs:
            try:
                for entry in os.scandir(nodes_dir):
                    if (entry.is_dir()
                            and not entry.name.endswith(".disabled")
                            and entry.name != "__pycache__"):
                        lower_name = entry.name.lower()
                        if lower_name not in result:
                            result[lower_name] = entry.path
            except FileNotFoundError:
                continue
        return result

    def _rename_existing_dir(self, node_path: str, node_name: str) -> str:
        """
        将已存在的插件目录重命名为 <node_name>.bak.<timestamp>，返回重命名后的绝对路径。
        同一秒内多次调用时自动追加计数器后缀保证唯一性。
        """
        nodes_dir = _custom_nodes_dir()
        timestamp = int(time.time())
        backup_path = os.path.join(nodes_dir, f"{node_name}.bak.{timestamp}")

        counter = 1
        while os.path.exists(backup_path):
            backup_path = os.path.join(nodes_dir, f"{node_name}.bak.{timestamp}.{counter}")
            counter += 1

        os.rename(node_path, backup_path)
        return backup_path

    def _run_clone(
        self,
        info: NodeMapValue,
        target_path: str,
        max_retries: int = MAX_CLONE_RETRIES,
        clone_timeout: float = CLONE_TIMEOUT,
    ) -> Tuple[bool, Optional[str]]:
        """
        对单个插件执行 git clone，根据 version.type 选择拉取策略：
          - tag      : git clone --depth 1 -b <tag> <url> <target>
          - commit   : git init && (remote add || set-url) && git fetch --depth 1 && git checkout FETCH_HEAD（单子进程）
          - 其他/无  : git clone --depth 1 <url> <target>

        每次命令使用 clone_timeout 超时，与全局超时解耦。
        失败或超时时至少重试一次（共 max_retries + 1 次），重试前清理残留目录。
        返回 (成功与否, 失败时的错误信息)。
        """
        clone_url = info.source.cloneUrl
        if not clone_url:
            log("WARNING", f"{_LOG_PREFIX} [{info.name}] missing cloneUrl, skipping clone.")
            return False, "missing cloneUrl"

        version_type = info.version.type if info.version else None
        version_value = info.version.value if info.version else None
        total_attempts = max_retries + 1

        last_err: Optional[str] = None
        for attempt in range(total_attempts):
            # 重试前清理上次可能残留的不完整目录
            if attempt > 0 and os.path.isdir(target_path):
                shutil.rmtree(target_path)
                log("WARNING", (
                    f"{_LOG_PREFIX} [{info.name}] attempt {attempt}/{max_retries} – "
                    f"previous error: {last_err}. Retrying..."
                ))

            try:
                if version_type == VERSION_TAG and version_value:
                    _run_cmd(
                        ["git", "clone", "--depth", "1", "-b", version_value, clone_url, target_path],
                        clone_timeout,
                    )
                elif version_type == VERSION_COMMIT_ID and version_value:
                    # 命令链在单一子进程中执行；remote add || set-url 保证幂等，支持重试
                    os.makedirs(target_path, exist_ok=True)
                    cmd = (
                        f"git init && "
                        f"(git remote add origin {shlex.quote(clone_url)} || git remote set-url origin {shlex.quote(clone_url)}) && "
                        f"git fetch --depth 1 origin {shlex.quote(version_value)} && "
                        f"git checkout FETCH_HEAD"
                    )
                    _run_cmd(["bash", "-c", cmd], clone_timeout, cwd=target_path)
                else:
                    _run_cmd(["git", "clone", "--depth", "1", clone_url, target_path], clone_timeout)
                return True, None
            except subprocess.TimeoutExpired:
                last_err = "timeout"
            except subprocess.CalledProcessError as e:
                stderr = e.stderr.strip() if e.stderr else ""
                last_err = stderr or f"git command failed with exit code {e.returncode}"

        log("ERROR", f"{_LOG_PREFIX} [{info.name}] all {total_attempts} attempt(s) failed: {last_err}")
        return False, last_err
