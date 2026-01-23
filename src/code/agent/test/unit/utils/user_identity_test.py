"""
测试 utils.user_identity 模块中的用户身份识别功能
"""
import base64
import pytest
from unittest.mock import Mock, patch
from flask import Flask, g

from utils.user_identity import (
    extract_user_from_basic_auth, 
    extract_user_from_header, 
    identify_user_or_default,
    set_user_identity_or_default
)


@pytest.fixture
def app():
    """创建测试用的 Flask 应用"""
    app = Flask(__name__)
    app.config['TESTING'] = True
    return app


class TestExtractUserFromBasicAuth:
    """测试从 Basic Auth 提取用户名"""
    
    def test_valid_basic_auth(self, app):
        """测试有效的 Basic Auth - 提取用户名"""
        username = 'user-h30ua81'
        password = 'QRpT5pPjXj@D6u%R'
        credentials = f"{username}:{password}"
        encoded = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
        auth_header = f"Basic {encoded}"
        
        with app.test_request_context(headers={'Authorization': auth_header}):
            result = extract_user_from_basic_auth()
            assert result == username
    
    def test_no_authorization_header(self, app):
        """测试无 Authorization header"""
        with app.test_request_context():
            result = extract_user_from_basic_auth()
            assert result is None
    
    def test_bearer_token_not_basic(self, app):
        """测试 Bearer Token (不是 Basic Auth)"""
        with app.test_request_context(headers={'Authorization': 'Bearer some-jwt-token'}):
            result = extract_user_from_basic_auth()
            assert result is None
    
    def test_invalid_base64(self, app):
        """测试无效的 Base64 编码"""
        with app.test_request_context(headers={'Authorization': 'Basic invalid-base64!!!'}):
            result = extract_user_from_basic_auth()
            assert result is None
    
    def test_no_colon_in_credentials(self, app):
        """测试格式错误 - 缺少冒号分隔符"""
        invalid_credentials = 'just-username'
        encoded = base64.b64encode(invalid_credentials.encode('utf-8')).decode('utf-8')
        auth_header = f"Basic {encoded}"
        
        with app.test_request_context(headers={'Authorization': auth_header}):
            result = extract_user_from_basic_auth()
            assert result is None
    
    def test_empty_username(self, app):
        """测试空用户名"""
        credentials = ':password'
        encoded = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
        auth_header = f"Basic {encoded}"
        
        with app.test_request_context(headers={'Authorization': auth_header}):
            result = extract_user_from_basic_auth()
            assert result is None
    
    def test_unexpected_exception(self, app):
        """测试未预期的异常"""
        from unittest.mock import patch
        
        auth_header = "Basic dGVzdDp0ZXN0"  # test:test
        
        with app.test_request_context(headers={'Authorization': auth_header}):
            # Patch 被测模块命名空间中的 base64.b64decode
            with patch('utils.user_identity.base64.b64decode', side_effect=RuntimeError("Unexpected error")):
                result = extract_user_from_basic_auth()
                assert result is None


class TestExtractUserFromHeader:
    """测试从 header 提取用户信息"""
    
    def test_multi_tenant_disabled(self, app):
        """测试多租户模式关闭 - extract_user_from_header 仍然提取信息"""
        username = 'user-test'
        
        with patch('utils.user_identity.constants') as mock_constants:
            mock_constants.ENABLE_COMFYUI_MULTI_USER = False
            mock_constants.HEADER_FUNART_COMFY_USERID = 'X-FunArt-Comfy-UserId'
            
            headers = {'X-FunArt-Comfy-UserId': username}
            
            with app.test_request_context(headers=headers):
                result = extract_user_from_header()
                # extract_user_from_header 不关心配置，只负责提取
                assert result == username
    
    def test_basic_auth_authentication(self, app):
        """测试使用 Basic Auth 认证"""
        username = 'user-h30ua81'
        password = 'QRpT5pPjXj@D6u%R'
        credentials = f"{username}:{password}"
        encoded = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
        
        headers = {
            'Authorization': f"Basic {encoded}"
        }
        
        with app.test_request_context(headers=headers):
            result = extract_user_from_header()
            assert result == username
    
    def test_jwt_authentication(self, app):
        """测试使用 JWT 认证"""
        username = 'user-jwt-only'
        
        headers = {
            'X-FunArt-Comfy-UserId': username
        }
        
        with app.test_request_context(headers=headers):
            result = extract_user_from_header()
            assert result == username
    
    def test_no_valid_auth_returns_none(self, app):
        """测试无有效认证信息时返回 None"""
        # 场景1: 完全没有认证 header
        with app.test_request_context():
            result = extract_user_from_header()
            assert result is None
        
        # 场景2: JWT header 为空白字符串
        headers = {'X-FunArt-Comfy-UserId': '   '}
        with app.test_request_context(headers=headers):
            result = extract_user_from_header()
            assert result is None


class TestSetUserIdentityOrDefault:
    """测试 set_user_identity_or_default 函数"""
    
    def test_multi_tenant_with_valid_user(self, app):
        """测试多租户模式下有效用户"""
        username = 'user-test'
        
        with patch('utils.user_identity.constants') as mock_constants:
            mock_constants.ENABLE_COMFYUI_MULTI_USER = True
            mock_constants.HEADER_FUNART_COMFY_USERID = 'X-FunArt-Comfy-UserId'
            
            headers = {'X-FunArt-Comfy-UserId': username}
            
            with app.test_request_context(headers=headers):
                set_user_identity_or_default()
                assert g.user_id == username
    
    def test_multi_tenant_without_user_fallback_to_default(self, app):
        """测试多租户模式下无用户信息时降级到 default"""
        with patch('utils.user_identity.constants') as mock_constants:
            mock_constants.ENABLE_COMFYUI_MULTI_USER = True
            mock_constants.HEADER_FUNART_COMFY_USERID = 'X-FunArt-Comfy-UserId'
            mock_constants.DEFAULT_USER_ID = 'default'
            
            with app.test_request_context():
                set_user_identity_or_default()
                assert g.user_id == 'default'
    
    def test_single_tenant_always_default(self, app):
        """测试单租户模式下总是使用 default"""
        with patch('utils.user_identity.constants') as mock_constants:
            mock_constants.ENABLE_COMFYUI_MULTI_USER = False
            mock_constants.DEFAULT_USER_ID = 'default'
            
            # 即使有用户信息也使用 default
            headers = {'X-FunArt-Comfy-UserId': 'some-user'}
            with app.test_request_context(headers=headers):
                set_user_identity_or_default()
                assert g.user_id == 'default'


class TestIdentifyUserOrDefaultDecorator:
    """测试 identify_user_or_default 装饰器"""
    
    def test_identify_user_or_default_with_valid_user(self, app):
        """测试有效用户使用 identify_user_or_default 装饰器"""
        username = 'user-optional'
        
        @identify_user_or_default
        def test_view():
            return f"User: {g.user_id}"
        
        with patch('utils.user_identity.constants') as mock_constants:
            mock_constants.ENABLE_COMFYUI_MULTI_USER = True
            mock_constants.HEADER_FUNART_COMFY_USERID = 'X-FunArt-Comfy-UserId'
            
            headers = {'X-FunArt-Comfy-UserId': username}
            
            with app.test_request_context(headers=headers):
                result = test_view()
                assert result == f"User: {username}"
                assert g.user_id == username
    
    def test_identify_user_or_default_fallback_scenarios(self, app):
        """测试 identify_user_or_default 在各种降级场景下的行为"""
        @identify_user_or_default
        def test_view():
            return f"User: {g.user_id}"
        
        with patch('utils.user_identity.constants') as mock_constants:
            # 场景1: 多租户模式，无认证信息
            mock_constants.ENABLE_COMFYUI_MULTI_USER = True
            mock_constants.HEADER_FUNART_COMFY_USERID = 'X-FunArt-Comfy-UserId'
            mock_constants.DEFAULT_USER_ID = 'default'
            with app.test_request_context():
                result = test_view()
                assert result == "User: default"
                assert g.user_id == 'default'
            
            # 场景2: 单租户模式，忽略认证信息
            mock_constants.ENABLE_COMFYUI_MULTI_USER = False
            headers = {'X-FunArt-Comfy-UserId': 'some-user'}
            with app.test_request_context(headers=headers):
                result = test_view()
                assert result == "User: default"
                assert g.user_id == 'default'
