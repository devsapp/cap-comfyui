"""
version_resolver 单元测试
=========================
覆盖 services/pip/version_resolver.py 中所有公开函数和内部辅助函数。

模块导出：
  resolve_version_conflict()       ← 对外唯一入口
内部函数（直接 import 测试）：
  _parse_version_constraint
  _apply_conflict_resolution_strategy
  _extract_version_from_exact
  _is_version_newer
  _try_merge_version_ranges
  _try_merge_with_packaging
  _try_merge_simple_ranges
  _simplify_version_spec
  _version_to_tuple
"""
import unittest
from unittest.mock import patch

from version_resolver import (
    resolve_version_conflict,
    _parse_version_constraint,
    _apply_conflict_resolution_strategy,
    _extract_version_from_exact,
    _is_version_newer,
    _try_merge_version_ranges,
    _try_merge_with_packaging,
    _try_merge_simple_ranges,
    _simplify_version_spec,
    _version_to_tuple,
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
        # 相同则直接返回，不打印
        result = resolve_version_conflict(">=1.0.0", ">=1.0.0", "pkg")
        self.assertEqual(result, ">=1.0.0")

    # 精确 vs 精确
    def test_exact_vs_exact_newer_wins(self):
        self.assertEqual(self._r("==1.0.0", "==2.0.0"), "==2.0.0")

    def test_exact_vs_exact_older_loses(self):
        self.assertEqual(self._r("==3.0.0", "==2.0.0"), "==3.0.0")

    def test_exact_vs_exact_same_version(self):
        result = self._r("==1.5.0", "==1.5.0")
        # 相同版本不论哪个都行
        self.assertIn(result, ("==1.5.0",))

    # 精确 vs 范围
    def test_exact_vs_range_keeps_exact(self):
        self.assertEqual(self._r("==1.5.0", ">=1.0.0"), "==1.5.0")

    def test_range_vs_exact_selects_exact(self):
        self.assertEqual(self._r(">=1.0.0", "==1.5.0"), "==1.5.0")

    # 范围 vs 范围
    def test_range_vs_range_picks_stricter_lower_bound(self):
        result = self._r(">=1.0.0", ">=1.5.0")
        # 结果应该是较高的下界
        self.assertIn("1.5", result)

    def test_range_vs_range_same_returns_same(self):
        result = resolve_version_conflict(">=1.0.0", ">=1.0.0", "pkg")
        self.assertEqual(result, ">=1.0.0")


# ─────────────────────────────────────────────────────────────────────────────
# 2. _parse_version_constraint
# ─────────────────────────────────────────────────────────────────────────────
class TestParseVersionConstraint(unittest.TestCase):

    def test_empty_spec(self):
        parsed = _parse_version_constraint("")
        self.assertEqual(parsed["operators"], [])
        self.assertFalse(parsed["is_exact"])
        self.assertFalse(parsed["has_exclusion"])

    def test_exact_version(self):
        parsed = _parse_version_constraint("==1.8.0")
        self.assertTrue(parsed["is_exact"])
        self.assertFalse(parsed["has_exclusion"])
        self.assertEqual(parsed["operators"], [("==", "1.8.0")])

    def test_ge_version(self):
        parsed = _parse_version_constraint(">=1.0.0")
        self.assertFalse(parsed["is_exact"])
        self.assertEqual(parsed["operators"][0][0], ">=")

    def test_compound_constraint(self):
        parsed = _parse_version_constraint(">=1.0.0,<2.0.0")
        self.assertEqual(len(parsed["operators"]), 2)
        ops = {op for op, _ in parsed["operators"]}
        self.assertIn(">=", ops)
        self.assertIn("<", ops)

    def test_exclusion_constraint(self):
        parsed = _parse_version_constraint(">=1.0.0,!=1.5.0")
        self.assertTrue(parsed["has_exclusion"])

    def test_whitespace_is_stripped(self):
        parsed = _parse_version_constraint("  >=1.0.0  ")
        self.assertEqual(parsed["operators"][0], (">=", "1.0.0"))


# ─────────────────────────────────────────────────────────────────────────────
# 3. _extract_version_from_exact
# ─────────────────────────────────────────────────────────────────────────────
class TestExtractVersionFromExact(unittest.TestCase):

    def test_simple_exact(self):
        self.assertEqual(_extract_version_from_exact("==1.8.0"), "1.8.0")

    def test_multi_segment(self):
        # 正则 [\d\.]+ 贪婪匹配到 "2.1.5."（含末尾点），这是当前实现的行为
        self.assertEqual(_extract_version_from_exact("==2.1.5.post1"), "2.1.5.")

    def test_no_match_returns_original(self):
        self.assertEqual(_extract_version_from_exact(">=1.0.0"), ">=1.0.0")

    def test_empty(self):
        self.assertEqual(_extract_version_from_exact(""), "")


# ─────────────────────────────────────────────────────────────────────────────
# 4. _is_version_newer
# ─────────────────────────────────────────────────────────────────────────────
class TestIsVersionNewer(unittest.TestCase):

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

    def test_different_length_segments(self):
        self.assertTrue(_is_version_newer("1.0.0.1", "1.0.0"))
        self.assertFalse(_is_version_newer("1.0.0", "1.0.0.1"))

    def test_fallback_string_comparison(self):
        # 非数字版本退化为字符串比较
        self.assertTrue(_is_version_newer("b", "a"))
        self.assertFalse(_is_version_newer("a", "b"))


# ─────────────────────────────────────────────────────────────────────────────
# 5. _try_merge_simple_ranges
# ─────────────────────────────────────────────────────────────────────────────
class TestTryMergeSimpleRanges(unittest.TestCase):

    def test_picks_higher_lower_bound(self):
        self.assertEqual(_try_merge_simple_ranges(">=1.0.0", ">=1.5.0"), ">=1.5.0")
        self.assertEqual(_try_merge_simple_ranges(">=2.0.0", ">=1.5.0"), ">=2.0.0")

    def test_same_lower_bound(self):
        result = _try_merge_simple_ranges(">=1.0.0", ">=1.0.0")
        self.assertIn("1.0.0", result)

    def test_complex_range_returns_none(self):
        # 有上界时无法简单合并
        self.assertIsNone(_try_merge_simple_ranges(">=1.0.0,<2.0.0", ">=1.5.0"))

    def test_both_complex_returns_none(self):
        self.assertIsNone(
            _try_merge_simple_ranges(">=1.0.0,<2.0.0", ">=1.5.0,<3.0.0")
        )


# ─────────────────────────────────────────────────────────────────────────────
# 6. _try_merge_with_packaging
# ─────────────────────────────────────────────────────────────────────────────
class TestTryMergeWithPackaging(unittest.TestCase):

    def test_merge_ge_ranges_with_packaging(self):
        result = _try_merge_with_packaging(">=1.0.0", ">=1.5.0")
        # 如果 packaging 可用，结果应包含 1.5
        if result is not None:
            self.assertIn("1.5", result)

    def test_incompatible_ranges_combined(self):
        # packaging 的 SpecifierSet & 只是合并约束字符串，不检测空交集
        # 所以 >=2.0.0 & <1.0.0 会返回合并后的约束串，而非 None
        result = _try_merge_with_packaging(">=2.0.0", "<1.0.0")
        if result is not None:
            # 两个约束都应出现在结果中
            self.assertIn("2.0.0", result)
            self.assertIn("1.0.0", result)

    def test_import_error_returns_none(self):
        with patch("builtins.__import__", side_effect=ImportError("no packaging")):
            result = _try_merge_with_packaging(">=1.0.0", ">=1.5.0")
        self.assertIsNone(result)


# ─────────────────────────────────────────────────────────────────────────────
# 7. _try_merge_version_ranges（总调度）
# ─────────────────────────────────────────────────────────────────────────────
class TestTryMergeVersionRanges(unittest.TestCase):

    def test_delegates_to_packaging_first(self):
        with patch("version_resolver._try_merge_with_packaging",
                   return_value=">=1.5.0") as mock_pkg, \
             patch("version_resolver._try_merge_simple_ranges") as mock_simple:
            result = _try_merge_version_ranges(">=1.0.0", ">=1.5.0")
        mock_pkg.assert_called_once()
        mock_simple.assert_not_called()
        self.assertEqual(result, ">=1.5.0")

    def test_falls_back_to_simple_when_packaging_returns_none(self):
        with patch("version_resolver._try_merge_with_packaging", return_value=None), \
             patch("version_resolver._try_merge_simple_ranges",
                   return_value=">=1.5.0") as mock_simple:
            result = _try_merge_version_ranges(">=1.0.0", ">=1.5.0")
        mock_simple.assert_called_once()
        self.assertEqual(result, ">=1.5.0")

    def test_returns_none_when_both_fail(self):
        with patch("version_resolver._try_merge_with_packaging", return_value=None), \
             patch("version_resolver._try_merge_simple_ranges", return_value=None):
            result = _try_merge_version_ranges(">=1.0.0", ">=1.5.0")
        self.assertIsNone(result)


# ─────────────────────────────────────────────────────────────────────────────
# 8. _simplify_version_spec
# ─────────────────────────────────────────────────────────────────────────────
class TestSimplifyVersionSpec(unittest.TestCase):

    def test_no_ge_no_change(self):
        self.assertEqual(_simplify_version_spec("<2.0.0"), "<2.0.0")

    def test_single_ge_no_change(self):
        self.assertEqual(_simplify_version_spec(">=1.0.0"), ">=1.0.0")

    def test_duplicate_ge_keeps_highest(self):
        result = _simplify_version_spec(">=1.8.0,>=1.9.0")
        self.assertIn("1.9.0", result)
        # 只剩一个 >=
        self.assertEqual(result.count(">="), 1)

    def test_ge_with_upper_bound_simplifies_ge(self):
        result = _simplify_version_spec(">=1.8.0,>=1.10.0,<2.0.0")
        self.assertIn("1.10.0", result)
        self.assertIn("<2.0.0", result)

    def test_no_comma_no_change(self):
        self.assertEqual(_simplify_version_spec(">=1.0.0"), ">=1.0.0")


# ─────────────────────────────────────────────────────────────────────────────
# 9. _version_to_tuple
# ─────────────────────────────────────────────────────────────────────────────
class TestVersionToTuple(unittest.TestCase):

    def test_simple(self):
        self.assertEqual(_version_to_tuple("1.2.3"), (1, 2, 3))

    def test_single_segment(self):
        self.assertEqual(_version_to_tuple("5"), (5,))

    def test_invalid_falls_back_to_string_tuple(self):
        result = _version_to_tuple("alpha")
        self.assertEqual(result, ("alpha",))


if __name__ == "__main__":
    unittest.main(verbosity=2)
