"""
TaskEventEmitter

在任务生命周期的关键阶段输出结构化 JSON 日志到 stdout，
由 FC 平台自动采集到 SLS，用于任务追踪和性能分析。

三条事件共用 metric_type: "art_task_event"，通过 event 字段区分：
  - submitted:  CPU 侧，任务提交（转发 GPU）时
  - executing:  GPU 侧，run() 入口收到请求时
  - completed:  GPU 侧，任务完成或失败时
"""
import json
import time
import traceback
from typing import Optional

import constants
from utils.logger import log

_METRIC_TYPE = "art_task_event"


class TaskEventEmitter:
    """任务生命周期事件上报（纯静态方法，无状态，线程安全）"""

    @staticmethod
    def emit_submitted(task_id: str, invocation_type: str) -> None:
        """
        任务提交事件（CPU 侧）

        Args:
            task_id: 任务 ID
            invocation_type: 调用类型，"Async" 或 "Sync"
        """
        _emit({
            "metric_type": _METRIC_TYPE,
            "task_id": task_id,
            "event": "Submitted",
            "invocation_type": invocation_type,
            "timestamp_ms": _now_ms(),
        })

    @staticmethod
    def emit_executing(task_id: str) -> int:
        """
        任务开始执行事件（GPU 侧）

        Args:
            task_id: 任务 ID

        Returns:
            int: 当前时间戳（毫秒），供 emit_completed 计算 duration_ms
        """
        ts = _now_ms()
        _emit({
            "metric_type": _METRIC_TYPE,
            "task_id": task_id,
            "event": "Executing",
            "timestamp_ms": ts,
        })
        return ts

    @staticmethod
    def emit_completed(
        task_id: str,
        status: str,
        executing_timestamp_ms: Optional[int] = None,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """
        任务完成事件（GPU 侧或 CPU 侧转发失败时）

        Args:
            task_id: 任务 ID
            status: "succeeded" 或 "failed"
            executing_timestamp_ms: emit_executing 返回的时间戳，用于计算 duration_ms
            error_type: 错误类型（成功时为 None）
            error_message: 错误消息（成功时为 None）
        """
        ts = _now_ms()
        duration_ms = (ts - executing_timestamp_ms) if executing_timestamp_ms is not None else None

        _emit({
            "metric_type": _METRIC_TYPE,
            "task_id": task_id,
            "event": "Completed",
            "status": status,
            "timestamp_ms": ts,
            "duration_ms": duration_ms,
            "error_type": error_type,
            "error_message": error_message,
            "instance_id": constants.INSTANCE_ID,
        })


def _now_ms() -> int:
    return int(time.time() * 1000)


def _emit(event: dict) -> None:
    """输出单行 JSON 日志，带时间戳，绝不抛异常。"""
    try:
        log("INFO", json.dumps(event, ensure_ascii=False))
        # 新增一行日志，用于分割ComfyUI本身的日志，避免影响日志解析
        log("INFO", "")
    except Exception:
        log("WARNING", f"[TaskEventEmitter] Failed to emit event: {traceback.format_exc()}")
