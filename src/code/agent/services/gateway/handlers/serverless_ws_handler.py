"""
Serverless WebSocket Handler
处理 /api/serverless/ws 的 WebSocket 连接，转发到 GPU 的 HTTP SSE 接口
"""
import json
import requests
from flask import request
from simple_websocket import Server

from utils.logger import log


class ServerlessWsHandler:
    """处理 Serverless WebSocket 转发到 GPU (WS->/api/serverless/ws)"""
    
    def __init__(self, gpu_function_url, task_manager=None):
        self.gpu_function_url = gpu_function_url
        self.task_manager = task_manager
    
    def _extract_task_id(self) -> str:
        """
        从请求头中提取任务ID
        
        Returns:
            str: task_id
        """
        return request.headers.get('x-fc-request-id')
    
    def handle_connection(self, ws: Server):
        """
        处理客户端 WebSocket 连接，转发到 GPU 的 HTTP SSE 接口
        
        Args:
            ws: 客户端 WebSocket 连接
        """
        task_id = self._extract_task_id()
        
        # 检查 GPU URL 配置
        if not self.gpu_function_url:
            log("ERROR", f"[ServerlessWS][{task_id}] GPU_FUNCTION_URL not configured")
            try:
                ws.send(json.dumps({
                    "type": "error",
                    "error_code": "configuration_error",
                    "error_message": "GPU_FUNCTION_URL not configured for CPU mode"
                }))
            except:
                pass
            return
        
        log("INFO", f"[ServerlessWS][{task_id}] Client connected")
        
        try:
            # 接收客户端发送的 prompt
            data = ws.receive()
            if not data:
                log("ERROR", f"[ServerlessWS][{task_id}] No data received from client")
                return
            
            # 解析 prompt（验证 JSON）
            try:
                prompt = json.loads(data)
            except json.JSONDecodeError as e:
                error_msg = f"Invalid JSON: {str(e)}"
                log("ERROR", f"[ServerlessWS][{task_id}] {error_msg}")
                ws.send(json.dumps({
                    "type": "error",
                    "error_code": "invalid_json",
                    "error_message": error_msg
                }))
                return
            
            log("INFO", f"[ServerlessWS][{task_id}] Received prompt, forwarding to GPU via HTTP")
            
            # 构造请求参数
            params = {"stream": "true"}
            if request.args.get("output_base64"):
                params["output_base64"] = request.args["output_base64"]
            if request.args.get("output_oss"):
                params["output_oss"] = request.args["output_oss"]
            
            # 准备 headers
            headers = {
                "x-fc-async-task-id": task_id,
                "x-fc-task-id": task_id,
                "Content-Type": "application/json",
            }
            
            # 发送 HTTP POST 请求到 GPU（流式）
            gpu_url = f"{self.gpu_function_url.rstrip('/')}/api/serverless/run"
            log("DEBUG", f"[ServerlessWS][{task_id}] POST {gpu_url} with stream=true")
            
            resp = requests.post(
                gpu_url,
                json=prompt,
                params=params,
                headers=headers,
                stream=True,
                timeout=600  # 10分钟超时
            )
            
            if resp.status_code != 200:
                error_msg = f"GPU returned HTTP {resp.status_code}"
                log("ERROR", f"[ServerlessWS][{task_id}] {error_msg}")
                ws.send(json.dumps({
                    "type": "error",
                    "error_code": "gpu_http_error",
                    "error_message": error_msg
                }))
                return
            
            log("INFO", f"[ServerlessWS][{task_id}] Streaming response from GPU")
            
            for line in resp.iter_lines():
                if not line:
                    continue
                
                line_str = line.decode("utf-8")
                
                if line_str.startswith("data: "):
                    message = line_str[6:]  # 去掉 "data: " 前缀
                    try:
                        ws.send(message)
                        log("DEBUG", f"[ServerlessWS][{task_id}] Forwarded: {message[:100]}...")
                    except Exception as e:
                        log("ERROR", f"[ServerlessWS][{task_id}] Failed to send to client: {e}")
                        break
            
            log("INFO", f"[ServerlessWS][{task_id}] Streaming completed")
        
        except requests.exceptions.Timeout:
            error_msg = "Request to GPU timed out"
            log("ERROR", f"[ServerlessWS][{task_id}] {error_msg}")
            try:
                ws.send(json.dumps({
                    "type": "error",
                    "error_code": "gpu_timeout",
                    "error_message": error_msg
                }))
            except:
                pass
        
        except requests.exceptions.RequestException as e:
            error_msg = f"Request to GPU failed: {str(e)}"
            log("ERROR", f"[ServerlessWS][{task_id}] {error_msg}")
            try:
                ws.send(json.dumps({
                    "type": "error",
                    "error_code": "gpu_request_error",
                    "error_message": error_msg
                }))
            except:
                pass
        
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            log("ERROR", f"[ServerlessWS][{task_id}] {error_msg}")
            try:
                ws.send(json.dumps({
                    "type": "error",
                    "error_code": "internal_error",
                    "error_message": error_msg
                }))
            except:
                pass
        
        finally:
            log("INFO", f"[ServerlessWS][{task_id}] Connection closed")
