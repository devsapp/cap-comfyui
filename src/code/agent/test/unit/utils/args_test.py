"""
测试 utils.args 模块中的参数解析功能
"""
import pytest
from utils.args import (
    parse_extra_boot_args,
    filter_protected_args,
    build_boot_command,
)


class TestParseExtraBootArgs:
    """测试 parse_extra_boot_args 函数"""

    def test_single_flag(self):
        """测试单个标志参数"""
        result = parse_extra_boot_args('--highvram')
        assert result == ['--highvram']

    def test_flag_with_value(self):
        """测试带值的参数"""
        result = parse_extra_boot_args('--preview-method auto')
        assert result == ['--preview-method', 'auto']

    def test_multiple_args(self):
        """测试多个参数组合"""
        result = parse_extra_boot_args('--highvram --preview-method auto --use-pytorch-cross-attention')
        assert result == ['--highvram', '--preview-method', 'auto', '--use-pytorch-cross-attention']

    def test_args_with_double_quotes(self):
        """测试带双引号的参数"""
        result = parse_extra_boot_args('--preview-method "auto" --port 8188')
        assert result == ['--preview-method', 'auto', '--port', '8188']

    def test_args_with_single_quotes(self):
        """测试带单引号的参数"""
        result = parse_extra_boot_args("--preview-method 'auto' --port 8188")
        assert result == ['--preview-method', 'auto', '--port', '8188']

    def test_empty_string(self):
        """测试空字符串"""
        result = parse_extra_boot_args('')
        assert result == []

    def test_whitespace_only(self):
        """测试仅包含空格的字符串"""
        result = parse_extra_boot_args('   ')
        assert result == []

    def test_none_value(self):
        """测试 None 值"""
        result = parse_extra_boot_args(None)
        assert result == []

    def test_complex_combination(self):
        """测试复杂参数组合"""
        result = parse_extra_boot_args(
            '--preview-method auto --highvram --port 8188 --max-upload-size 100'
        )
        assert result == [
            '--preview-method', 'auto', 
            '--highvram', 
            '--port', '8188', 
            '--max-upload-size', '100'
        ]

    def test_args_with_equal_sign(self):
        """测试使用等号的参数格式"""
        result = parse_extra_boot_args('--port=8188 --max-upload-size=100')
        assert result == ['--port=8188', '--max-upload-size=100']

    def test_args_with_path(self):
        """测试包含路径的参数"""
        result = parse_extra_boot_args('--input-directory /path/to/input --output-directory /path/to/output')
        assert result == ['--input-directory', '/path/to/input', '--output-directory', '/path/to/output']

    def test_args_with_quoted_path_containing_spaces(self):
        """测试包含空格的路径（带引号）"""
        result = parse_extra_boot_args('--input-directory "/path/to/my directory"')
        assert result == ['--input-directory', '/path/to/my directory']

    def test_mixed_quotes(self):
        """测试混合使用单引号和双引号"""
        result = parse_extra_boot_args('--method "auto" --name \'test\'')
        assert result == ['--method', 'auto', '--name', 'test']

    def test_args_with_numbers(self):
        """测试数字参数"""
        result = parse_extra_boot_args('--port 8188 --timeout 300 --workers 4')
        assert result == ['--port', '8188', '--timeout', '300', '--workers', '4']

    def test_boolean_flags_only(self):
        """测试多个布尔标志"""
        result = parse_extra_boot_args('--highvram --enable-cors-header --use-pytorch-cross-attention')
        assert result == ['--highvram', '--enable-cors-header', '--use-pytorch-cross-attention']

    def test_leading_and_trailing_whitespace(self):
        """测试前后有空格的输入"""
        result = parse_extra_boot_args('  --highvram --preview-method auto  ')
        assert result == ['--highvram', '--preview-method', 'auto']

    def test_multiple_spaces_between_args(self):
        """测试参数之间有多个空格"""
        result = parse_extra_boot_args('--highvram    --preview-method    auto')
        assert result == ['--highvram', '--preview-method', 'auto']

    def test_real_world_scenario_high_performance(self):
        """测试真实场景：高性能配置"""
        result = parse_extra_boot_args('--highvram --preview-method auto --use-pytorch-cross-attention')
        assert result == ['--highvram', '--preview-method', 'auto', '--use-pytorch-cross-attention']

    def test_real_world_scenario_low_memory(self):
        """测试真实场景：低内存配置"""
        result = parse_extra_boot_args('--lowvram --dont-upcast-attention')
        assert result == ['--lowvram', '--dont-upcast-attention']

    def test_real_world_scenario_development(self):
        """测试真实场景：开发环境配置"""
        result = parse_extra_boot_args('--enable-cors-header --preview-method auto')
        assert result == ['--enable-cors-header', '--preview-method', 'auto']

    def test_special_characters_in_quoted_string(self):
        """测试引号内的特殊字符"""
        result = parse_extra_boot_args('--description "test-value with spaces & special chars!"')
        assert result == ['--description', 'test-value with spaces & special chars!']

    def test_escaped_quotes(self):
        """测试转义的引号"""
        # shlex 应该能正确处理转义
        result = parse_extra_boot_args('--text "He said \\"hello\\""')
        assert result == ['--text', 'He said "hello"']

    def test_very_long_argument_string(self):
        """测试很长的参数字符串"""
        long_args = ' '.join([f'--arg{i} value{i}' for i in range(50)])
        result = parse_extra_boot_args(long_args)
        assert len(result) == 100  # 50 个参数，每个有名称和值

    def test_unicode_characters(self):
        """测试 Unicode 字符"""
        result = parse_extra_boot_args('--name "测试中文" --emoji "🚀"')
        assert result == ['--name', '测试中文', '--emoji', '🚀']


class TestFilterProtectedArgs:
    """测试 filter_protected_args 函数"""
    
    def test_filter_single_protected_arg(self):
        """测试过滤单个受保护参数"""
        args = ['--listen', '127.0.0.1', '--highvram']
        protected = {'--listen'}
        actual_valid_args, actual_excluded_args = filter_protected_args(args, protected)
        
        expected_valid_args = ['--highvram']
        expected_excluded_args = ['--listen']
        assert actual_valid_args == expected_valid_args
        assert actual_excluded_args == expected_excluded_args
    
    def test_filter_multiple_protected_args(self):
        """测试过滤多个受保护参数"""
        args = ['--listen', '0.0.0.0', '--cpu', '--highvram', '--input-directory', '/custom']
        protected = {'--listen', '--cpu', '--input-directory'}
        actual_valid_args, actual_excluded_args = filter_protected_args(args, protected)
        
        expected_valid_args = ['--highvram']
        expected_excluded_args = {'--listen', '--cpu', '--input-directory'}
        assert actual_valid_args == expected_valid_args
        assert set(actual_excluded_args) == expected_excluded_args
    
    def test_no_protected_args(self):
        """测试没有受保护参数"""
        args = ['--highvram', '--preview-method', 'auto']
        protected = {'--listen', '--port', '--cpu'}
        actual_valid_args, actual_excluded_args = filter_protected_args(args, protected)
        
        expected_valid_args = ['--highvram', '--preview-method', 'auto']
        expected_excluded_args = []
        assert actual_valid_args == expected_valid_args
        assert actual_excluded_args == expected_excluded_args
    
    def test_all_protected_args(self):
        """测试全部是受保护参数"""
        args = ['--listen', '0.0.0.0', '--cpu']
        protected = {'--listen', '--cpu'}
        actual_valid_args, actual_excluded_args = filter_protected_args(args, protected)
        
        expected_valid_args = []
        expected_excluded_args = {'--listen', '--cpu'}
        assert actual_valid_args == expected_valid_args
        assert set(actual_excluded_args) == expected_excluded_args
    
    def test_protected_arg_with_equal_sign(self):
        """测试 --key=value 格式的受保护参数"""
        args = ['--port=8188', '--listen=127.0.0.1', '--highvram']
        protected = {'--listen', '--port'}
        actual_valid_args, actual_excluded_args = filter_protected_args(args, protected)
        
        expected_valid_args = ['--highvram']
        expected_excluded_args = {'--listen', '--port'}
        assert actual_valid_args == expected_valid_args
        assert set(actual_excluded_args) == expected_excluded_args


class TestBuildBootCommand:
    """测试 build_boot_command 高层接口"""
    
    def test_complete_workflow_no_custom_args(self):
        """测试完整流程：无自定义参数"""
        base = ['python', 'main.py', '--listen', '0.0.0.0', '--port', '8188']
        protected = {'--listen', '--port'}
        
        result = build_boot_command(base, '', protected)
        
        assert result == base
    
    def test_complete_workflow_with_custom_args(self):
        """测试完整流程：有自定义参数"""
        base = ['python', 'main.py', '--listen', '0.0.0.0', '--port', '8188']
        protected = {'--listen', '--port'}
        custom = '--highvram --preview-method auto'
        
        result = build_boot_command(base, custom, protected)
        
        expected = ['python', 'main.py', '--listen', '0.0.0.0', '--port', '8188', '--highvram', '--preview-method', 'auto']
        assert result == expected
    
    def test_complete_workflow_with_protected_filter(self):
        """测试完整流程：过滤受保护参数"""
        base = ['python', 'main.py', '--listen', '0.0.0.0', '--port', '8188']
        protected = {'--listen', '--port'}  # 所有默认参数都受保护
        custom = '--listen 127.0.0.1 --highvram'
        
        result = build_boot_command(base, custom, protected)
        
        # --listen 和 127.0.0.1 应该被过滤掉，只添加 --highvram
        expected = ['python', 'main.py', '--listen', '0.0.0.0', '--port', '8188', '--highvram']
        assert result == expected
    
    def test_complete_workflow_filter_port(self):
        """测试完整流程：过滤 --port 参数"""
        base = ['python', 'main.py', '--listen', '0.0.0.0', '--port', '8188']
        protected = {'--listen', '--port'}
        custom = '--port 9999 --highvram'
        
        result = build_boot_command(base, custom, protected)
        
        # --port 9999 应该被过滤掉，保持默认的 8188
        expected = ['python', 'main.py', '--listen', '0.0.0.0', '--port', '8188', '--highvram']
        assert result == expected
    
    def test_complete_workflow_only_append(self):
        """测试完整流程：只追加，不覆盖"""
        base = ['python', 'main.py', '--listen', '0.0.0.0', '--port', '8188']
        protected = {'--listen', '--port'}  # 默认参数都受保护
        custom = '--highvram --preview-method auto'
        
        result = build_boot_command(base, custom, protected)
        
        # 结果应该是：base + custom
        expected = base + ['--highvram', '--preview-method', 'auto']
        assert result == expected
    
    def test_complete_workflow_real_scenario(self):
        """测试完整流程：真实场景"""
        base = [
            '/root/venv/bin/python',
            '/root/comfyui/main.py',
            '--listen',
            '0.0.0.0',
            '--port',
            '8188',
            '--input-directory',
            '/mnt/auto/input',
            '--output-directory',
            '/mnt/auto/output',
            '--disable-metadata'
        ]
        protected = {
            '--listen',
            '--port',
            '--input-directory',
            '--output-directory',
            '--disable-metadata'
        }
        custom = '--preview-method auto --highvram --use-pytorch-cross-attention'
        
        result = build_boot_command(base, custom, protected)
        
        expected = [
            '/root/venv/bin/python',
            '/root/comfyui/main.py',
            '--listen',
            '0.0.0.0',
            '--port',
            '8188',
            '--input-directory',
            '/mnt/auto/input',
            '--output-directory',
            '/mnt/auto/output',
            '--disable-metadata',
            '--preview-method',
            'auto',
            '--highvram',
            '--use-pytorch-cross-attention'
        ]
        assert result == expected
