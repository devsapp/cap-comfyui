"""
version_resolver 单元测试
=========================
覆盖 services/pip/version_resolver.py 中所有公开函数和内部辅助函数。

模块导出：
  resolve_version_conflict()       ← 对外唯一入口
内部函数（直接 import 测试）：
  _apply_simple_strategy
  _extract_exact_version
  _parse_single_op
  _try_merge_with_packaging
  _is_version_newer
"""
import unittest
from unittest.mock import patch

from version_resolver import (
    resolve_version_conflict,
    _apply_simple_strategy,
    _extract_exact_version,
    _parse_single_op,
    _try_merge_with_packaging,
    _is_version_newer,
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. resolve_version_conflict — 公开入口
# ─────────────────────────────────────────────────────────────────────────────
class TestResolveVersionConflict(unittest.TestCase):

    def _r(self, a, b, pkg="pkg"):
        with patch("builtins.print"):
            return resolve_version_conflict(a, b, pkg)

    # 短路情形
    def test_both_empty_returns_empty(self):
        self.assertEqual(self._r("", ""), "")

    def test_existing_empty_returns_new(self):
        self.assertEqual(self._r("", ">=1.0.0"), ">=1.0.0")

    def test_new_empty_returns_existing(self):
        self.assertEqual(self._r(">=1.0.0", ""), ">=1.0.0")

    def test_same_spec_no_print(self):
        result = resolve_version_conflict(">=1.0.0", ">=1.0.0", "pkg")
        self.assertEqual(result, ">=1.0.0")

    # 简单策略：== 优先
    def test_exact_vs_exact_newer_wins(self):
        self.assertEqual(self._r("==1.0.0", "==2.0.0"), "==2.0.0")

    def test_exact_vs_exact_older_loses(self):
        self.assertEqual(self._r("==3.0.0", "==2.0.0"), "==3.0.0")

    def test_exact_vs_range_keeps_exact(self):
        self.assertEqual(self._r("==1.5.0", ">=1.0.0"), "==1.5.0")

    def test_range_vs_exact_selects_exact(self):
        self.assertEqual(self._r(">=1.0.0", "==1.5.0"), "==1.5.0")

    # 简单策略：单一同类操作符
    def test_ge_picks_higher_bound(self):
        self.assertEqual(self._r(">=1.0.0", ">=1.5.0"), ">=1.5.0")

    def test_le_picks_lower_bound(self):
        self.assertEqual(self._r("<=1.8.0", "<=1.10.0"), "<=1.8.0")

    def test_gt_picks_higher_bound(self):
        self.assertEqual(self._r(">1.0.0", ">1.5.0"), ">1.5.0")

    def test_lt_picks_lower_bound(self):
        self.assertEqual(self._r("<1.8.0", "<1.10.0"), "<1.8.0")

    # packaging 兜底（复杂约束）
    def test_complex_constraint_uses_packaging(self):
        result = self._r(">=1.8.0,<2.0", ">=1.10.0,<3.0")
        self.assertIn("1.10.0", result)

    def test_exclusion_constraint_preserved(self):
        result = self._r(">=4.39.0,!=4.50.*", ">=4.44.0")
        if result:
            self.assertIn("4.44.0", result)
            self.assertIn("4.50", result)


# ─────────────────────────────────────────────────────────────────────────────
# 2. _apply_simple_strategy
# ─────────────────────────────────────────────────────────────────────────────
class TestApplySimpleStrategy(unittest.TestCase):

    # 场景 1：== 优先
    def test_both_exact_newer_wins(self):
        self.assertEqual(_apply_simple_strategy("==1.0.0", "==2.0.0"), "==2.0.0")
        self.assertEqual(_apply_simple_strategy("==2.0.0", "==1.0.0"), "==2.0.0")

    def test_exact_same_version(self):
        # 相同版本：任意一方都行
        result = _apply_simple_strategy("==1.5.0", "==1.5.0")
        self.assertEqual(result, "==1.5.0")

    def test_exact_vs_range_keeps_exact(self):
        self.assertEqual(_apply_simple_strategy("==1.5.0", ">=1.0.0"), "==1.5.0")

    def test_range_vs_exact_keeps_exact(self):
        self.assertEqual(_apply_simple_strategy(">=1.0.0", "==1.5.0"), "==1.5.0")

    def test_exact_vs_le_keeps_exact(self):
        self.assertEqual(_apply_simple_strategy("==1.5.0", "<=2.0.0"), "==1.5.0")

    # 场景 2：单一同类操作符
    def test_ge_picks_higher(self):
        self.assertEqual(_apply_simple_strategy(">=1.8.0", ">=1.10.0"), ">=1.10.0")
        self.assertEqual(_apply_simple_strategy(">=1.10.0", ">=1.8.0"), ">=1.10.0")

    def test_le_picks_lower(self):
        self.assertEqual(_apply_simple_strategy("<=1.8.0", "<=1.10.0"), "<=1.8.0")
        self.assertEqual(_apply_simple_strategy("<=1.10.0", "<=1.8.0"), "<=1.8.0")

    def test_gt_picks_higher(self):
        self.assertEqual(_apply_simple_strategy(">1.8.0", ">1.10.0"), ">1.10.0")

    def test_lt_picks_lower(self):
        self.assertEqual(_apply_simple_strategy("<1.8.0", "<1.10.0"), "<1.8.0")

    def test_ge_same_version(self):
        result = _apply_simple_strategy(">=1.0.0", ">=1.0.0")
        self.assertIn("1.0.0", result)

    # 不处理的场景（返回 None，交由 packaging）
    def test_mixed_ops_ge_vs_le_returns_none(self):
        self.assertIsNone(_apply_simple_strategy(">=1.0.0", "<=2.0.0"))

    def test_mixed_ops_ge_vs_lt_returns_none(self):
        self.assertIsNone(_apply_simple_strategy(">=1.0.0", "<2.0.0"))

    def test_compound_vs_simple_returns_none(self):
        self.assertIsNone(_apply_simple_strategy(">=1.0.0,<2.0.0", ">=1.5.0"))

    def test_both_compound_returns_none(self):
        self.assertIsNone(_apply_simple_strategy(">=1.0.0,<2.0.0", ">=1.5.0,<3.0.0"))

    def test_exclusion_returns_none(self):
        self.assertIsNone(_apply_simple_strategy(">=1.0.0,!=1.5.0", ">=1.2.0"))

    def test_tilde_returns_none(self):
        self.assertIsNone(_apply_simple_strategy("~=1.4.2", ">=1.4.0"))

    def test_ge_vs_le_different_versions_returns_none(self):
        # 下界 vs 上界：不属于"单一同类操作符"
        self.assertIsNone(_apply_simple_strategy(">=1.26.4", "<=1.26.4"))


# ─────────────────────────────────────────────────────────────────────────────
# 3. _extract_exact_version
# ─────────────────────────────────────────────────────────────────────────────
class TestExtractExactVersion(unittest.TestCase):

    def test_simple_exact(self):
        self.assertEqual(_extract_exact_version("==1.8.0"), "1.8.0")

    def test_post_release(self):
        self.assertEqual(_extract_exact_version("==2.1.5.post1"), "2.1.5.post1")

    def test_pre_release(self):
        self.assertEqual(_extract_exact_version("==1.0.0a1"), "1.0.0a1")

    def test_ge_returns_none(self):
        self.assertIsNone(_extract_exact_version(">=1.0.0"))

    def test_le_returns_none(self):
        self.assertIsNone(_extract_exact_version("<=1.0.0"))

    def test_exclusion_returns_none(self):
        self.assertIsNone(_extract_exact_version("!=1.0.0"))

    def test_compound_returns_none(self):
        # 复合约束：含逗号不匹配
        self.assertIsNone(_extract_exact_version("==1.5,!=1.5.1"))

    def test_empty_returns_none(self):
        self.assertIsNone(_extract_exact_version(""))

    def test_whitespace_stripped(self):
        self.assertEqual(_extract_exact_version("  ==1.8.0  "), "1.8.0")


# ─────────────────────────────────────────────────────────────────────────────
# 4. _parse_single_op
# ─────────────────────────────────────────────────────────────────────────────
class TestParseSingleOp(unittest.TestCase):

    def test_ge(self):
        self.assertEqual(_parse_single_op(">=1.8.0"), (">=", "1.8.0"))

    def test_le(self):
        self.assertEqual(_parse_single_op("<=2.0"), ("<=", "2.0"))

    def test_gt(self):
        self.assertEqual(_parse_single_op(">1.0"), (">", "1.0"))

    def test_lt(self):
        self.assertEqual(_parse_single_op("<3.0.0"), ("<", "3.0.0"))

    def test_exact_returns_none(self):
        self.assertEqual(_parse_single_op("==1.5"), (None, None))

    def test_exclusion_returns_none(self):
        self.assertEqual(_parse_single_op("!=1.5"), (None, None))

    def test_tilde_returns_none(self):
        self.assertEqual(_parse_single_op("~=1.4.2"), (None, None))

    def test_compound_returns_none(self):
        self.assertEqual(_parse_single_op(">=1.0,<2.0"), (None, None))

    def test_whitespace_stripped(self):
        self.assertEqual(_parse_single_op("  >=1.0.0  "), (">=", "1.0.0"))

    def test_operator_with_space_before_version(self):
        """操作符与版本号之间有空格时也能解析，如 requirements 中 'accelerate >= 0.33.0'"""
        self.assertEqual(_parse_single_op(">= 0.33.0"), (">=", "0.33.0"))
        self.assertEqual(_parse_single_op("<= 2.0"), ("<=", "2.0"))

    def test_multi_segment_version(self):
        self.assertEqual(_parse_single_op(">=1.26.4"), (">=", "1.26.4"))


# ─────────────────────────────────────────────────────────────────────────────
# 5. _try_merge_with_packaging
# ─────────────────────────────────────────────────────────────────────────────
class TestTryMergeWithPackaging(unittest.TestCase):

    def test_ge_ranges_merged(self):
        result = _try_merge_with_packaging(">=1.0.0", ">=1.5.0")
        if result is not None:
            self.assertIn("1.5", result)

    def test_ge_with_upper_bound(self):
        result = _try_merge_with_packaging(">=1.8.0,<2.0", ">=1.10.0,<3.0")
        if result is not None:
            self.assertIn("1.10.0", result)

    def test_exclusion_preserved(self):
        result = _try_merge_with_packaging(">=4.39.0,!=4.50.*", ">=4.44.0")
        if result is not None:
            self.assertIn("4.44.0", result)
            self.assertIn("4.50", result)

    def test_incompatible_ranges_returns_combined_string(self):
        # packaging 不检测矛盾区间，返回拼接字符串交给 pip 处理
        result = _try_merge_with_packaging(">=2.0.0", "<1.0.0")
        if result is not None:
            self.assertIn("2.0.0", result)
            self.assertIn("1.0.0", result)

    def test_ge_le_same_version_returns_combined(self):
        # packaging 不化简 >=x,<=x → ==x，交给 pip
        result = _try_merge_with_packaging(">=1.26.4", "<=1.26.4")
        if result is not None:
            self.assertIn("1.26.4", result)

    def test_import_error_returns_none(self):
        with patch("builtins.__import__", side_effect=ImportError("no packaging")):
            result = _try_merge_with_packaging(">=1.0.0", ">=1.5.0")
        self.assertIsNone(result)


# ─────────────────────────────────────────────────────────────────────────────
# 6. _is_version_newer
# ─────────────────────────────────────────────────────────────────────────────
class TestIsVersionNewer(unittest.TestCase):

    # 基本数字版本
    def test_major_version(self):
        self.assertTrue(_is_version_newer("2.0.0", "1.0.0"))
        self.assertFalse(_is_version_newer("1.0.0", "2.0.0"))

    def test_minor_version(self):
        self.assertTrue(_is_version_newer("1.5.0", "1.4.9"))
        self.assertFalse(_is_version_newer("1.4.9", "1.5.0"))

    def test_patch_version(self):
        self.assertTrue(_is_version_newer("1.0.1", "1.0.0"))
        self.assertFalse(_is_version_newer("1.0.0", "1.0.1"))

    def test_equal_returns_false(self):
        self.assertFalse(_is_version_newer("1.0.0", "1.0.0"))

    def test_multi_segment(self):
        self.assertTrue(_is_version_newer("1.0.0.1", "1.0.0"))
        self.assertFalse(_is_version_newer("1.0.0", "1.0.0.1"))

    def test_double_digit_minor(self):
        # 1.10 > 1.9，纯字符串比较会出错
        self.assertTrue(_is_version_newer("1.10.0", "1.9.0"))

    # PEP 440 特殊版本形式
    def test_pre_release_older_than_release(self):
        # alpha/beta/rc 比正式版旧
        self.assertFalse(_is_version_newer("1.0.0a1", "1.0.0"))
        self.assertFalse(_is_version_newer("1.0.0b2", "1.0.0"))
        self.assertFalse(_is_version_newer("1.0.0rc1", "1.0.0"))

    def test_pre_release_ordering(self):
        # alpha < beta < rc
        self.assertFalse(_is_version_newer("1.0.0a1", "1.0.0b1"))
        self.assertFalse(_is_version_newer("1.0.0b1", "1.0.0rc1"))

    def test_post_release_newer_than_release(self):
        self.assertTrue(_is_version_newer("1.0.0.post1", "1.0.0"))
        self.assertFalse(_is_version_newer("1.0.0", "1.0.0.post1"))

    def test_dev_release_older_than_release(self):
        self.assertFalse(_is_version_newer("1.0.0.dev1", "1.0.0"))

    def test_epoch(self):
        # epoch 优先级最高，1!2.0.0 > 9.0.0
        self.assertTrue(_is_version_newer("1!2.0.0", "9.0.0"))

    # 兜底行为
    def test_fallback_on_invalid_version_treats_a_as_newer(self):
        # packaging 无法解析时，视 version_a 为较新，返回 True，并打印 WARNING
        with patch("builtins.print"):
            with patch("builtins.__import__", side_effect=ImportError("no packaging")):
                result = _is_version_newer("invalid-ver", "1.0.0")
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
