"""
Unified Error Handler
统一的异常处理和错误响应工具
"""
import traceback
from functools import wraps
from typing import Tuple, Optional

from flask import jsonify
from exceptions.exceptions import CustomError
from utils.logger import log


class ErrorResponse:
    """统一的错误响应格式"""
    
    @staticmethod
    def create(error_type: str, message: str, status_code: int = 500):
        """
        创建统一格式的错误响应
        
        Args:
            error_type: 错误类型（如 "invalid_request_error", "internal_error"）
            message: 错误消息
            status_code: HTTP 状态码
            
        Returns:
            tuple: (jsonify response, status_code)
        """
        return jsonify({
            "error": {
                "type": error_type,
                "message": message
            }
        }), status_code
    
    @staticmethod
    def success(data: dict, status_code: int = 200):
        """
        创建成功响应
        
        Args:
            data: 响应数据
            status_code: HTTP 状态码
            
        Returns:
            tuple: (jsonify response, status_code)
        """
        return jsonify(data), status_code


def handle_exceptions(error_type: str = "operation_error", log_prefix: str = ""):
    """
    装饰器：统一处理路由函数中的异常
    
    Usage:
        @handle_exceptions(error_type="prompt_operation_error", log_prefix="Prompt")
        def handle_prompt():
            # your code here
            
    Args:
        error_type: 错误类型后缀（会添加到错误消息中）
        log_prefix: 日志前缀
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except CustomError as e:
                # 自定义异常：使用定义的错误码和消息
                log("ERROR", f"[{log_prefix}] Custom error: {e.message}")
                return ErrorResponse.create(
                    error_type=error_type,
                    message=e.message,
                    status_code=e.code
                )
            except Exception as e:
                # 未预期的异常：记录堆栈并返回通用错误
                error_msg = f"Failed to {log_prefix.lower()}: {str(e)}"
                log("ERROR", f"{error_msg}\nStacktrace:\n{traceback.format_exc()}")
                return ErrorResponse.create(
                    error_type=error_type,
                    message=error_msg,
                    status_code=500
                )
        return wrapper
    return decorator


def log_and_return_error(
    error: Exception,
    error_type: str,
    log_prefix: str,
    default_message: Optional[str] = None
) -> Tuple:
    """
    记录错误日志并返回统一格式的错误响应
    
    Args:
        error: 异常对象
        error_type: 错误类型
        log_prefix: 日志前缀
        default_message: 默认错误消息（如果不提供，使用异常消息）
        
    Returns:
        tuple: (jsonify response, status_code)
    """
    if isinstance(error, CustomError):
        # 自定义异常
        message = error.message
        status_code = error.code
        log("ERROR", f"[{log_prefix}] Custom error: {message}")
    else:
        # 未预期的异常
        message = default_message or f"Failed to {log_prefix.lower()}: {str(error)}"
        status_code = 500
        log("ERROR", f"[{log_prefix}] {message}\nStacktrace:\n{traceback.format_exc()}")
    
    return ErrorResponse.create(
        error_type=error_type,
        message=message,
        status_code=status_code
    )
