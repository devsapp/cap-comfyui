"""
Reboot Handler
处理服务重启逻辑
"""
import json
import threading
import time
import traceback

from flask import request, jsonify, Response
import requests

import constants
from services.management_service import ManagementService, Action, BackendStatus
from utils.logger import log
from utils.error_handler import ErrorResponse


class RebootHandler:
    """处理服务重启逻辑"""
    
    def __init__(self):
        # 重启锁，防止并发重启
        self._reboot_lock = threading.Lock()
    
    def handle_reboot(self):
        """
        拦截 ComfyUI-Manager 的 reboot 请求，使用管控接口实现重启
        
        CPU 模式：保存当前 snapshot 并通知 GPU 函数重启，然后等待本地 ComfyUI 重启完成
        GPU 模式：直接用 latest-dev 重启
        """
        # 检查是否已有重启在进行中
        if not self._reboot_lock.acquire(blocking=False):
            log("WARNING", "Reboot request rejected: reboot already in progress")
            return ErrorResponse.create(
                error_type="reboot_in_progress",
                message="Reboot already in progress, please wait",
                status_code=409
            )
        
        service = ManagementService()
        
        try:
            log("INFO", f"Received /api/manager/reboot request (mode={constants.COMFYUI_MODE})")
            
            # 开始重启：转换到 REBOOTING 状态
            service._transition_to(BackendStatus.REBOOTING, Action.REBOOT)
            log("INFO", "Reboot started, status set to REBOOTING")
            
            # CPU 模式：保存 snapshot 并通知 GPU 函数重启
            if constants.COMFYUI_MODE == 'cpu':
                # 保存当前 snapshot
                try:
                    from services.workspace.snapshot_manager import SnapshotManager
                    log("INFO", "Saving workspace before reboot...")
                    result_map = service.save(SnapshotManager.TYPE_DEV)
                    log("INFO", f"Save result before reboot: {json.dumps(result_map, indent=2)}")
                except Exception as e:
                    log("WARNING", f"Failed to save workspace before reboot: {str(e)}")
                
                # 触发 GPU 函数的重启
                if constants.GPU_FUNCTION_URL:
                    try:
                        gpu_reboot_url = f"{constants.GPU_FUNCTION_URL.rstrip('/')}/api/manager/reboot"
                        log("INFO", "Triggering reboot to remote GPU service")
                        
                        gpu_headers = {
                            constants.HEADER_FC_INVOCATION_TYPE: 'Async'
                        }
                        
                        gpu_resp = requests.post(gpu_reboot_url, headers=gpu_headers, timeout=10)
                        log("INFO", f"GPU reboot triggered: status={gpu_resp.status_code}")
                    except Exception as e:
                        log("WARNING", f"Failed to trigger GPU reboot: {str(e)}")
                
                # 转发请求给 ComfyUI 后端
                original_uri = request.environ.get('RAW_URI', request.path)
                target_url = f"http://{constants.APP_HOST}{original_uri}"
                log("INFO", f"Forwarding reboot request to ComfyUI backend: {target_url}")
                
                try:
                    resp = requests.request(
                        method=request.method,
                        url=target_url,
                        headers=dict(request.headers),
                        params=request.args,
                        data=request.get_data(),
                        cookies=request.cookies,
                        allow_redirects=False,
                        verify=False,
                        timeout=30
                    )
                    log("DEBUG", f"ComfyUI reboot response: status={resp.status_code}")
                except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                    # ComfyUI 重启时会立即关闭连接，这是预期行为
                    log("DEBUG", f"ComfyUI connection closed during reboot (expected): {type(e).__name__}")
                except requests.exceptions.RequestException as e:
                    # 其他请求异常也记录但不影响重启流程
                    log("WARNING", f"ComfyUI reboot request failed: {type(e).__name__}: {str(e)}")
                
                # 等待 ComfyUI 进程 ready
                log("INFO", "Waiting for ComfyUI process to be ready...")
                try:
                    service._process_mgr.wait_until_ready(
                        poll_interval=constants.DEFAULT_READINESS_POLL_INTERVAL,
                        timeout=constants.DEFAULT_READINESS_TIMEOUT
                    )
                    log("INFO", "ComfyUI process is ready")
                    
                    # 进程 ready 后：从 REBOOTING 转换到 RUNNING
                    service._transition_to(BackendStatus.RUNNING, Action.REBOOT)
                    log("INFO", "Reboot completed successfully, status set to RUNNING")
                    
                    # 返回成功响应
                    return jsonify({
                        "message": "Reboot completed successfully"
                    }), 200
                except Exception as e:
                    error_msg = f"Error waiting for ComfyUI readiness: {str(e)}"
                    log("ERROR", error_msg)
                    raise
            
            # GPU 模式：直接用 latest-dev 重启
            else:
                # GPU 重启必须成功，带重试机制确保可靠性
                # 如果 GPU 重启失败而 CPU 已重启成功，会导致状态不一致
                max_reboot_retries = 3
                reboot_succeeded = False
                last_error = None
                
                for attempt in range(max_reboot_retries):
                    try:
                        log("INFO", f"GPU reboot attempt {attempt + 1}/{max_reboot_retries}")
                        
                        # 停止服务
                        log("INFO", "Stopping GPU service...")
                        service.stop()
                        log("INFO", "GPU service stopped successfully")
                        
                        # 重新启动本地服务（不安装依赖），直接使用 latest-dev
                        log("INFO", "Starting GPU service with latest-dev...")
                        service.start('latest-dev', nodes_map=service.SKIP_INSTALL_SENTINEL)
                        log("INFO", "GPU service started successfully")
                        
                        # 重启成功
                        reboot_succeeded = True
                        break
                        
                    except Exception as e:
                        last_error = e
                        log("WARNING", f"GPU reboot attempt {attempt + 1} failed: {str(e)}")
                        if attempt < max_reboot_retries - 1:
                            log("INFO", f"Retrying in 2 seconds...")
                            time.sleep(2)
                        else:
                            log("ERROR", f"GPU reboot failed after {max_reboot_retries} attempts")
                
                # 检查重启是否成功
                if not reboot_succeeded:
                    error_msg = f"GPU reboot failed after {max_reboot_retries} attempts: {str(last_error)}"
                    log("ERROR", error_msg)
                    raise Exception(error_msg)
                
                # 重启成功：从 REBOOTING 转换到 RUNNING
                # 注意：start() 方法在 REBOOTING 状态下会保持 REBOOTING 状态（不转换到 STARTING）
                # 所以这里需要在 start() 完成后，将状态从 REBOOTING 转换到 RUNNING
                service._transition_to(BackendStatus.RUNNING, Action.REBOOT)
                log("INFO", "Reboot completed successfully, status set to RUNNING")
                
                # 返回成功响应
                return jsonify({
                    "message": "Reboot completed successfully"
                }), 200
            
        except Exception as e:
            error_msg = f"Failed to handle reboot request: {str(e)}"
            log("ERROR", f"{error_msg}\nStacktrace:\n{traceback.format_exc()}")
            
            # 重启失败：从 REBOOTING 转换到 STOPPED
            try:
                service._transition_to(BackendStatus.STOPPED, Action.REBOOT)
                log("INFO", "Reboot failed, status set to STOPPED")
            except Exception as transition_error:
                log("ERROR", f"Failed to transition to STOPPED after reboot failure: {transition_error}")
            
            # 返回错误响应
            return ErrorResponse.create(
                error_type="reboot_failed",
                message=error_msg,
                status_code=500
            )
        finally:
            # 释放重启锁
            self._reboot_lock.release()
            log("DEBUG", "Reboot lock released")

