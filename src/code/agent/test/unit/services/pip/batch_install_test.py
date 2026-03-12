"""
两轮批次安装单元测试
====================
覆盖 _install_in_batches、_install_individually 和
_install_merged_dependencies 的完整链路。

两轮均通过 returncode 判断成功与否，无需解析 stderr，
通过 mock subprocess.run 精确控制每次调用的结果。
"""
import subprocess
import time
import unittest
from unittest.mock import patch

from services.pip.pip_installer import PIPInstaller
from models import DependencyInfo

# 测试中使用的固定批次大小，与 _make_installer 中 mock 的 INSTALL_BATCH_SIZE 一致
TEST_BATCH_SIZE = 10


# ─────────────────────────────────────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────────────────────────────────────

def _dep(name, spec="", node="node-a"):
    return DependencyInfo(package_name=name, version_spec=spec,
                          original_line=f"{name}{spec}", source_nodes=[node])


def _ok():
    return subprocess.CompletedProcess(args=[], returncode=0)


def _fail():
    return subprocess.CompletedProcess(args=[], returncode=1)


def _make_installer():
    with patch("services.pip.pip_installer.subprocess.check_output",
               return_value="Package Version\n"), \
         patch("services.pip.pip_installer.constants") as c:
        c.COMFYUI_DIR = "/tmp/fake"
        c.VENV_EXECUTABLE = "/fake/python"
        return PIPInstaller()


# ─────────────────────────────────────────────────────────────────────────────
# 1. _install_in_batches
# ─────────────────────────────────────────────────────────────────────────────
class TestInstallInBatches(unittest.TestCase):
    """运行期间固定 INSTALL_BATCH_SIZE=10，否则会使用 constants 默认值 20 导致断言失败"""

    def setUp(self):
        self._batch_patcher = patch(
            "services.pip.pip_installer.constants.INSTALL_BATCH_SIZE", TEST_BATCH_SIZE
        )
        self._batch_patcher.start()

    def tearDown(self):
        self._batch_patcher.stop()

    def _run(self, installer, deps, timeout=600):
        with patch("builtins.print"):
            return installer._install_in_batches(
                deps, timeout=timeout, start_time=time.time()
            )

    # ── 基础场景 ──────────────────────────────────────────────────────────────

    def test_empty_deps_returns_empty_no_pip(self):
        installer = _make_installer()
        with patch("subprocess.run") as mock_run:
            result = self._run(installer, [])
        mock_run.assert_not_called()
        self.assertEqual(result, [])

    def test_all_batches_succeed_returns_empty(self):
        installer = _make_installer()
        deps = [_dep(f"pkg-{i}") for i in range(5)]
        with patch("subprocess.run", return_value=_ok()):
            result = self._run(installer, deps)
        self.assertEqual(result, [])

    def test_failed_batch_all_deps_returned(self):
        installer = _make_installer()
        deps = [_dep("pkg-a"), _dep("pkg-b")]
        with patch("subprocess.run", return_value=_fail()):
            result = self._run(installer, deps)
        self.assertEqual({d.package_name for d in result}, {"pkg-a", "pkg-b"})

    def test_only_failed_batch_deps_returned(self):
        """两批：第一批成功，第二批失败；返回值只含第二批"""
        installer = _make_installer()
        batch1 = [_dep(f"good-{i}") for i in range(TEST_BATCH_SIZE)]
        batch2 = [_dep("bad")]
        with patch("subprocess.run", side_effect=[_ok(), _fail()]):
            result = self._run(installer, batch1 + batch2)
        self.assertEqual({d.package_name for d in result}, {"bad"})

    # ── 超时行为 ──────────────────────────────────────────────────────────────

    def test_subprocess_timeout_batch_returned(self):
        """批次 subprocess 超时 → 整批进入 failed_deps"""
        installer = _make_installer()
        deps = [_dep("slow-a"), _dep("slow-b")]
        with patch("subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="pip", timeout=1)):
            result = self._run(installer, deps)
        self.assertEqual({d.package_name for d in result}, {"slow-a", "slow-b"})

    def test_global_timeout_all_remaining_deferred(self):
        """全局超时时，当前及后续批次全部移入 failed_deps，不调用 pip"""
        installer = _make_installer()
        deps = [_dep(f"pkg-{i}") for i in range(TEST_BATCH_SIZE + 3)]
        with patch("subprocess.run") as mock_run, patch("builtins.print"):
            result = installer._install_in_batches(
                deps, timeout=1, start_time=time.time() - 9999
            )
        mock_run.assert_not_called()
        self.assertEqual(len(result), len(deps))

    def test_global_timeout_mid_run_defers_remaining(self):
        """第一批成功后全局超时，第二批未执行也进入 failed_deps"""
        installer = _make_installer()
        batch1 = [_dep(f"good-{i}") for i in range(TEST_BATCH_SIZE)]
        batch2 = [_dep("not-tried")]
        call_count = 0
        original_time = time.time

        def fake_time():
            nonlocal call_count
            call_count += 1
            # 第 1 次（batch1 超时检查）返回正常时间让第一批执行；之后超出 timeout 让 batch2 被推迟
            return 0.0 if call_count <= 1 else 9999.0

        with patch("subprocess.run", return_value=_ok()), \
             patch("builtins.print"), \
             patch("services.pip.pip_installer.time.time", side_effect=fake_time):
            result = installer._install_in_batches(
                batch1 + batch2, timeout=1, start_time=0.0
            )
        self.assertIn("not-tried", {d.package_name for d in result})

    # ── 批次大小 & pip 命令 ───────────────────────────────────────────────────

    def test_exact_batch_size_is_one_call(self):
        installer = _make_installer()
        deps = [_dep(f"pkg-{i}") for i in range(TEST_BATCH_SIZE)]
        with patch("subprocess.run", return_value=_ok()) as mock_run:
            self._run(installer, deps)
        self.assertEqual(mock_run.call_count, 1)

    def test_batch_size_plus_one_is_two_calls(self):
        installer = _make_installer()
        deps = [_dep(f"pkg-{i}") for i in range(TEST_BATCH_SIZE + 1)]
        with patch("subprocess.run", return_value=_ok()) as mock_run:
            self._run(installer, deps)
        self.assertEqual(mock_run.call_count, 2)

    def test_pip_cmd_contains_batch_specs(self):
        installer = _make_installer()
        deps = [_dep("requests", ">=2.0"), _dep("numpy", "==1.21.0")]
        with patch("subprocess.run", return_value=_ok()) as mock_run:
            self._run(installer, deps)
        cmd = mock_run.call_args[0][0]
        self.assertIn("requests>=2.0", cmd)
        self.assertIn("numpy==1.21.0", cmd)

    def test_pkg_without_version_spec_in_cmd(self):
        installer = _make_installer()
        with patch("subprocess.run", return_value=_ok()) as mock_run:
            self._run(installer, [_dep("requests")])
        cmd = mock_run.call_args[0][0]
        self.assertIn("requests", cmd)
        # 不应出现 "requests==" 或 "requests>=" 这类版本后缀
        self.assertNotIn("requests=", " ".join(cmd))
        self.assertNotIn("requests>", " ".join(cmd))


# ─────────────────────────────────────────────────────────────────────────────
# 2. _install_individually
# ─────────────────────────────────────────────────────────────────────────────
class TestInstallIndividually(unittest.TestCase):

    def _run(self, installer, deps, timeout=600):
        with patch("builtins.print"):
            installer._install_individually(
                deps, timeout=timeout, start_time=time.time()
            )

    # ── 基础场景 ──────────────────────────────────────────────────────────────

    def test_empty_deps_no_pip_no_problematic(self):
        installer = _make_installer()
        with patch("subprocess.run") as mock_run:
            self._run(installer, [])
        mock_run.assert_not_called()
        self.assertEqual(installer._problematic_deps, {})

    def test_success_not_in_problematic(self):
        installer = _make_installer()
        with patch("subprocess.run", return_value=_ok()):
            self._run(installer, [_dep("requests")])
        self.assertNotIn("requests", installer._problematic_deps)

    def test_failure_goes_to_problematic(self):
        installer = _make_installer()
        with patch("subprocess.run", return_value=_fail()):
            self._run(installer, [_dep("bad-pkg", "==0.1")])
        self.assertIn("bad-pkg", installer._problematic_deps)

    def test_partial_failure(self):
        """good 成功，bad 失败"""
        installer = _make_installer()
        with patch("subprocess.run", side_effect=[_ok(), _fail()]):
            self._run(installer, [_dep("good"), _dep("bad")])
        self.assertNotIn("good", installer._problematic_deps)
        self.assertIn("bad", installer._problematic_deps)

    def test_each_dep_called_individually(self):
        """每个包独立调用一次 pip"""
        installer = _make_installer()
        deps = [_dep("a", ">=1.0"), _dep("b", "==2.0")]
        with patch("subprocess.run", return_value=_ok()) as mock_run:
            self._run(installer, deps)
        self.assertEqual(mock_run.call_count, 2)
        all_cmds = [" ".join(c[0][0]) for c in mock_run.call_args_list]
        self.assertTrue(any("a>=1.0" in cmd for cmd in all_cmds))
        self.assertTrue(any("b==2.0" in cmd for cmd in all_cmds))

    # ── 超时行为 ──────────────────────────────────────────────────────────────

    def test_subprocess_timeout_goes_to_problematic(self):
        installer = _make_installer()
        with patch("subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="pip", timeout=1)):
            self._run(installer, [_dep("slow-pkg")])
        self.assertIn("slow-pkg", installer._problematic_deps)

    def test_global_timeout_remaining_all_become_problematic(self):
        """全局超时时，未执行的包全部标记为 problematic，不调用 pip"""
        installer = _make_installer()
        deps = [_dep("pkg-a"), _dep("pkg-b"), _dep("pkg-c")]
        with patch("subprocess.run") as mock_run, patch("builtins.print"):
            installer._install_individually(
                deps, timeout=1, start_time=time.time() - 9999
            )
        mock_run.assert_not_called()
        for name in ["pkg-a", "pkg-b", "pkg-c"]:
            self.assertIn(name, installer._problematic_deps)

    # ── problematic_deps 内容 ─────────────────────────────────────────────────

    def test_problematic_dep_preserves_package_name(self):
        installer = _make_installer()
        with patch("subprocess.run", return_value=_fail()):
            self._run(installer, [_dep("my-pkg", ">=1.0")])
        self.assertIn("my-pkg", installer._problematic_deps)
        dep = installer._problematic_deps["my-pkg"]
        self.assertEqual(dep.package_name, "my-pkg")
        self.assertEqual(dep.version_spec, ">=1.0")

    def test_problematic_dep_preserves_source_nodes(self):
        installer = _make_installer()
        d = DependencyInfo(package_name="pkg", version_spec="", original_line="pkg",
                           source_nodes=["nodeA", "nodeB"])
        with patch("subprocess.run", return_value=_fail()):
            self._run(installer, [d])
        self.assertEqual(installer._problematic_deps["pkg"].source_nodes, ["nodeA", "nodeB"])


# ─────────────────────────────────────────────────────────────────────────────
# 3. _install_merged_dependencies — 完整两轮链路
# ─────────────────────────────────────────────────────────────────────────────
class TestInstallMergedDependenciesRounds(unittest.TestCase):
    """运行期间固定 INSTALL_BATCH_SIZE=10，保证两批边界与用例假设一致"""

    def setUp(self):
        self._batch_patcher = patch(
            "services.pip.pip_installer.constants.INSTALL_BATCH_SIZE", TEST_BATCH_SIZE
        )
        self._batch_patcher.start()
        self.installer = _make_installer()

    def tearDown(self):
        self._batch_patcher.stop()

    def _run(self, deps, timeout=600):
        with patch("builtins.print"):
            return self.installer._install_merged_dependencies(
                deps, timeout=timeout, start_time=time.time()
            )

    # ── 基础场景 ──────────────────────────────────────────────────────────────

    def test_empty_deps_success_no_pip(self):
        with patch("subprocess.run") as mock_run:
            record = self._run({})
        mock_run.assert_not_called()
        self.assertTrue(record.success)
        self.assertEqual(record.problematic_deps, [])

    def test_all_batches_succeed_no_round2(self):
        """第一轮全部成功 → 不进入第二轮，无 problematic_deps"""
        deps = {"requests": _dep("requests"), "numpy": _dep("numpy", ">=1.20")}
        with patch("subprocess.run", return_value=_ok()) as mock_run:
            record = self._run(deps)
        self.assertTrue(record.success)
        self.assertEqual(record.problematic_deps, [])
        # 2 个包在同一批 → pip 只调用 1 次
        self.assertEqual(mock_run.call_count, 1)

    def test_batch_failure_triggers_round2(self):
        """第一轮失败 → 第二轮成功 → 无 problematic_deps"""
        deps = {"requests": _dep("requests")}
        with patch("subprocess.run", side_effect=[_fail(), _ok()]) as mock_run:
            record = self._run(deps)
        self.assertTrue(record.success)
        self.assertEqual(record.problematic_deps, [])
        # Round1(1次) + Round2(1次)
        self.assertEqual(mock_run.call_count, 2)

    def test_round2_failure_goes_to_problematic(self):
        """第一轮失败，第二轮也失败 → 加入 problematic_deps，success 仍为 True"""
        deps = {"bad-pkg": _dep("bad-pkg", "==0.0.1")}
        with patch("subprocess.run", side_effect=[_fail(), _fail()]):
            record = self._run(deps)
        self.assertTrue(record.success)
        self.assertEqual(len(record.problematic_deps), 1)
        self.assertEqual(record.problematic_deps[0].package_name, "bad-pkg")

    def test_partial_failure_only_bad_in_problematic(self):
        """好包批次成功，坏包批次失败后 Round 2 也失败。
        包名用 aaa-* 确保字典序排在 zzz-bad 之前，
        使 good 包在 batch1、zzz-bad 在 batch2。"""
        good_deps = {f"aaa-{i}": _dep(f"aaa-{i}") for i in range(TEST_BATCH_SIZE)}
        bad_deps = {"zzz-bad": _dep("zzz-bad", "==0.0.1")}
        deps = {**good_deps, **bad_deps}
        with patch("subprocess.run", side_effect=[_ok(), _fail(), _fail()]):
            record = self._run(deps)
        self.assertTrue(record.success)
        prob_names = {d.package_name for d in record.problematic_deps}
        self.assertIn("zzz-bad", prob_names)
        for i in range(TEST_BATCH_SIZE):
            self.assertNotIn(f"aaa-{i}", prob_names)

    def test_round2_rescues_some_packages(self):
        """第一轮批次失败的包中，有的在 Round 2 成功，有的失败。
        aaa-ok 字典序在 zzz-bad 之前，Round 2 按序执行：aaa-ok 先成功，zzz-bad 后失败。"""
        deps = {"aaa-ok": _dep("aaa-ok"), "zzz-bad": _dep("zzz-bad")}
        with patch("subprocess.run", side_effect=[
            _fail(),   # Round 1 批次失败（两个包都在这批）
            _ok(),     # Round 2: aaa-ok 成功（字典序第一）
            _fail(),   # Round 2: zzz-bad 失败（字典序第二）
        ]):
            record = self._run(deps)
        self.assertTrue(record.success)
        prob_names = {d.package_name for d in record.problematic_deps}
        self.assertIn("zzz-bad", prob_names)
        self.assertNotIn("aaa-ok", prob_names)

    # ── 超时场景 ──────────────────────────────────────────────────────────────

    def test_global_timeout_all_deps_become_problematic(self):
        """全局超时：不调用 pip，所有依赖进 problematic_deps，success=True"""
        deps = {"requests": _dep("requests"), "numpy": _dep("numpy")}
        with patch("subprocess.run") as mock_run, patch("builtins.print"):
            record = self.installer._install_merged_dependencies(
                deps, timeout=1, start_time=time.time() - 9999
            )
        mock_run.assert_not_called()
        self.assertTrue(record.success)
        self.assertEqual(len(record.problematic_deps), 2)

    def test_batch_subprocess_timeout_dep_in_problematic(self):
        """批次 subprocess 超时：两轮均超时，依赖进 problematic_deps"""
        deps = {"slow": _dep("slow")}
        with patch("subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="pip", timeout=1)):
            record = self._run(deps)
        self.assertTrue(record.success)
        self.assertEqual(len(record.problematic_deps), 1)
        self.assertEqual(record.problematic_deps[0].package_name, "slow")

    # ── record 字段 ───────────────────────────────────────────────────────────

    def test_record_has_duration(self):
        with patch("subprocess.run", return_value=_ok()):
            record = self._run({"requests": _dep("requests")})
        self.assertGreaterEqual(record.duration, 0)

    def test_record_requirements_txt_contains_dep(self):
        with patch("subprocess.run", return_value=_ok()):
            record = self._run({"requests": _dep("requests", ">=2.0")})
        self.assertIn("requests>=2.0", record.requirements_txt)

    def test_record_problematic_deps_includes_prefiltered(self):
        """过滤阶段（黑名单）产生的 problematic_deps 也应出现在 record 中"""
        with patch("services.pip.pip_installer.subprocess.check_output",
                   return_value="Package Version\n"), \
             patch("services.pip.pip_installer.constants") as c:
            c.COMFYUI_DIR = "/tmp/fake"
            c.VENV_EXECUTABLE = "/fake/python"
            installer = PIPInstaller(blacklist=["torch"])

        # 手动向 _problematic_deps 注入黑名单包（模拟 _filter_merged_dependencies 行为）
        from models import DependencyInfo
        installer._problematic_deps["torch"] = DependencyInfo(
            package_name="torch", version_spec=">=1.8",
            original_line="torch>=1.8", source_nodes=["n"]
        )

        with patch("subprocess.run", return_value=_ok()), patch("builtins.print"):
            record = installer._install_merged_dependencies(
                {"requests": _dep("requests")}, timeout=600, start_time=time.time()
            )
        prob_names = {d.package_name for d in record.problematic_deps}
        self.assertIn("torch", prob_names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
