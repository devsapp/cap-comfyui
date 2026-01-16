"""
History Handler
处理 /history 请求逻辑
从 TaskManager 读取历史数据并返回 ComfyUI 兼容格式
"""
import time
import traceback
from collections import OrderedDict
from typing import Optional, Dict, Any, List
from flask import request, jsonify

from utils.logger import log


class HistoryHandler:
    """处理 /history 请求，从内存队列读取历史数据"""
    
    def __init__(self):
        """初始化 handler，获取任务管理器和状态枚举"""
        try:
            from services.gateway.task.task_manager import get_task_manager
            from services.gateway.task.task import TaskStatus
            self.task_manager = get_task_manager()
            self.TaskStatus = TaskStatus
        except Exception as e:
            log("ERROR", f"Failed to initialize HistoryHandler: {e}")
            self.task_manager = None
            self.TaskStatus = None
    
    def handle_get_request(self):
        """处理 GET /api/history 请求"""
        limit = self._parse_limit_param()
        history = self._get_all_history_from_queue(limit)
        log("DEBUG", f"Retrieved {len(history)} history items from queue")
        return jsonify(history)
    
    def _get_all_history_from_queue(self, limit: Optional[int] = None) -> OrderedDict:
        """
        从队列中获取所有已完成任务的历史记录
        
        Args:
            limit: 可选的数量限制
            
        Returns:
            OrderedDict: prompt_id -> history_item
        """
        if not self._is_initialized():
            return OrderedDict()
        
        try:
            # 获取并过滤已完成的任务
            ended_tasks = self._get_ended_tasks(limit)
            
            # 转换为历史记录格式
            result = OrderedDict()
            total_count = len(ended_tasks)
            for idx, task in enumerate(ended_tasks):
                history_item = self._convert_task_to_history_item(task, total_count - idx)
                if history_item:
                    prompt_id = list(history_item.keys())[0]
                    result[prompt_id] = history_item[prompt_id]
            
            return result
        except Exception as e:
            log("ERROR", f"Error getting all history from queue: {e}\n{traceback.format_exc()}")
            return OrderedDict()
    
    def _convert_task_to_history_item(self, task, sequence_number: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        将 Task 对象转换为 ComfyUI history 格式
        
        Args:
            task: Task 对象
            sequence_number: 可选的序号（用于排序）
            
        Returns:
            Optional[Dict]: {prompt_id: {prompt, outputs, status, meta}}
        """
        try:
            prompt_id = self._extract_prompt_id(task)
            outputs = self._build_outputs(task)
            prompt_structure = self._build_prompt_structure(task, prompt_id, sequence_number)
            status_obj = self._build_status_object(task, prompt_id)
            meta = self._build_meta_object(outputs)
            
            return {
                prompt_id: {
                    "prompt": prompt_structure,
                    "outputs": outputs,
                    "status": status_obj,
                    "meta": meta
                }
            }
        except Exception as e:
            log("ERROR", f"Error converting task {task.task_id} to history item: {e}\n{traceback.format_exc()}")
            return None
    
    def _extract_prompt_id(self, task) -> str:
        """
        从 Task 对象中提取 prompt_id
        
        优先级：
        1. task.final_status_data.data.prompt_id
        2. task.task_id (fallback)
        """
        # 优先从 final_status_data 获取
        if task.final_status_data:
            prompt_id = (task.final_status_data.get("data", {}) or {}).get("prompt_id")
            if prompt_id:
                return prompt_id
        
        # 最后使用 task_id 作为 fallback
        return task.task_id
    
    def _build_outputs(self, task) -> Dict[str, Dict[str, List[Dict[str, str]]]]:
        """
        构建 outputs 对象
        
        Returns:
            Dict: {node_id: {output_type: [output_items]}}
        """
        outputs = {}
        
        # 获取 results
        results = task.results
        if results is None and task.final_status_data:
            results = (task.final_status_data.get("data", {}) or {}).get("results", [])
        
        # 处理每个 result
        for result in (results or []):
            node_id = result.get("node_id", "unknown")
            output_data = result.get("output", {})
            output_type = output_data.get("type", "images")
            
            # 初始化结构
            if node_id not in outputs:
                outputs[node_id] = {}
            if output_type not in outputs[node_id]:
                outputs[node_id][output_type] = []
            
            # 构建输出项
            raw_data = output_data.get("raw", {})
            comfy_output = {
                "filename": raw_data.get("filename", ""),
                "subfolder": raw_data.get("subfolder", ""),
                "type": raw_data.get("type", "output")
            }
            outputs[node_id][output_type].append(comfy_output)
        
        return outputs
    
    def _build_prompt_structure(self, task, prompt_id: str, sequence_number: Optional[int] = None) -> List:
        """
        构建 prompt 结构体
        
        Returns:
            List: [number, prompt_id, prompt, extra_data, outputs_to_execute]
        """
        number = sequence_number if sequence_number is not None else (
            task.completed_at or task.create_at or 1.0
        )
        
        # 安全地提取 prompt 和 extra_data
        prompt_body = task.prompt_body or {}
        
        # 兼容两种格式：
        # 1. 新格式: {"prompt": {...}, "extra_data": {...}}
        # 2. 旧格式: 直接是 prompt 工作流定义
        if isinstance(prompt_body, dict) and "prompt" in prompt_body:
            prompt = prompt_body.get("prompt", {})
            extra_data = prompt_body.get("extra_data", {})
        else:
            prompt = prompt_body
            extra_data = {}
        
        return [
            number,
            prompt_id,
            prompt or {},
            extra_data or {},
            []
        ]
    
    def _build_status_object(self, task, prompt_id: str) -> Dict[str, Any]:
        """
        构建 status 对象
        
        Returns:
            Dict: {status_str, completed, messages}
        """
        if task.status.name == "FAILED":
            return self._build_error_status(task, prompt_id)
        else:
            return self._build_success_status(task, prompt_id)
    
    def _extract_execution_timestamps(self, task) -> tuple:
        """
        从 status_history 中提取 execution_start 和 execution_end 的时间戳
        
        优先级：
        1. 从 status_history 中找 execution_start 第一个消息
        2. 从 status_history 中找结束标记（优先级：serverless_api > execution_success > execution_error）
        3. 作为 fallback，使用 task 的时间戳
        
        Returns:
            tuple: (start_ts_int, end_ts_int) 以毫秒为单位
        """
        def _normalize_timestamp(ts_value, default_ts_seconds):
            """
            将时间戳标准化为毫秒格式
            
            Args:
                ts_value: 可能的时间戳值（可能是秒或毫秒）
                default_ts_seconds: 默认时间戳（秒格式）
            
            Returns:
                int: 毫秒格式的时间戳
            """
            if ts_value is None:
                return int(default_ts_seconds * 1000)
            
            # 判断是秒还是毫秒：如果小于 10000000000（约 2001年），认为是秒格式
            if ts_value < 10000000000:
                return int(ts_value * 1000)
            else:
                return int(ts_value)
        
        start_ts = None
        end_ts = None
        
        # 从 status_history 中提取时间戳
        for status_msg in task.status_history:
            msg_type = status_msg.get("type")
            msg_data = status_msg.get("data", {})
            
            # 找 execution_start 消息
            if msg_type == "execution_start" and start_ts is None:
                ts_value = msg_data.get("timestamp")
                start_ts = _normalize_timestamp(ts_value, time.time())
            
            # 找执行成功 或 失败的标记
            # 优先级：serverless_api > execution_success > execution_error
            if msg_type == "serverless_api":
                # serverless_api 消息可能没有 timestamp，只有 execution_time
                ts_value = msg_data.get("timestamp")
                if ts_value is None:
                    # 使用 execution_time 计算结束时间戳
                    execution_time = msg_data.get("execution_time")
                    if execution_time is not None:
                        # 先尝试从 start_ts 计算
                        if start_ts is not None:
                            # execution_time 是秒，转换为毫秒并加到开始时间
                            end_ts = start_ts + int(execution_time * 1000)
                        else:
                            # 如果 start_ts 还没找到，使用 task.create_at 作为基准
                            base_ts = task.create_at
                            if base_ts:
                                end_ts = int(base_ts * 1000) + int(execution_time * 1000)
                            else:
                                # 最后 fallback 到 task.completed_at
                                default_ts = task.completed_at
                                end_ts = int(default_ts * 1000) if default_ts else 0
                    else:
                        # 如果没有 execution_time，使用 task.completed_at
                        default_ts = task.completed_at or task.create_at
                        end_ts = int(default_ts * 1000)
                else:
                    default_ts = task.completed_at or task.create_at
                    end_ts = _normalize_timestamp(ts_value, default_ts)
            elif msg_type == "execution_success" and end_ts is None:
                ts_value = msg_data.get("timestamp")
                default_ts = task.completed_at or task.create_at
                end_ts = _normalize_timestamp(ts_value, default_ts)
            elif msg_type == "execution_error" and end_ts is None:
                ts_value = msg_data.get("timestamp")
                default_ts = task.completed_at or task.create_at
                end_ts = _normalize_timestamp(ts_value, default_ts)
        
        if start_ts is None:
            start_ts = int(task.create_at * 1000)
        
        if end_ts is None:
            end_ts = int((task.completed_at or task.create_at) * 1000)
        
        return start_ts, end_ts
    
    def _build_error_status(self, task, prompt_id: str) -> Dict[str, Any]:
        """构建错误状态的 status 对象"""
        data = (task.final_status_data.get("data", {}) if task.final_status_data else {})
        start_ts, error_ts = self._extract_execution_timestamps(task)
        
        return {
            "status_str": "error",
            "completed": True,
            "messages": [
                ["execution_start", {"prompt_id": prompt_id, "timestamp": start_ts}],
                ["execution_error", {
                    "prompt_id": prompt_id,
                    "node_id": data.get("node_id") or data.get("node", "unknown"),
                    "exception_message": data.get("exception_message", "Unknown error"),
                    "timestamp": error_ts
                }]
            ]
        }
    
    def _build_success_status(self, task, prompt_id: str) -> Dict[str, Any]:
        """构建成功状态的 status 对象"""
        start_ts, end_ts = self._extract_execution_timestamps(task)
        
        return {
            "status_str": "success",
            "completed": True,
            "messages": [
                ["execution_start", {"prompt_id": prompt_id, "timestamp": start_ts}],
                ["execution_success", {"prompt_id": prompt_id, "timestamp": end_ts}]
            ]
        }
    
    def _build_meta_object(self, outputs: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """
        构建 meta 对象（记录每个输出节点）
        
        Args:
            outputs: outputs 字典
            
        Returns:
            Dict: {node_id: {node_id, display_node, parent_node, real_node_id}}
        """
        meta = {}
        for node_id in outputs.keys():
            meta[node_id] = {
                "node_id": node_id,
                "display_node": node_id,
                "parent_node": None,
                "real_node_id": node_id
            }
        return meta
    
    def _is_initialized(self) -> bool:
        """检查服务是否已正确初始化"""
        return self.task_manager is not None and self.TaskStatus is not None
    
    def _get_ended_tasks(self, limit: Optional[int] = None) -> List:
        """
        获取已结束的任务列表（按完成时间倒序）
        
        Args:
            limit: 可选的数量限制
            
        Returns:
            List: 已结束的任务列表
        """
        tasks = self.task_manager.get_all_tasks()
        ended = [
            t for t in tasks 
            if t.status in (self.TaskStatus.COMPLETED, self.TaskStatus.FAILED)
        ]
        ended.sort(key=lambda t: t.completed_at or 0, reverse=True)
        
        if isinstance(limit, int) and limit > 0:
            ended = ended[:limit]
        
        return ended
    
    def _parse_limit_param(self) -> Optional[int]:
        """解析请求中的 limit 参数"""
        limit_param = request.args.get('limit')
        if not limit_param:
            return None
        
        try:
            limit = int(limit_param)
            return limit if limit > 0 else None
        except ValueError:
            return None
