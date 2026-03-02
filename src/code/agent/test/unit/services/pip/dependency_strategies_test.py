"""
dependency_strategies 单元测试
================================
覆盖 services/pip/dependency_strategies.py 中所有函数。

模块导出：
  apply_custom_dependency_strategies()    ← 对外唯一入口
内部函数（直接 import 测试）：
  _handle_nunchaku_strategy
  _extract_nunchaku_version
"""
import unittest
from unittest.mock import patch

from dependency_strategies import (
    apply_custom_dependency_strategies,
    _handle_nunchaku_strategy,
    _extract_nunchaku_version,
)
from models import DependencyInfo


# ─────────────────────────────────────────────────────────────────────────────
# 辅助
# ─────────────────────────────────────────────────────────────────────────────
def _dep(name, spec="", node="node-a"):
    return DependencyInfo(package_name=name, version_spec=spec,
                          original_line=f"{name}{spec}", source_nodes=[node])


_NUNCHAKU_WHEEL = (
    "https://modelscope.cn/models/nunchaku-tech/nunchaku/resolve/master/"
    "nunchaku-1.0.0+torch2.8-cp310-cp310-linux_x86_64.whl"
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. apply_custom_dependency_strategies — 公开入口
# ─────────────────────────────────────────────────────────────────────────────
class TestApplyCustomDependencyStrategies(unittest.TestCase):

    def _apply(self, deps, nodes_to_install, nodes_map=None):
        with patch("builtins.print"):
            return apply_custom_dependency_strategies(deps, nodes_to_install, nodes_map)

    def test_no_nunchaku_node_deps_unchanged(self):
        deps = {"requests": _dep("requests", ">=2.25.0")}
        result = self._apply(deps, ["other-node"], {"other-node": {}})
        self.assertEqual(result, deps)
        self.assertNotIn(_NUNCHAKU_WHEEL, result)

    def test_nunchaku_v1_0_0_injects_wheel(self):
        deps = {"requests": _dep("requests")}
        nodes_map = {"ComfyUI-nunchaku": {"version": {"type": "tag", "value": "v1.0.0"}}}
        result = self._apply(deps, ["ComfyUI-nunchaku"], nodes_map)
        self.assertIn(_NUNCHAKU_WHEEL, result)

    def test_nunchaku_v1_0_1_injects_same_wheel(self):
        deps = {}
        nodes_map = {"ComfyUI-nunchaku": {"version": {"type": "tag", "value": "v1.0.1"}}}
        result = self._apply(deps, ["ComfyUI-nunchaku"], nodes_map)
        self.assertIn(_NUNCHAKU_WHEEL, result)

    def test_nunchaku_other_version_no_wheel(self):
        deps = {"requests": _dep("requests")}
        nodes_map = {"ComfyUI-nunchaku": {"version": {"type": "tag", "value": "v0.3.0"}}}
        result = self._apply(deps, ["ComfyUI-nunchaku"], nodes_map)
        self.assertNotIn(_NUNCHAKU_WHEEL, result)

    def test_original_deps_preserved_with_nunchaku(self):
        deps = {"requests": _dep("requests", ">=2.25.0")}
        nodes_map = {"ComfyUI-nunchaku": {"version": {"type": "tag", "value": "v1.0.0"}}}
        result = self._apply(deps, ["ComfyUI-nunchaku"], nodes_map)
        self.assertIn("requests", result)

    def test_empty_deps_with_nunchaku(self):
        nodes_map = {"ComfyUI-nunchaku": {"version": {"type": "tag", "value": "v1.0.0"}}}
        result = self._apply({}, ["ComfyUI-nunchaku"], nodes_map)
        self.assertIn(_NUNCHAKU_WHEEL, result)
        self.assertEqual(len(result), 1)


# ─────────────────────────────────────────────────────────────────────────────
# 2. _handle_nunchaku_strategy
# ─────────────────────────────────────────────────────────────────────────────
class TestHandleNunchakuStrategy(unittest.TestCase):

    def _handle(self, deps, nodes_to_install, nodes_map):
        with patch("builtins.print"):
            return _handle_nunchaku_strategy(deps, nodes_to_install, nodes_map)

    # ── 无 nunchaku 节点 ──────────────────────────────────────────────────────
    def test_no_nunchaku_in_nodes_returns_deps_unchanged(self):
        deps = {"requests": _dep("requests")}
        result = self._handle(deps, ["other-node"], {"other-node": {}})
        self.assertIs(result, deps)

    # ── nunchaku v1.0.0 ───────────────────────────────────────────────────────
    def test_v1_0_0_adds_wheel(self):
        deps = {}
        nodes_map = {"ComfyUI-nunchaku": {"version": {"type": "tag", "value": "v1.0.0"}}}
        result = self._handle(deps, ["ComfyUI-nunchaku"], nodes_map)
        self.assertIn(_NUNCHAKU_WHEEL, result)

    def test_v1_0_0_wheel_dep_structure(self):
        nodes_map = {"ComfyUI-nunchaku": {"version": {"type": "tag", "value": "v1.0.0"}}}
        result = self._handle({}, ["ComfyUI-nunchaku"], nodes_map)
        wheel_dep = result[_NUNCHAKU_WHEEL]
        self.assertEqual(wheel_dep.package_name, _NUNCHAKU_WHEEL)
        self.assertEqual(wheel_dep.version_spec, "")
        self.assertEqual(wheel_dep.source_nodes, ["ComfyUI-nunchaku"])

    # ── nunchaku v1.0.1 ───────────────────────────────────────────────────────
    def test_v1_0_1_adds_same_wheel_as_v1_0_0(self):
        nodes_map = {"ComfyUI-nunchaku": {"version": {"type": "tag", "value": "v1.0.1"}}}
        result = self._handle({}, ["ComfyUI-nunchaku"], nodes_map)
        self.assertIn(_NUNCHAKU_WHEEL, result)

    # ── 其他版本 ─────────────────────────────────────────────────────────────
    def test_v0_2_0_no_wheel(self):
        nodes_map = {"ComfyUI-nunchaku": {"version": {"type": "tag", "value": "v0.2.0"}}}
        result = self._handle({"requests": _dep("requests")}, ["ComfyUI-nunchaku"], nodes_map)
        self.assertNotIn(_NUNCHAKU_WHEEL, result)

    def test_unknown_version_no_wheel(self):
        # 缺少 version 字段 → version 解析为 "unknown" → 不注入 wheel
        nodes_map = {"ComfyUI-nunchaku": {"name": "ComfyUI-nunchaku"}}
        result = self._handle({}, ["ComfyUI-nunchaku"], nodes_map)
        self.assertNotIn(_NUNCHAKU_WHEEL, result)

    def test_none_nodes_map_version_unknown_no_wheel(self):
        result = self._handle({}, ["ComfyUI-nunchaku"], None)
        self.assertNotIn(_NUNCHAKU_WHEEL, result)


# ─────────────────────────────────────────────────────────────────────────────
# 3. _extract_nunchaku_version
# ─────────────────────────────────────────────────────────────────────────────
class TestExtractNunchakuVersion(unittest.TestCase):

    _NODE = "ComfyUI-nunchaku"

    def _extract(self, nodes_map):
        with patch("builtins.print"):
            return _extract_nunchaku_version(nodes_map, self._NODE)

    def test_valid_tag_version(self):
        nodes_map = {self._NODE: {"version": {"type": "tag", "value": "v1.0.0"}}}
        self.assertEqual(self._extract(nodes_map), "v1.0.0")

    def test_valid_branch_version(self):
        nodes_map = {self._NODE: {"version": {"type": "branch", "value": "main"}}}
        self.assertEqual(self._extract(nodes_map), "main")

    def test_node_missing_from_map_returns_unknown(self):
        self.assertEqual(self._extract({"other_node": {}}), "unknown")

    def test_none_nodes_map_returns_unknown(self):
        self.assertEqual(self._extract(None), "unknown")

    def test_empty_nodes_map_returns_unknown(self):
        self.assertEqual(self._extract({}), "unknown")

    def test_missing_version_key_returns_unknown(self):
        nodes_map = {self._NODE: {"name": "ComfyUI-nunchaku"}}
        # version 字段不存在，get 返回 {}，.get('value') 返回 'unknown'
        self.assertEqual(self._extract(nodes_map), "unknown")

    def test_version_not_dict_returns_unknown(self):
        nodes_map = {self._NODE: {"version": "v1.0.0"}}
        self.assertEqual(self._extract(nodes_map), "unknown")

    def test_version_missing_value_key_returns_unknown(self):
        nodes_map = {self._NODE: {"version": {"type": "tag"}}}
        # value 不存在，get 返回 'unknown'
        self.assertEqual(self._extract(nodes_map), "unknown")

    def test_version_value_is_none_returns_none(self):
        # value 存在但为 None（罕见，但应能处理）
        nodes_map = {self._NODE: {"version": {"type": "tag", "value": None}}}
        result = self._extract(nodes_map)
        self.assertIsNone(result)

    def test_full_config_structure(self):
        nodes_map = {
            self._NODE: {
                "name": "ComfyUI-nunchaku",
                "source": {"type": "github",
                           "cloneUrl": "https://github.com/nunchaku-tech/ComfyUI-nunchaku.git"},
                "version": {"type": "tag", "value": "v1.0.1"},
            }
        }
        self.assertEqual(self._extract(nodes_map), "v1.0.1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
