"""
_install_merged_dependencies — stderr 捕获 + 重试机制测试
==========================================================
验证"pip 失败 → 解析 stderr → 剔除问题包 → 有限次重试"的完整链路。

每个测试用 mock subprocess.run 精确控制 pip 的 stdout/stderr，
无需网络、无需真实 pip。
"""
import subprocess
import time
import unittest
from unittest.mock import patch

from services.pip.pip_installer import PIPInstaller
from models import DependencyInfo


# ─────────────────────────────────────────────────────────────────────────────
# 辅助
# ─────────────────────────────────────────────────────────────────────────────
def _dep(name, spec="", node="node-a"):
    return DependencyInfo(package_name=name, version_spec=spec,
                          original_line=f"{name}{spec}", source_nodes=[node])


def _pip_ok():
    return subprocess.CompletedProcess(args=[], returncode=0, stderr="")


def _pip_fail(pkg_spec):
    """模拟 pip 报 'Could not install requirement <pkg_spec>' 的失败。"""
    stderr = (
        f"ERROR: pip's dependency resolver...\n"
        f"Could not install requirement {pkg_spec} "
        f"from https://pypi.org/simple/ because of download error\n"
    )
    return subprocess.CompletedProcess(args=[], returncode=1, stderr=stderr)


def _pip_fail_opaque(msg="ERROR: subprocess-exited-with-error"):
    """模拟 pip 失败但 stderr 无法解析包名的情况。"""
    return subprocess.CompletedProcess(args=[], returncode=1, stderr=msg)


def _make_installer():
    with patch("services.pip.pip_installer.subprocess.check_output",
               return_value="Package Version\n"), \
         patch("services.pip.pip_installer.constants") as c:
        c.COMFYUI_DIR = "/tmp/fake"
        c.VENV_EXECUTABLE = "/fake/python"
        return PIPInstaller()


def _run(installer, deps, timeout=600):
    with patch("builtins.print"):
        return installer._install_merged_dependencies(
            deps, timeout=timeout, start_time=time.time()
        )


# ─────────────────────────────────────────────────────────────────────────────
# 测试用例
# ─────────────────────────────────────────────────────────────────────────────
class TestStderrRetry(unittest.TestCase):

    # ── 1. 核心场景：一次重试后成功 ──────────────────────────────────────────
    def test_retry_once_then_success(self):
        """
        merged_deps = {requests, numpy, bad-pkg==99.99.99}
        第1次 pip fail → 识别 bad-pkg → 剔除 → 第2次 pip success
        """
        installer = _make_installer()
        deps = {
            "requests": _dep("requests"),
            "numpy":    _dep("numpy", ">=1.20.0"),
            "bad-pkg":  _dep("bad-pkg", "==99.99.99"),
        }

        with patch("subprocess.run", side_effect=[
            _pip_fail("bad-pkg==99.99.99"),   # 第1次失败
            _pip_ok(),                         # 第2次成功
        ]) as mock_run:
            record = _run(installer, deps)

        self.assertTrue(record.success, "重试后应整体成功")
        self.assertEqual(record.error_msg, "")
        self.assertIn("bad-pkg", installer._problematic_deps)
        self.assertNotIn("bad-pkg", record.requirements_txt)
        self.assertEqual(mock_run.call_count, 2, "pip 应调用 2 次")

    # ── 2. stderr 无法解析包名 → 不重试，直接报错 ────────────────────────────
    def test_no_retry_when_stderr_unparseable(self):
        installer = _make_installer()
        deps = {"requests": _dep("requests")}

        with patch("subprocess.run", return_value=_pip_fail_opaque()) as mock_run:
            record = _run(installer, deps)

        self.assertFalse(record.success)
        self.assertIn("no specific failed package", record.error_msg)
        self.assertEqual(mock_run.call_count, 1, "无法解析 stderr 时不应重试")

    # ── 3. 耗尽最大重试次数 ────────────────────────────────────────────────────
    def test_max_retries_exhausted(self):
        from services.pip.pip_installer import _MAX_INSTALL_RETRIES

        installer = _make_installer()
        # 构造 MAX_RETRIES+2 个包，每次失败一个不同的
        n = _MAX_INSTALL_RETRIES + 2
        deps = {
            f"bad-{i}": _dep(f"bad-{i}", f"=={i}.0.0")
            for i in range(n)
        }
        side_effects = [
            _pip_fail(f"bad-{i}=={i}.0.0") for i in range(_MAX_INSTALL_RETRIES + 1)
        ]

        with patch("subprocess.run", side_effect=side_effects) as mock_run:
            record = _run(installer, deps)

        self.assertFalse(record.success)
        self.assertIn("retries", record.error_msg)
        self.assertEqual(mock_run.call_count, _MAX_INSTALL_RETRIES + 1)

    # ── 4. 同一个包反复失败 → 防死循环 ────────────────────────────────────────
    def test_no_progress_breaks_loop(self):
        """
        第1次剔除 bad-pkg 后，第2次 pip 的 stderr 仍然报 bad-pkg
        （bad-pkg 已不在 current_deps 中），newly_removed 为空 → 中止。
        """
        installer = _make_installer()
        deps = {
            "requests": _dep("requests"),
            "bad-pkg":  _dep("bad-pkg", "==99.99.99"),
        }

        with patch("subprocess.run", side_effect=[
            _pip_fail("bad-pkg==99.99.99"),  # 第1次：bad-pkg 失败 → 剔除
            _pip_fail("bad-pkg==99.99.99"),  # 第2次：同一包，已剔除，newly_removed=[]
        ]) as mock_run:
            record = _run(installer, deps)

        self.assertFalse(record.success)
        self.assertIn("no further progress", record.error_msg)
        self.assertEqual(mock_run.call_count, 2)

    # ── 5. 多个包同时失败 → 一轮内全部剔除 ────────────────────────────────────
    def test_multiple_failures_in_one_round(self):
        """
        pip 在同一次调用中报了 2 个失败包，两个都应被识别并剔除，然后重试成功。
        """
        installer = _make_installer()
        deps = {
            "requests": _dep("requests"),
            "bad-a":    _dep("bad-a", "==1.0.0"),
            "bad-b":    _dep("bad-b", "==2.0.0"),
        }
        stderr_two_failures = (
            "Could not install requirement bad-a==1.0.0 from ...\n"
            "Could not install requirement bad-b==2.0.0 from ...\n"
        )
        fail_result = subprocess.CompletedProcess(
            args=[], returncode=1, stderr=stderr_two_failures
        )

        with patch("subprocess.run", side_effect=[fail_result, _pip_ok()]) as mock_run:
            record = _run(installer, deps)

        self.assertTrue(record.success)
        self.assertIn("bad-a", installer._problematic_deps)
        self.assertIn("bad-b", installer._problematic_deps)
        self.assertNotIn("bad-a", record.requirements_txt)
        self.assertNotIn("bad-b", record.requirements_txt)
        self.assertEqual(mock_run.call_count, 2)

    # ── 6. pip 进程超时 ────────────────────────────────────────────────────────
    def test_subprocess_timeout_records_error(self):
        installer = _make_installer()
        deps = {"requests": _dep("requests")}

        with patch("subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="pip", timeout=5)):
            record = _run(installer, deps)

        self.assertFalse(record.success)
        self.assertIn("timed out", record.error_msg)

    # ── 7. 成功时 requirements_txt 字段被更新 ─────────────────────────────────
    def test_success_requirements_txt_updated(self):
        """成功时 record.requirements_txt 应为实际安装的内容（不含剔除的包）。"""
        installer = _make_installer()
        deps = {
            "numpy":   _dep("numpy", ">=1.20.0"),
            "bad-pkg": _dep("bad-pkg", "==0.0.1"),
        }

        with patch("subprocess.run", side_effect=[
            _pip_fail("bad-pkg==0.0.1"),
            _pip_ok(),
        ]):
            record = _run(installer, deps)

        self.assertTrue(record.success)
        self.assertIn("numpy", record.requirements_txt)
        self.assertNotIn("bad-pkg", record.requirements_txt)

    # ── 8. 空依赖字典 → 立即成功，不调用 pip ──────────────────────────────────
    def test_empty_deps_skips_pip(self):
        installer = _make_installer()

        with patch("subprocess.run") as mock_run:
            record = _run(installer, {})

        mock_run.assert_not_called()
        self.assertTrue(record.success)
        self.assertEqual(record.requirements_txt, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
