"""
用户身份识别模块

支持多种方式提取用户信息（认证由网关层负责）：
1. JWT 方式：从 X-FunArt-Comfy-UserId header 提取（网关解析 JWT 后注入）
2. Basic Auth 方式：从 Authorization: Basic header 中解析 username

通过 ENABLE_COMFYUI_MULTI_USER 环境变量控制：
- true: 启用多租户模式，支持上述两种方式提取用户信息
- false: 单租户模式，所有用户为 'default'
"""

import base64
from typing import Optional
from functools import wraps
from flask import request, g, abort

import constants
from utils.logger import log


# 用户身份识别相关常量
AUTHORIZATION_HEADER = 'Authorization'
BASIC_AUTH_PREFIX = 'Basic '
DEFAULT_USER_ID = 'default'


def extract_user_from_basic_auth() -> Optional[str]:
    """
    从 Authorization: Basic header 中提取用户名
        
    Returns:
        Optional[str]: 用户ID，解析失败时返回 None
    """
    auth_header = request.headers.get(AUTHORIZATION_HEADER, '')
    
    if not auth_header.startswith(BASIC_AUTH_PREFIX):
        return None
    
    try:
        # 解码 Base64
        encoded_credentials = auth_header[len(BASIC_AUTH_PREFIX):]  # 去掉 'Basic ' 前缀
        decoded_credentials = base64.b64decode(encoded_credentials).decode('utf-8')
        
        # 格式: username:password
        if ':' not in decoded_credentials:
            log("WARNING", "Basic Auth format error: missing colon separator")
            return None
        
        username, _ = decoded_credentials.split(':', 1)
        username = username.strip()
        
        if not username:
            log("WARNING", "Basic Auth format error: empty username")
            return None
        
        return username
        
    except (ValueError, UnicodeDecodeError, AttributeError) as e:
        log("WARNING", f"Basic Auth parse error: {type(e).__name__}: {e}")
        return None
    except Exception as e:
        log("ERROR", f"Unexpected error in extract_user_from_basic_auth: {type(e).__name__}: {e}")
        return None


def extract_user_from_header() -> Optional[str]:
    """
    提取用户ID，支持两种认证方式
    
    - JWT 方式：从 X-FunArt-Comfy-UserId header 获取
    - Basic Auth 方式：从 Authorization: Basic header 解析
    
    Returns:
        Optional[str]: 用户ID，无认证信息时返回 None
    """
    jwt_user = request.headers.get(constants.HEADER_FUNART_COMFY_USERID, '').strip()
    if jwt_user:
        log("DEBUG", f"User extracted from JWT: {jwt_user}")
        return jwt_user
    
    basic_user = extract_user_from_basic_auth()
    if basic_user is not None:
        log("DEBUG", f"User extracted from Basic Auth: {basic_user}")
        return basic_user
    
    # 无认证信息
    log("DEBUG", "No user authentication info found in request headers")
    return None


def set_user_identity_or_default():
    """
    设置用户身份到 flask.g.user_id，如果无法识别则降级到默认用户
    
    在多租户模式下：
    - 尝试从请求中识别用户身份
    - 如果无法识别，降级为 'default' 用户
    
    在单租户模式下：
    - 所有用户统一为 'default'
    
    使用场景：
    - 作为中间件在 before_request 中调用
    - 作为装饰器的内部实现
    """
    if not constants.ENABLE_COMFYUI_MULTI_USER:
        g.user_id = DEFAULT_USER_ID
    else:
        uid = extract_user_from_header()
        g.user_id = uid if uid is not None else DEFAULT_USER_ID


def identify_user_or_default(func):
    """
    装饰器：识别用户身份，如果无法识别则降级到默认用户
    
    这是 set_user_identity_or_default() 的装饰器版本
    """
    @wraps(func)
    def decorated_function(*args, **kwargs):
        set_user_identity_or_default()
        return func(*args, **kwargs)
    return decorated_function
