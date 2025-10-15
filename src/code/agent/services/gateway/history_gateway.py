"""
History Gateway Service
处理 ComfyUI history API 相关的逻辑
"""
import os
import glob
from collections import OrderedDict
from flask import request, jsonify

import constants


class HistoryGatewayService:
    """History网关服务，负责处理历史记录相关请求"""
    
    def __init__(self):
        pass
    
    def handle_history_request(self, api_service, path):
        """
        处理 history 相关请求
        
        Args:
            api_service: ServerlessApiService实例
            path: 请求路径
            
        Returns:
            Flask response
        """
        try:
            print(f"[Enhanced History] Processing history request from persistent storage")
            
            if path == "api/history" and request.method == "GET":
                # GET /api/history - 获取所有历史记录（支持limit参数）
                return self._handle_get_all_history(api_service)
            
            elif path.startswith("api/history/") and request.method == "GET":
                # GET /api/history/{prompt_id} - 获取特定任务的历史记录
                prompt_id = path.split("/")[-1]
                return self._handle_get_history_by_id(api_service, prompt_id)
            
            elif path == "api/history" and request.method == "POST":
                # POST /api/history - 清理历史记录
                return self._handle_clear_history(api_service)
            
            # 其他情况返回空结果
            return jsonify({})
            
        except Exception as e:
            import traceback
            error_msg = f"Enhanced history processing failed: {str(e)}"
            print(f"[Enhanced History] {error_msg}\nStacktrace:\n{traceback.format_exc()}")
            
            # 出错时返回空历史记录而不是代理到 ComfyUI
            return jsonify({})
    
    def _handle_get_all_history(self, api_service):
        """
        处理获取所有历史记录的请求
        """
        print(f"[Enhanced History] Retrieving history from persistent storage")
        
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
        all_history = self._get_all_persisted_history(api_service, limit=limit)
        
        if limit:
            print(f"[Enhanced History] Found {len(all_history)} history items (limited to {limit} most recent)")
        else:
            print(f"[Enhanced History] Found {len(all_history)} history items (no limit)")
        
        return jsonify(all_history)
    
    def _handle_get_history_by_id(self, api_service, prompt_id):
        """
        处理获取特定任务历史记录的请求
        """
        print(f"[Enhanced History] Retrieving history for prompt_id: {prompt_id}")
        
        history_data = self._get_persisted_history_by_prompt_id(api_service, prompt_id)
        
        if history_data:
            print(f"[Enhanced History] Found persisted history for prompt_id: {prompt_id}")
            from flask import Response
            import json
            return Response(
                json.dumps(history_data, ensure_ascii=False),
                mimetype='application/json'
            )
        else:
            print(f"[Enhanced History] No persisted history found for prompt_id: {prompt_id}")
            from flask import Response
            import json
            return Response(
                json.dumps({}, ensure_ascii=False),
                mimetype='application/json'
            )
    
    def _handle_clear_history(self, api_service):
        """
        处理清理历史记录的请求
        """
        request_data = request.get_json() or {}
        
        if request_data.get("clear"):
            print(f"[Enhanced History] Clearing ComfyUI in-memory history")
            
            # 只清理 ComfyUI 的内存历史记录，保留持久化数据
            api_service.api_clear_history()
            
            # 如果需要清理持久化数据，可以在这里添加相关逻辑
            # 目前只清理 ComfyUI 内存，保持持久化数据不变
            
            return jsonify({"status": "success", "message": "ComfyUI memory history cleared"})
        
        return jsonify({})
    
    def _get_all_persisted_history(self, api_service, limit=None):
        """
        从持久化存储获取所有历史记录，按生成时间倒序排序（最新的在前）
        
        Args:
            api_service: ServerlessApiService实例
            limit: 限制返回的记录数量，None表示返回所有记录
        """
        try:
            all_history = OrderedDict()  # 使用有序字典保持排序
            history_with_timestamps = []  # 用于排序的临时列表
            storage_path = f"{constants.MNT_DIR}/output/serverless_api"
            
            if os.path.exists(storage_path):
                # 获取所有存储文件
                task_files = glob.glob(os.path.join(storage_path, "*"))
                print(f"[Enhanced History] Found {len(task_files)} task files in storage")
                
                for task_file in task_files:
                    if os.path.isfile(task_file):
                        task_id = os.path.basename(task_file)
                        try:
                            status_data = api_service.get_status_from_store(task_id)
                            file_mtime = os.path.getmtime(task_file)
                            history_item = self._convert_status_to_history_item(status_data, task_id, file_mtime)
                            if history_item:
                                prompt_id = list(history_item.keys())[0]
                                
                                # 使用prompt中的序号作为排序依据（ComfyUI原生的排序方式）
                                # prompt格式：[number, prompt_id, {...}, {...}, [...]]
                                sort_number = None
                                if history_item[prompt_id].get('prompt'):
                                    prompt_array = history_item[prompt_id]['prompt']
                                    if isinstance(prompt_array, list) and len(prompt_array) > 0:
                                        sort_number = prompt_array[0]  # 第一个元素是序号
                                
                                # 降级方案：使用文件修改时间
                                if sort_number is None:
                                    file_mtime = os.path.getmtime(task_file)
                                    sort_number = file_mtime
                                    print(f"[Enhanced History] Using file mtime for {prompt_id[:12]}... (no prompt number)")
                                else:
                                    print(f"[Enhanced History] Using prompt number {sort_number} for {prompt_id[:12]}...")
                                
                                timestamp = sort_number
                                
                                history_with_timestamps.append({
                                    'prompt_id': prompt_id,
                                    'history_item': history_item,  # 保持完整结构（包含prompt_id key）
                                    'timestamp': timestamp
                                })
                                
                        except Exception as e:
                            print(f"[Enhanced History] Error processing task_id {task_id}: {e}")
                            continue
                
                # 按时间戳倒序排序（最新的在前）
                history_with_timestamps.sort(key=lambda x: x['timestamp'], reverse=True)
                print(f"[Enhanced History] Sorted {len(history_with_timestamps)} history items by timestamp (newest first)")
                
                # 调试信息：显示排序结果的前几条
                if history_with_timestamps:
                    from datetime import datetime
                    print(f"[Enhanced History] Sort order preview:")
                    for i, item in enumerate(history_with_timestamps[:5]):  # 显示前5条
                        timestamp_str = datetime.fromtimestamp(item['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
                        print(f"  {i+1}. {item['prompt_id'][:12]}... - {timestamp_str}")
                
                # 应用limit限制
                if limit is not None and limit > 0:
                    history_with_timestamps = history_with_timestamps[:limit]
                    print(f"[Enhanced History] Limited results to {limit} most recent items")
                
                # 构建最终的历史记录字典，按倒序赋值序号（最新的序号最大）
                total_count = len(history_with_timestamps)
                
                for idx, item in enumerate(history_with_timestamps):
                    prompt_id = item['prompt_id']
                    history_item = item['history_item']  # 完整结构: {prompt_id: {prompt, outputs, status}}
                    
                    # 修改prompt数组的第一个元素为正确的序号（最新的最大）
                    # 前端按 queueIndex 降序排序: sort((a, b) => b.queueIndex - a.queueIndex)
                    sequence_number = total_count - idx
                    if prompt_id in history_item and 'prompt' in history_item[prompt_id]:
                        prompt_array = history_item[prompt_id]['prompt']
                        if isinstance(prompt_array, list) and len(prompt_array) > 0:
                            prompt_array[0] = sequence_number  # 更新序号
                    
                    # 提取内层字典存入all_history
                    all_history[prompt_id] = history_item[prompt_id]
            
            return all_history
            
        except Exception as e:
            print(f"[Enhanced History] Error getting all persisted history: {e}")
            return {}
    
    def _get_persisted_history_by_prompt_id(self, api_service, prompt_id):
        """
        根据 prompt_id 从持久化存储获取历史记录
        """
        try:
            # 构造可能的 task_id 列表
            possible_task_ids = [
                prompt_id,
                f"prompt_{constants.INSTANCE_ID}_{prompt_id}",
                # 可以添加更多可能的 task_id 模式
            ]
            
            # 也可以通过搜索所有文件来查找包含该 prompt_id 的记录
            storage_path = f"{constants.MNT_DIR}/output/serverless_api"
            
            if os.path.exists(storage_path):
                task_files = glob.glob(os.path.join(storage_path, "*"))
                for task_file in task_files:
                    if os.path.isfile(task_file):
                        task_id = os.path.basename(task_file)
                        try:
                            status_data = api_service.get_status_from_store(task_id)
                            for status in status_data:
                                if (status.get("type") == "serverless_api" and 
                                    status.get("data", {}).get("prompt_id") == prompt_id):
                                    return self._convert_status_to_history_item(status_data, task_id)
                        except Exception as e:
                            continue
            
            return None
            
        except Exception as e:
            print(f"[Enhanced History] Error getting persisted history for prompt_id {prompt_id}: {e}")
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
            initial_number = int(file_mtime) if file_mtime else 1
            prompt_structure = [
                initial_number,  # number - 使用时间戳作为初始值
                prompt_id,  # prompt_id
                {},  # prompt_data - 工作流定义（从持久化中可能不完整）
                {},  # extra_data - 额外数据
                []   # outputs_to_execute - 要执行的输出节点
            ]
            
            return {
                prompt_id: {
                    "prompt": prompt_structure,
                    "outputs": outputs,
                    "status": {
                        "status_str": "success",
                        "completed": True,
                        "messages": []
                    }
                }
            }
            
        except Exception as e:
            print(f"[Enhanced History] Error converting status to history: {e}")
            return None
