"""
Reboot Handler
处理服务重启逻辑
"""
import json
import time
import traceback

from flask import request, jsonify, Response
import requests

import constants
from services.management_service import ManagementService, BackendStatus
from utils.logger import log
from utils.error_handler import ErrorResponse


class RebootHandler:
    """处理服务重启逻辑"""
    
    def handle_reboot(self):
        """
        拦截 ComfyUI-Manager 的 reboot 请求，使用管控接口实现重启
        
        并发安全由状态机保证：RUNNING → REBOOTING 的转换在 _status_lock 保护下执行。
        
        CPU 模式：保存当前 snapshot 并通过 header 传递 snapshot 名称给 GPU 函数，然后等待本地 ComfyUI 重启完成
        GPU 模式：
          - 独立 GPU 函数（无 snapshot header）：转发到 ComfyUI backend 直接重启
          - CPU-GPU 架构（有 snapshot header）：停止服务后用指定 snapshot 重启
        """
        service = ManagementService()
        
        try:
            log("DEBUG", f"Received /api/manager/reboot request (mode={constants.COMFYUI_MODE})")
            
            # 开始重启：转换到 REBOOTING 状态
            service._transition_to(BackendStatus.REBOOTING)
            log("INFO", "Starting service reboot...")
            
            # CPU 模式：保存 snapshot 并通知 GPU 函数重启
            if constants.COMFYUI_MODE == 'cpu':
                # 保存当前 snapshot
                snapshot_name = None
                try:
                    from services.workspace.snapshot_manager import SnapshotManager
                    log("INFO", "Saving workspace...")
                    result_map = service.save(SnapshotManager.TYPE_DEV)
                    snapshot_name = result_map.get("snapshot")
                    log("DEBUG", f"Workspace saved: {json.dumps(result_map, indent=2)}")
                except Exception as e:
                    log("WARNING", f"Failed to save workspace: {str(e)}")
                
                # 触发 GPU 函数的重启
                if constants.GPU_FUNCTION_URL and snapshot_name:
                    try:
                        gpu_reboot_url = f"{constants.GPU_FUNCTION_URL.rstrip('/')}/api/manager/reboot"
                        log("DEBUG", f"Notifying GPU service to reload snapshot: {snapshot_name}")
                        
                        gpu_headers = {
                            constants.HEADER_FC_INVOCATION_TYPE: 'Async',
                            constants.HEADER_SNAPSHOT_NAME: snapshot_name  # 传递 snapshot 名称
                        }
                        
                        gpu_resp = requests.post(gpu_reboot_url, headers=gpu_headers, timeout=10)
                        log("DEBUG", f"GPU service notified: status={gpu_resp.status_code}")
                    except Exception as e:
                        log("WARNING", f"Failed to notify GPU service: {str(e)}")
                
                # 转发请求给 ComfyUI 后端
                original_uri = request.environ.get('RAW_URI', request.path)
                target_url = f"http://{constants.APP_HOST}{original_uri}"
                log("DEBUG", f"Forwarding reboot request to: {target_url}")
                
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
                    # 重启时会立即关闭连接，这是预期行为
                    log("DEBUG", f"Connection closed during reboot (expected): {type(e).__name__}")
                except requests.exceptions.RequestException as e:
                    # 其他请求异常也记录但不影响重启流程
                    log("WARNING", f"Reboot request failed: {type(e).__name__}: {str(e)}")
                
                # 等待 ComfyUI 进程 ready
                log("INFO", "Waiting for service to be ready...")
                try:
                    service._process_mgr.wait_until_ready(
                        poll_interval=constants.DEFAULT_READINESS_POLL_INTERVAL,
                        timeout=constants.DEFAULT_READINESS_TIMEOUT
                    )
                    log("DEBUG", "Service is ready")
                    
                    # 进程 ready 后：从 REBOOTING 转换到 RUNNING
                    service._transition_to(BackendStatus.RUNNING)
                    log("INFO", "Service reboot completed successfully")
                    
                    # 返回成功响应
                    return jsonify({
                        "message": "Reboot completed successfully"
                    }), 200
                except Exception as e:
                    error_msg = f"Service failed to become ready: {str(e)}"
                    log("ERROR", error_msg)
                    raise
            
            # GPU 模式：根据是否有 CPU 调用决定重启逻辑
            else:
                # 检查是否来自 CPU 调用（通过 snapshot header 判断）
                snapshot_from_cpu = request.headers.get(constants.HEADER_SNAPSHOT_NAME, '').strip()
                
                # 情况1：独立 GPU 函数（无 CPU 调用）- 调用自身管理接口重启
                if not snapshot_from_cpu:
                    log("INFO", "Restarting ComfyUI service...")
                    
                    # 转发请求给 ComfyUI 后端
                    original_uri = request.environ.get('RAW_URI', request.path)
                    target_url = f"http://{constants.APP_HOST}{original_uri}"
                    log("DEBUG", f"Forwarding reboot request to: {target_url}")
                    
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
                        # 重启时会立即关闭连接，这是预期行为
                        log("DEBUG", f"Connection closed during reboot (expected): {type(e).__name__}")
                    except requests.exceptions.RequestException as e:
                        # 其他请求异常也记录但不影响重启流程
                        log("WARNING", f"Reboot request failed: {type(e).__name__}: {str(e)}")
                    
                    # 等待 ComfyUI 进程 ready
                    log("INFO", "Waiting for service to be ready...")
                    try:
                        service._process_mgr.wait_until_ready(
                            poll_interval=constants.DEFAULT_READINESS_POLL_INTERVAL,
                            timeout=constants.DEFAULT_READINESS_TIMEOUT
                        )
                        log("DEBUG", "Service is ready")
                        
                        # 进程 ready 后：从 REBOOTING 转换到 RUNNING
                        service._transition_to(BackendStatus.RUNNING)
                        log("INFO", "Service reboot completed successfully")
                        
                        # 返回成功响应
                        return jsonify({
                            "message": "Reboot completed successfully"
                        }), 200
                    except Exception as e:
                        error_msg = f"Service failed to become ready: {str(e)}"
                        log("ERROR", error_msg)
                        raise
                
                # 情况2：CPU-GPU 架构 - 重新加载快照
                else:
                    log("INFO", f"Reloading workspace from snapshot: {snapshot_from_cpu}")
                    
                    # GPU 重启必须成功，带重试机制确保可靠性
                    # 如果 GPU 重启失败而 CPU 已重启成功，会导致状态不一致
                    max_reboot_retries = 3
                    reboot_succeeded = False
                    last_error = None
                    
                    for attempt in range(max_reboot_retries):
                        try:
                            log("DEBUG", f"Reboot attempt {attempt + 1}/{max_reboot_retries}")
                            
                            # 停止服务
                            log("DEBUG", "Stopping service...")
                            service.stop()
                            log("DEBUG", "Service stopped")
                            
                            # 重新启动本地服务（不安装依赖），使用 CPU 传递的 snapshot
                            log("DEBUG", f"Starting service with snapshot: {snapshot_from_cpu}")
                            service.start(snapshot_from_cpu, nodes_map=service.SKIP_INSTALL_SENTINEL)
                            log("DEBUG", "Service started")
                            
                            # 重启成功
                            reboot_succeeded = True
                            break
                            
                        except Exception as e:
                            last_error = e
                            log("WARNING", f"Reboot attempt {attempt + 1} failed: {str(e)}")
                            if attempt < max_reboot_retries - 1:
                                log("DEBUG", f"Retrying in 2 seconds...")
                                time.sleep(2)
                            else:
                                log("ERROR", f"All reboot attempts failed")
                    
                    # 检查重启是否成功
                    if not reboot_succeeded:
                        error_msg = f"Failed to reload workspace after {max_reboot_retries} attempts: {str(last_error)}"
                        log("ERROR", error_msg)
                        raise Exception(error_msg)
                    
                    # 重启成功：从 REBOOTING 转换到 RUNNING
                    # 注意：start() 方法在 REBOOTING 状态下会保持 REBOOTING 状态（不转换到 STARTING）
                    # 所以这里需要在 start() 完成后，将状态从 REBOOTING 转换到 RUNNING
                    service._transition_to(BackendStatus.RUNNING)
                    log("INFO", "Workspace reloaded successfully")
                    
                    # 返回成功响应
                    return jsonify({
                        "message": "Reboot completed successfully"
                    }), 200
            
        except Exception as e:
            error_msg = f"Service reboot failed: {str(e)}"
            log("ERROR", f"{error_msg}\nStacktrace:\n{traceback.format_exc()}")
            
            # 重启失败：从 REBOOTING 转换到 REBOOT_FAILED
            try:
                service._transition_to(BackendStatus.REBOOT_FAILED)
                log("ERROR", "Service status set to REBOOT_FAILED, manual intervention may be required")
            except Exception as transition_error:
                log("ERROR", f"Failed to update service status: {transition_error}")
            
            # 返回错误响应
            return ErrorResponse.create(
                error_type="reboot_failed",
                message=error_msg,
                status_code=500
            )
