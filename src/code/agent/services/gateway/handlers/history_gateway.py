"""
History Gateway Service
处理 ComfyUI history API 相关的逻辑
"""
import os
import json
import glob
import time
import traceback
from collections import OrderedDict
from datetime import datetime
from flask import request, jsonify

import constants
from utils.logger import log


class HistoryGatewayService:
    
    def __init__(self):
        # 直接访问存储路径，不需要依赖 ServerlessApiService
        self.storage_path = f"{constants.MNT_DIR}/output/serverless_api"
    
    def handle_history_request(self, path):
        """
        处理 history 相关请求
        
        Args:
            path: 请求路径
            
        Returns:
            Flask response
        """
        try:
            log("DEBUG", f"Processing history request from persistent storage")
            
            if path == "api/history" and request.method == "GET":
                return self._handle_get_all_history()
            
            elif path.startswith("api/history/") and request.method == "GET":
                # GET /api/history/{prompt_id} - 获取特定任务的历史记录
                prompt_id = path.split("/")[-1]
                return self._handle_get_history_by_id(prompt_id)
            
            elif path == "api/history" and request.method == "POST":
                # POST /api/history - 清理历史记录
                return self._handle_clear_history()
            
            # 其他情况返回空结果
            return jsonify({})
            
        except Exception as e:
            error_msg = f"Enhanced history processing failed: {str(e)}"
            log("ERROR", f"{error_msg}\nStacktrace:\n{traceback.format_exc()}")
            
            # 出错时返回空历史记录而不是代理到 ComfyUI
            return jsonify({})
    
    def _handle_get_all_history(self):
        """
        处理获取所有历史记录的请求
        """
        log("DEBUG", f"Retrieving history from persistent storage")
        
        # 获取limit参数
        limit_param = request.args.get('limit')
        limit = None
        if limit_param:
            try:
                limit = int(limit_param)
                if limit <= 0:
                    limit = None  # 无效值时不限制
            except ValueError:
                limit = None  # 无效值时不限制
        
        # 从持久化存储获取历史记录
        all_history = self._get_all_persisted_history(limit=limit)
        
        if limit:
            log("DEBUG", f"Found {len(all_history)} history items (limited to {limit} most recent)")
        else:
            log("DEBUG", f"Found {len(all_history)} history items (no limit)")
        
        return jsonify(all_history)
    
    def _handle_get_history_by_id(self, prompt_id):
        """
        处理获取特定任务历史记录的请求
        """
        log("DEBUG", f"Retrieving history for prompt_id: {prompt_id}")
        
        history_data = self._get_persisted_history_by_prompt_id(prompt_id)
        
        if history_data:
            log("DEBUG", f"Found persisted history for prompt_id: {prompt_id}")
            return jsonify(history_data)
        else:
            log("DEBUG", f"No persisted history found for prompt_id: {prompt_id}")
            return jsonify({})
    
    def _handle_clear_history(self):
        """
        处理清理历史记录的请求
        
        注意：此方法目前不清理持久化存储的历史，
        只返回成功响应。如需清理持久化数据，
        需要单独实现。
        """
        request_data = request.get_json() or {}
        
        if request_data.get("clear"):
            log("INFO", f"Clear history requested (persistent storage not affected)")
            
            # 持久化存储的历史不清理
            # 如果需要清理，可以删除 self.storage_path 下的文件
            
            return jsonify({"status": "success", "message": "History clear acknowledged (persistent storage preserved)"})
        
        return jsonify({})
    
    def _get_all_persisted_history(self, limit=None):
        """
        从持久化存储获取所有历史记录，按文件修改时间倒序排序（最新的在前）
        
        Args:
            limit: 限制返回的记录数量，None表示返回所有记录
        """
        try:
            if not os.path.exists(self.storage_path):
                return OrderedDict()
            
            # 获取所有存储文件，按修改时间排序
            task_files = glob.glob(os.path.join(self.storage_path, "*"))
            task_files = [f for f in task_files if os.path.isfile(f)]
            task_files.sort(key=os.path.getmtime, reverse=True)  # 最新的在前
            
            log("DEBUG", f"Found {len(task_files)} task files in storage")
            
            # 应用limit限制
            if limit is not None and limit > 0:
                task_files = task_files[:limit]
            
            all_history = OrderedDict()
            total_count = len(task_files)
            
            for idx, task_file in enumerate(task_files):
                task_id = os.path.basename(task_file)
                try:
                    status_data = self._get_status_from_file(task_id)
                    file_mtime = os.path.getmtime(task_file)
                    history_item = self._convert_status_to_history_item(status_data, task_id, file_mtime)
                    if history_item:
                        prompt_id = list(history_item.keys())[0]
                        # 更新序号（最新的序号最大，倒序）
                        if prompt_id in history_item and 'prompt' in history_item[prompt_id]:
                            prompt_array = history_item[prompt_id]['prompt']
                            if isinstance(prompt_array, list) and len(prompt_array) > 0:
                                prompt_array[0] = total_count - idx
                        all_history[prompt_id] = history_item[prompt_id]
                except Exception as e:
                    log("WARNING", f"Error processing task_id {task_id}: {e}")
                    continue
            
            return all_history
            
        except Exception as e:
            log("ERROR", f"Error getting all persisted history: {e}")
            return OrderedDict()
    
    def _get_persisted_history_by_prompt_id(self, prompt_id):
        """
        根据 prompt_id 从持久化存储获取历史记录
        
        首先尝试可能的 task_id 路径，如果失败则遍历所有文件查找
        """
        try:
            # 首先尝试可能的 task_id 路径（性能优化）
            possible_task_ids = [
                prompt_id,
                f"prompt_{constants.INSTANCE_ID}_{prompt_id}",
            ]
            
            for task_id in possible_task_ids:
                file_path = os.path.join(self.storage_path, task_id)
                if os.path.exists(file_path) and os.path.isfile(file_path):
                    try:
                        status_data = self._get_status_from_file(task_id)
                        # 验证是否包含该 prompt_id
                        for status in status_data:
                            if (status.get("type") == "serverless_api" and 
                                status.get("data", {}).get("prompt_id") == prompt_id):
                                file_mtime = os.path.getmtime(file_path)
                                return self._convert_status_to_history_item(status_data, task_id, file_mtime)
                    except Exception as e:
                        log("DEBUG", f"Error checking task_id {task_id} for prompt_id {prompt_id}: {e}")
                        continue
            
            # 如果直接路径查找失败，遍历所有文件查找（降级方案）
            if os.path.exists(self.storage_path):
                task_files = glob.glob(os.path.join(self.storage_path, "*"))
                for task_file in task_files:
                    if os.path.isfile(task_file):
                        task_id = os.path.basename(task_file)
                        # 跳过已经尝试过的 task_id
                        if task_id in possible_task_ids:
                            continue
                        try:
                            status_data = self._get_status_from_file(task_id)
                            for status in status_data:
                                if (status.get("type") == "serverless_api" and 
                                    status.get("data", {}).get("prompt_id") == prompt_id):
                                    file_mtime = os.path.getmtime(task_file)
                                    return self._convert_status_to_history_item(status_data, task_id, file_mtime)
                        except Exception as e:
                            log("DEBUG", f"Error checking task_id {task_id} for prompt_id {prompt_id}: {e}")
                            continue
            
            return None
            
        except Exception as e:
            log("ERROR", f"Error getting persisted history for prompt_id {prompt_id}: {e}")
            return None
    
    def _convert_status_to_history_item(self, status_data, task_id, file_mtime=None):
        """
        将 ServerlessApiService 的状态数据转换为 ComfyUI 完全兼容的历史记录格式
        根据 ComfyUI 原生格式：
        {
          "prompt_id": {
            "prompt": [number, "prompt_id", {prompt_data}, {extra_data}, [outputs_to_execute]],
            "outputs": {"node_id": {"output_type": [output_data, ...]}},
            "status": {"status_str": "success", "completed": true, "messages": []}
          }
        }
        """
        try:
            if not status_data:
                return None
            
            # 查找最终结果
            final_result = None
            for status in reversed(status_data):  # 从最新的开始查找
                if status.get("type") == "serverless_api":
                    final_result = status
                    break
            
            if not final_result:
                return None
            
            data = final_result.get("data", {})
            prompt_id = data.get("prompt_id", task_id)
            results = data.get("results", [])
            execution_time = data.get("execution_time")  # 获取执行时间
            
            # 构造 ComfyUI 兼容的输出格式
            outputs = {}
            for result in results:
                node_id = result.get("node_id", "unknown")
                if node_id not in outputs:
                    outputs[node_id] = {}
                
                output_data = result.get("output", {})
                output_type = output_data.get("type", "images")
                
                if output_type not in outputs[node_id]:
                    outputs[node_id][output_type] = []
                
                # 构造符合 ComfyUI 原生格式的输出数据
                raw_data = output_data.get("raw", {})
                comfy_output = {
                    "filename": raw_data.get("filename", ""),
                    "subfolder": raw_data.get("subfolder", ""),
                    "type": raw_data.get("type", "output")
                }
                
                # 只在 debug 模式下添加增强信息，保持最大兼容性
                # 除非用户明确需要增强信息。在正常情况下不添加任何非标准字段
                outputs[node_id][output_type].append(comfy_output)
            
            # 构造符合 ComfyUI 格式的 prompt 数据结构
            # ComfyUI 原生格式: [number, prompt_id, {prompt_data}, {extra_data}, [outputs_to_execute]]
            # 使用文件修改时间作为初始序号，后续会被正确的序号覆盖
            # 注意：保留浮点数精度，后续在排序时会使用
            initial_number = file_mtime if file_mtime else 1.0
            prompt_structure = [
                initial_number,  # number - 使用时间戳作为初始值
                prompt_id,  # prompt_id
                {},  # prompt_data - 工作流定义（从持久化中可能不完整）
                {},  # extra_data - 额外数据
                []   # outputs_to_execute - 要执行的输出节点
            ]
            
            # 构造 status 对象，与 ComfyUI 完全一致
            # ComfyUI 的 ExecutionStatus 格式: {status_str, completed, messages}
            # messages 格式: List[Tuple[str, dict]]，每个消息包含 timestamp
            
            # 计算时间戳
            # 如果有 execution_time，使用它来计算准确的开始和结束时间
            # 否则使用文件修改时间作为参考
            if execution_time is not None and file_mtime is not None:
                # 使用文件修改时间作为结束时间，向前推 execution_time 作为开始时间
                end_timestamp = int(file_mtime * 1000)
                start_timestamp = end_timestamp - int(execution_time * 1000)
            elif file_mtime is not None:
                # 没有 execution_time，使用文件修改时间作为结束时间，向前推1秒作为开始时间（默认）
                end_timestamp = int(file_mtime * 1000)
                start_timestamp = end_timestamp - 1000  # 默认1秒
            else:
                # 降级方案：使用当前时间
                current_timestamp = int(time.time() * 1000)
                end_timestamp = current_timestamp
                start_timestamp = current_timestamp - 1000
            
            # 构造 messages，与 ComfyUI 格式完全一致
            # ComfyUI 会发送 execution_start 和 execution_success 消息
            status_obj = {
                "status_str": "success",
                "completed": True,
                "messages": [
                    [
                        "execution_start",
                        {
                            "prompt_id": prompt_id,
                            "timestamp": start_timestamp
                        }
                    ],
                    [
                        "execution_success",
                        {
                            "prompt_id": prompt_id,
                            "timestamp": end_timestamp
                        }
                    ]
                ]
            }
            
            return {
                prompt_id: {
                    "prompt": prompt_structure,
                    "outputs": outputs,
                    "status": status_obj
                }
            }
            
        except Exception as e:
            log("ERROR", f"Error converting status to history: {e}")
            return None
    
    def _get_status_from_file(self, task_id: str):
        """
        从文件读取任务状态
        
        Args:
            task_id: 任务ID
            
        Returns:
            list: 状态历史列表
        """
        try:
            file_path = os.path.join(self.storage_path, task_id)
            if not os.path.exists(file_path):
                return []
            
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                status_list = []
                for line in content.split("\n"):
                    line = line.strip()
                    if line:
                        try:
                            status_list.append(json.loads(line))
                        except json.JSONDecodeError as e:
                            log("WARNING", f"Error parsing JSON line in file {task_id}: {e}")
                            continue
                return status_list
        except Exception as e:
            log("ERROR", f"Error reading status from file {task_id}: {e}")
            return []

