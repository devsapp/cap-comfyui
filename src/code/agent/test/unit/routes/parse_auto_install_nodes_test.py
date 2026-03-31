"""parse_auto_install_nodes 解析逻辑单元测试
===============================================
routes.routes.parse_auto_install_nodes 负责将 AUTO_INSTALL_NODES 环境变量原始字符串
解析为 nodes_map，供 ManagementService.start() 使用。

覆盖所有分支："*"、有效 JSON dict、空 dict、JSON 数组、非法 JSON、空串、None。
"""
import json
import unittest

import constants
from routes.routes import parse_auto_install_nodes


class TestParseAutoInstallNodes(unittest.TestCase):

    def test_star_returns_none(self):
        """'*' → 安装所有插件"""
        result = parse_auto_install_nodes('*')
        self.assertIsNone(result)

    def test_star_with_whitespace(self):
        """' * ' → strip 后等同于 '*'"""
        result = parse_auto_install_nodes('  *  ')
        self.assertIsNone(result)

    def test_valid_json_dict_single_node(self):
        """单个插件的 JSON dict → 返回解析后的 dict"""
        raw = json.dumps({"NodeA": {"source": {"cloneUrl": "https://github.com/a/a.git"}}})
        result = parse_auto_install_nodes(raw)
        self.assertIsInstance(result, dict)
        self.assertEqual(len(result), 1)
        self.assertIn("NodeA", result)

    def test_valid_json_dict_multiple_nodes(self):
        """多个插件的 JSON dict → 返回正确数量的 dict"""
        raw = json.dumps({"NodeA": {}, "NodeB": {}, "NodeC": {}})
        result = parse_auto_install_nodes(raw)
        self.assertEqual(len(result), 3)

    def test_empty_json_dict_returns_sentinel(self):
        """空 JSON dict '{}' → parsed 为 dict 但为空，应返回 sentinel"""
        result = parse_auto_install_nodes('{}')
        self.assertIs(result, constants.SKIP_INSTALL_SENTINEL)

    def test_json_array_returns_sentinel(self):
        """JSON 数组 '[]' → 不是 dict，返回 sentinel"""
        result = parse_auto_install_nodes('[1, 2, 3]')
        self.assertIs(result, constants.SKIP_INSTALL_SENTINEL)

    def test_json_string_returns_sentinel(self):
        """JSON 字符串 '"hello"' → 不是 dict，返回 sentinel"""
        result = parse_auto_install_nodes('"hello"')
        self.assertIs(result, constants.SKIP_INSTALL_SENTINEL)

    def test_invalid_json_returns_sentinel(self):
        """非法 JSON 字符串 → JSONDecodeError 被捕获，返回 sentinel"""
        result = parse_auto_install_nodes('{not valid json}')
        self.assertIs(result, constants.SKIP_INSTALL_SENTINEL)

    def test_empty_string_returns_sentinel(self):
        """空字符串 → 跳过安装"""
        result = parse_auto_install_nodes('')
        self.assertIs(result, constants.SKIP_INSTALL_SENTINEL)

    def test_none_returns_sentinel(self):
        """None → (None or '').strip() == ''，跳过安装"""
        result = parse_auto_install_nodes(None)
        self.assertIs(result, constants.SKIP_INSTALL_SENTINEL)

    def test_whitespace_only_returns_sentinel(self):
        """纯空白字符串 → strip 后为空，返回 sentinel"""
        result = parse_auto_install_nodes('   \n\t  ')
        self.assertIs(result, constants.SKIP_INSTALL_SENTINEL)

    def test_random_non_json_string_returns_sentinel(self):
        """任意非 JSON / 非 '*' 字符串 → 返回 sentinel"""
        result = parse_auto_install_nodes('some_random_text')
        self.assertIs(result, constants.SKIP_INSTALL_SENTINEL)

    def test_json_number_returns_sentinel(self):
        """JSON 数字 '42' → 不是 dict，返回 sentinel"""
        result = parse_auto_install_nodes('42')
        self.assertIs(result, constants.SKIP_INSTALL_SENTINEL)

    def test_returned_dict_is_parsed_not_raw(self):
        """确认返回的 dict 是 json.loads 解析后的 Python 对象"""
        raw = json.dumps({"ComfyUI-nunchaku": {"version": "v0.2.0"}})
        result = parse_auto_install_nodes(raw)
        self.assertEqual(result["ComfyUI-nunchaku"]["version"], "v0.2.0")


if __name__ == "__main__":
    unittest.main()
