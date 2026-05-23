"""
Jobs Handler
处理 /api/jobs 请求（ComfyUI v0.16.4 新增 API）
从 TaskManager 的 HistoryManager 读取历史数据并返回 v0.16.4 jobs 格式
"""
import traceback
from typing import Optional, List
from flask import request, jsonify, g

from utils.logger import log


# Media types that can be previewed
PREVIEWABLE_MEDIA_TYPES = frozenset({'images', 'video', 'audio', '3d', 'text'})


class JobsHandler:
    """处理 /api/jobs 请求，从 TaskManager 读取历史数据并转换为 v0.16.4 jobs 格式"""

    def __init__(self, task_manager):
        self.task_manager = task_manager

    def handle_get_jobs(self):
        """处理 GET /api/jobs 请求"""
        status_param = request.args.get('status')
        sort_by = request.args.get('sort_by', 'created_at').lower()
        sort_order = request.args.get('sort_order', 'desc').lower()

        status_filter = None
        if status_param:
            status_filter = [s.strip().lower() for s in status_param.split(',') if s.strip()]
            valid_statuses = {'pending', 'in_progress', 'completed', 'failed', 'cancelled'}
            invalid = [s for s in status_filter if s not in valid_statuses]
            if invalid:
                return jsonify({"error": f"Invalid status value(s): {', '.join(invalid)}"}), 400

        if sort_by not in {'created_at', 'execution_duration'}:
            return jsonify({"error": "sort_by must be 'created_at' or 'execution_duration'"}), 400

        if sort_order not in {'asc', 'desc'}:
            return jsonify({"error": "sort_order must be 'asc' or 'desc'"}), 400

        limit = None
        if 'limit' in request.args:
            try:
                limit = int(request.args.get('limit'))
                if limit <= 0:
                    return jsonify({"error": "limit must be a positive integer"}), 400
            except (ValueError, TypeError):
                return jsonify({"error": "limit must be an integer"}), 400

        offset = 0
        if 'offset' in request.args:
            try:
                offset = int(request.args.get('offset'))
                if offset < 0:
                    offset = 0
            except (ValueError, TypeError):
                return jsonify({"error": "offset must be an integer"}), 400

        try:
            jobs = self._get_all_jobs(status_filter, sort_by, sort_order)
            total = len(jobs)

            if offset > 0:
                jobs = jobs[offset:]
            if limit is not None:
                jobs = jobs[:limit]

            has_more = (offset + len(jobs)) < total

            return jsonify({
                'jobs': jobs,
                'pagination': {
                    'offset': offset,
                    'limit': limit,
                    'total': total,
                    'has_more': has_more
                }
            })
        except Exception as e:
            log("ERROR", f"[JobsHandler] Error getting jobs: {e}\n{traceback.format_exc()}")
            return jsonify({"error": "Internal server error"}), 500

    def handle_get_job(self, job_id: str):
        """处理 GET /api/jobs/<job_id> 请求"""
        try:
            history_item = self.task_manager._history_manager.get_history_item(job_id)
            if not history_item:
                return jsonify({"error": "Job not found"}), 404

            job = self._normalize_history_item(job_id, history_item, include_outputs=True)
            return jsonify(job)
        except Exception as e:
            log("ERROR", f"[JobsHandler] Error getting job {job_id}: {e}\n{traceback.format_exc()}")
            return jsonify({"error": "Internal server error"}), 500

    def _get_all_jobs(self, status_filter: Optional[List[str]], sort_by: str, sort_order: str) -> list:
        """从 TaskManager 获取所有 jobs"""
        jobs = []
        user_id = getattr(g, 'user_id', 'default')

        if status_filter is None:
            status_filter = ['pending', 'in_progress', 'completed', 'failed', 'cancelled']

        # Get active tasks (pending/running)
        if 'in_progress' in status_filter or 'pending' in status_filter:
            tasks = self.task_manager.get_current_user_tasks()
            for task in tasks:
                if task.status.value == 'running' and 'in_progress' in status_filter:
                    jobs.append(self._normalize_active_task(task, 'in_progress'))
                elif task.status.value == 'pending' and 'pending' in status_filter:
                    jobs.append(self._normalize_active_task(task, 'pending'))

        # Get completed/failed from history
        history_statuses = {'completed', 'failed', 'cancelled'}
        requested_history = history_statuses & set(status_filter)
        if requested_history:
            history = self.task_manager._history_manager.get_history(user_id)
            for prompt_id, history_item in history.items():
                job = self._normalize_history_item(prompt_id, history_item)
                if job.get('status') in requested_history:
                    jobs.append(job)

        # Sort
        reverse = (sort_order == 'desc')
        if sort_by == 'execution_duration':
            def sort_key(j):
                start = j.get('execution_start_time', 0) or 0
                end = j.get('execution_end_time', 0) or 0
                return end - start if end and start else 0
        else:
            def sort_key(j):
                return j.get('create_time', 0) or 0

        jobs.sort(key=sort_key, reverse=reverse)
        return jobs

    def _normalize_active_task(self, task, status: str) -> dict:
        """Convert an active Task to jobs API format"""
        extra_data = {}
        if task.prompt_body:
            extra_data = task.prompt_body.get('extra_data', {})

        return {
            'id': task.task_id,
            'status': status,
            'create_time': extra_data.get('create_time'),
            'outputs_count': 0,
        }

    def _normalize_history_item(self, prompt_id: str, history_item: dict, include_outputs: bool = False) -> dict:
        """Convert a HistoryManager item to jobs API format"""
        prompt_tuple = history_item.get('prompt', [])
        extra_data = prompt_tuple[3] if len(prompt_tuple) > 3 else {}
        create_time = extra_data.get('create_time') or history_item.get('create_time')

        status_info = history_item.get('status', {})
        status_str = status_info.get('status_str', '')

        if status_str == 'success':
            status = 'completed'
        elif status_str == 'error':
            status = 'failed'
        else:
            status = 'completed'

        outputs = history_item.get('outputs', {})
        outputs_count, preview_output = self._get_outputs_summary(outputs)

        execution_start_time = None
        execution_end_time = None
        execution_error = None
        messages = status_info.get('messages', [])
        for entry in messages:
            if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                event_name, event_data = entry[0], entry[1]
                if isinstance(event_data, dict):
                    if event_name == 'execution_start':
                        execution_start_time = event_data.get('timestamp')
                    elif event_name in ('execution_success', 'execution_error', 'execution_interrupted'):
                        execution_end_time = event_data.get('timestamp')
                        if event_name == 'execution_error':
                            execution_error = event_data
                        elif event_name == 'execution_interrupted':
                            status = 'cancelled'

        job = {
            'id': prompt_id,
            'status': status,
            'create_time': create_time,
            'execution_start_time': execution_start_time,
            'execution_end_time': execution_end_time,
            'outputs_count': outputs_count,
            'preview_output': preview_output,
        }

        if execution_error:
            job['execution_error'] = execution_error

        if include_outputs:
            job['outputs'] = outputs
            job['execution_status'] = status_info
            prompt_dict = prompt_tuple[2] if len(prompt_tuple) > 2 else {}
            job['workflow'] = {
                'prompt': prompt_dict,
                'extra_data': extra_data,
            }

        # Remove None values
        job = {k: v for k, v in job.items() if v is not None}
        return job

    def _get_outputs_summary(self, outputs: dict) -> tuple:
        """Count outputs and find preview image"""
        count = 0
        preview_output = None

        for node_id, node_outputs in outputs.items():
            if not isinstance(node_outputs, dict):
                continue
            for media_type, items in node_outputs.items():
                if media_type == 'animated' or not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    count += 1
                    if preview_output is None and media_type in PREVIEWABLE_MEDIA_TYPES:
                        preview_output = {
                            **item,
                            'nodeId': node_id,
                            'mediaType': media_type,
                        }

        return count, preview_output
