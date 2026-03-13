"""GitCloner 单元测试
==================
系统覆盖 services/git/git_cloner.py 的所有核心路径：
  - _parse_nodes_map
  - _get_existing_lower
  - _rename_existing_dir
  - _run_clone
  - _clone_single_node
  - _process_and_clone_nodes（超时处理）
  - clone_all（整合 + summary 计数）
"""
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from services.git.git_cloner import (
    CLONE_TIMEOUT,
    CONFLICT_OVERRIDE,
    CONFLICT_SKIP,
    GitCloner,
    _parse_nodes_map,
)
from services.git.models import (
    CloneDetail,
    NodeMapValue,
    NodeSource,
    NodeVersion,
    STATUS_CLONED,
    STATUS_FAILED,
    STATUS_OVERRIDDEN,
    STATUS_SKIPPED,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_info(
    clone_url: str = "https://github.com/test/repo.git",
    version_type: str = None,
    version_value: str = None,
) -> NodeMapValue:
    version = NodeVersion(type=version_type, value=version_value) if version_type else None
    return NodeMapValue(
        name="TestNode",
        source=NodeSource(type="github", cloneUrl=clone_url),
        version=version,
    )


def _make_entry(name: str, is_dir: bool = True, parent: str = "/fake/nodes") -> MagicMock:
    entry = MagicMock()
    entry.name = name
    entry.path = f"{parent}/{name}"
    entry.is_dir.return_value = is_dir
    return entry


# ── _parse_nodes_map ──────────────────────────────────────────────────────────

class TestParseNodesMap(unittest.TestCase):
    """_parse_nodes_map 的完整覆盖，含边界与校验失败分支。"""

    def test_none_returns_empty(self):
        self.assertEqual(_parse_nodes_map(None), {})

    def test_empty_dict_returns_empty(self):
        self.assertEqual(_parse_nodes_map({}), {})

    def test_valid_single_entry(self):
        nodes_map = {
            "ComfyUI-nunchaku": {
                "name": "ComfyUI-nunchaku",
                "source": {
                    "type": "github",
                    "cloneUrl": "https://github.com/nunchaku-tech/ComfyUI-nunchaku.git",
                    "webUrl": "https://github.com/nunchaku-tech/ComfyUI-nunchaku",
                },
                "version": {"type": "tag", "value": "v0.2.0"},
            }
        }
        parsed = _parse_nodes_map(nodes_map)
        self.assertEqual(len(parsed), 1)
        node = parsed["ComfyUI-nunchaku"]
        self.assertIsInstance(node, NodeMapValue)
        self.assertEqual(node.name, "ComfyUI-nunchaku")
        self.assertEqual(node.source.cloneUrl, "https://github.com/nunchaku-tech/ComfyUI-nunchaku.git")
        self.assertEqual(node.source.type, "github")
        self.assertEqual(node.version.type, "tag")
        self.assertEqual(node.version.value, "v0.2.0")

    def test_valid_multiple_entries(self):
        nodes_map = {
            "NodeA": {"name": "NodeA", "source": {"type": "github", "cloneUrl": "https://github.com/a/A.git"}},
            "NodeB": {"name": "NodeB", "source": {"type": "github", "cloneUrl": "https://github.com/b/B.git"}},
        }
        parsed = _parse_nodes_map(nodes_map)
        self.assertEqual(len(parsed), 2)
        self.assertIn("NodeA", parsed)
        self.assertIn("NodeB", parsed)

    def test_no_version_field(self):
        nodes_map = {
            "NodeX": {"name": "NodeX", "source": {"type": "github", "cloneUrl": "https://github.com/x/X.git"}},
        }
        parsed = _parse_nodes_map(nodes_map)
        self.assertIsNone(parsed["NodeX"].version)

    def test_missing_clone_url_still_included(self):
        """cloneUrl 为可选字段，缺失时条目仍保留，由下游决定如何处理"""
        nodes_map = {
            "NodeX": {"name": "NodeX", "source": {"type": "github"}},
        }
        parsed = _parse_nodes_map(nodes_map)
        self.assertEqual(len(parsed), 1)
        self.assertIsNone(parsed["NodeX"].source.cloneUrl)

    def test_non_dict_value_skipped(self):
        nodes_map = {"BadNode": "not-a-dict"}
        self.assertEqual(_parse_nodes_map(nodes_map), {})

    def test_list_value_skipped(self):
        nodes_map = {"BadNode": [1, 2, 3]}
        self.assertEqual(_parse_nodes_map(nodes_map), {})

    def test_validation_error_missing_source_type_skipped(self):
        """source.type 为必填字段，缺失时 ValidationError 触发，条目被跳过"""
        nodes_map = {
            "BadNode": {"name": "BadNode", "source": {"cloneUrl": "https://github.com/bad/bad.git"}},
        }
        self.assertEqual(_parse_nodes_map(nodes_map), {})

    def test_empty_name_skipped(self):
        """name 为空字符串时 field_validator 报错，条目被跳过"""
        nodes_map = {
            "EmptyName": {"name": "", "source": {"type": "github", "cloneUrl": "https://github.com/x/x.git"}},
        }
        self.assertEqual(_parse_nodes_map(nodes_map), {})

    def test_whitespace_name_skipped(self):
        nodes_map = {
            "SpaceName": {"name": "   ", "source": {"type": "github"}},
        }
        self.assertEqual(_parse_nodes_map(nodes_map), {})

    def test_mixed_valid_and_invalid(self):
        nodes_map = {
            "Good": {"name": "Good", "source": {"type": "github", "cloneUrl": "https://github.com/g/g.git"}},
            "Bad": "not-a-dict",
        }
        parsed = _parse_nodes_map(nodes_map)
        self.assertEqual(len(parsed), 1)
        self.assertIn("Good", parsed)

    def test_commitid_version(self):
        nodes_map = {
            "NodeC": {
                "name": "NodeC",
                "source": {"type": "github", "cloneUrl": "https://github.com/c/C.git"},
                "version": {"type": "commit", "value": "abc1234def5678"},
            }
        }
        parsed = _parse_nodes_map(nodes_map)
        self.assertEqual(parsed["NodeC"].version.type, "commit")
        self.assertEqual(parsed["NodeC"].version.value, "abc1234def5678")


# ── _get_existing_lower ───────────────────────────────────────────────────────

class TestGetExistingLower(unittest.TestCase):

    def setUp(self):
        self.cloner = GitCloner()

    @patch("services.git.git_cloner.os.scandir")
    def test_returns_lowercase_mapping(self, mock_scandir):
        mock_scandir.return_value = [
            _make_entry("NodeA"),
            _make_entry("ComfyUI-Foo"),
        ]
        result = self.cloner._get_existing_lower(["/fake/nodes"])
        self.assertEqual(result, {
            "nodea": "/fake/nodes/NodeA",
            "comfyui-foo": "/fake/nodes/ComfyUI-Foo",
        })

    @patch("services.git.git_cloner.os.scandir")
    def test_skips_disabled_dirs(self, mock_scandir):
        mock_scandir.return_value = [
            _make_entry("NodeA"),
            _make_entry("NodeB.disabled"),
        ]
        result = self.cloner._get_existing_lower(["/fake/nodes"])
        self.assertIn("nodea", result)
        self.assertNotIn("nodeb.disabled", result)

    @patch("services.git.git_cloner.os.scandir")
    def test_skips_pycache(self, mock_scandir):
        mock_scandir.return_value = [
            _make_entry("NodeA"),
            _make_entry("__pycache__"),
        ]
        result = self.cloner._get_existing_lower(["/fake/nodes"])
        self.assertIn("nodea", result)
        self.assertNotIn("__pycache__", result)

    @patch("services.git.git_cloner.os.scandir")
    def test_skips_files(self, mock_scandir):
        mock_scandir.return_value = [
            _make_entry("NodeA", is_dir=True),
            _make_entry("somefile.txt", is_dir=False),
        ]
        result = self.cloner._get_existing_lower(["/fake/nodes"])
        self.assertEqual(result, {"nodea": "/fake/nodes/NodeA"})

    @patch("services.git.git_cloner.os.scandir", side_effect=FileNotFoundError)
    def test_dir_not_found_returns_empty(self, _):
        result = self.cloner._get_existing_lower(["/non/existent"])
        self.assertEqual(result, {})

    @patch("services.git.git_cloner.os.scandir")
    def test_empty_dir_returns_empty(self, mock_scandir):
        mock_scandir.return_value = []
        result = self.cloner._get_existing_lower(["/fake/nodes"])
        self.assertEqual(result, {})

    @patch("services.git.git_cloner.os.scandir")
    def test_preserves_real_case_in_value(self, mock_scandir):
        mock_scandir.return_value = [_make_entry("ComfyUI-Manager")]
        result = self.cloner._get_existing_lower(["/fake/nodes"])
        self.assertEqual(result["comfyui-manager"], "/fake/nodes/ComfyUI-Manager")

    @patch("services.git.git_cloner.os.scandir")
    def test_multi_dirs_first_wins_on_conflict(self, mock_scandir):
        """同名插件存在于多个目录时，以列表中先出现的目录为准"""
        def scandir_side_effect(path):
            if path == "/dir1":
                return [_make_entry("NodeA", parent="/dir1")]
            if path == "/dir2":
                return [_make_entry("NodeA", parent="/dir2"), _make_entry("NodeB", parent="/dir2")]
            return []
        mock_scandir.side_effect = scandir_side_effect
        result = self.cloner._get_existing_lower(["/dir1", "/dir2"])
        self.assertEqual(result["nodea"], "/dir1/NodeA")
        self.assertEqual(result["nodeb"], "/dir2/NodeB")

    @patch("services.git.git_cloner.os.scandir")
    def test_multi_dirs_skips_missing_dir(self, mock_scandir):
        """不存在的目录跳过，不影响其他目录的扫描"""
        def scandir_side_effect(path):
            if path == "/missing":
                raise FileNotFoundError
            return [_make_entry("NodeC", parent="/existing")]
        mock_scandir.side_effect = scandir_side_effect
        result = self.cloner._get_existing_lower(["/missing", "/existing"])
        self.assertEqual(result, {"nodec": "/existing/NodeC"})


# ── _rename_existing_dir ──────────────────────────────────────────────────────

class TestRenameExistingDir(unittest.TestCase):

    def setUp(self):
        self.cloner = GitCloner()

    @patch("services.git.git_cloner.os.rename")
    @patch("services.git.git_cloner.os.path.exists", return_value=False)
    @patch("services.git.git_cloner.time.time", return_value=1700000000.0)
    @patch("services.git.git_cloner.constants")
    def test_renames_to_bak_with_timestamp(self, mock_constants, _time, _exists, mock_rename):
        mock_constants.COMFYUI_DIR = "/comfyui"
        result = self.cloner._rename_existing_dir("/comfyui/custom_nodes/NodeA", "NodeA")
        self.assertIn("NodeA.bak.1700000000", result)
        mock_rename.assert_called_once()

    @patch("services.git.git_cloner.os.rename")
    @patch("services.git.git_cloner.os.path.exists")
    @patch("services.git.git_cloner.time.time", return_value=1700000000.0)
    @patch("services.git.git_cloner.constants")
    def test_collision_appends_counter(self, mock_constants, _time, mock_exists, mock_rename):
        mock_constants.COMFYUI_DIR = "/comfyui"
        # .bak.ts → exists, .bak.ts.1 → exists, .bak.ts.2 → free
        mock_exists.side_effect = [True, True, False]
        result = self.cloner._rename_existing_dir("/comfyui/custom_nodes/NodeA", "NodeA")
        self.assertTrue(result.endswith("NodeA.bak.1700000000.2"))
        mock_rename.assert_called_once()

    @patch("services.git.git_cloner.os.rename")
    @patch("services.git.git_cloner.os.path.exists", return_value=False)
    @patch("services.git.git_cloner.time.time", return_value=1700000000.0)
    @patch("services.git.git_cloner.constants")
    def test_return_is_absolute_path(self, mock_constants, _time, _exists, mock_rename):
        mock_constants.COMFYUI_DIR = "/comfyui"
        result = self.cloner._rename_existing_dir("/comfyui/custom_nodes/NodeA", "NodeA")
        self.assertTrue(result.startswith("/"))


# ── _run_clone ────────────────────────────────────────────────────────────────

class TestRunClone(unittest.TestCase):

    def setUp(self):
        self.cloner = GitCloner()

    def test_missing_clone_url_returns_false(self):
        info = NodeMapValue(name="Test", source=NodeSource(type="github", cloneUrl=None))
        ok, err = self.cloner._run_clone(info, "/fake/path")
        self.assertFalse(ok)
        self.assertEqual(err, "missing cloneUrl")

    @patch("services.git.git_cloner._run_cmd")
    def test_default_clone_no_version(self, mock_run_cmd):
        info = _make_info()
        ok, err = self.cloner._run_clone(info, "/fake/target")
        self.assertTrue(ok)
        self.assertIsNone(err)
        mock_run_cmd.assert_called_once_with(
            ["git", "clone", "--depth", "1", "https://github.com/test/repo.git", "/fake/target"],
            CLONE_TIMEOUT,
        )

    @patch("services.git.git_cloner._run_cmd")
    def test_tag_version_uses_dash_b(self, mock_run_cmd):
        info = _make_info(version_type="tag", version_value="v1.0.0")
        ok, err = self.cloner._run_clone(info, "/fake/target")
        self.assertTrue(ok)
        mock_run_cmd.assert_called_once_with(
            ["git", "clone", "--depth", "1", "-b", "v1.0.0", "https://github.com/test/repo.git", "/fake/target"],
            CLONE_TIMEOUT,
        )

    @patch("services.git.git_cloner.os.makedirs")
    @patch("services.git.git_cloner._run_cmd")
    def test_commit_id_uses_bash_init_flow(self, mock_run_cmd, mock_makedirs):
        info = _make_info(version_type="commit", version_value="abc1234")
        ok, err = self.cloner._run_clone(info, "/fake/target")
        self.assertTrue(ok)
        mock_makedirs.assert_called_once_with("/fake/target", exist_ok=True)
        cmd_args = mock_run_cmd.call_args[0][0]
        self.assertEqual(cmd_args[0], "bash")
        self.assertIn("git init", cmd_args[2])
        self.assertIn("abc1234", cmd_args[2])
        self.assertIn("FETCH_HEAD", cmd_args[2])

    @patch("services.git.git_cloner._run_cmd")
    def test_tag_with_empty_value_falls_back_to_default(self, mock_run_cmd):
        """version.type=tag 但 value 为 None 时，回退到默认 clone"""
        info = _make_info(version_type="tag", version_value=None)
        ok, err = self.cloner._run_clone(info, "/fake/target")
        self.assertTrue(ok)
        cmd = mock_run_cmd.call_args[0][0]
        self.assertNotIn("-b", cmd)

    @patch("services.git.git_cloner._run_cmd")
    def test_unknown_version_type_falls_back_to_default(self, mock_run_cmd):
        info = _make_info(version_type="branch", version_value="main")
        ok, err = self.cloner._run_clone(info, "/fake/target")
        self.assertTrue(ok)
        cmd = mock_run_cmd.call_args[0][0]
        self.assertNotIn("-b", cmd)

    @patch("services.git.git_cloner.shutil.rmtree")
    @patch("services.git.git_cloner.os.path.isdir", return_value=True)
    @patch(
        "services.git.git_cloner._run_cmd",
        side_effect=subprocess.CalledProcessError(1, "git", stderr="fatal: repo not found"),
    )
    def test_retries_on_called_process_error(self, mock_run_cmd, _isdir, mock_rmtree):
        info = _make_info()
        ok, err = self.cloner._run_clone(info, "/fake/target")
        self.assertFalse(ok)
        self.assertIn("fatal: repo not found", err)
        # MAX_CLONE_RETRIES=1 → 2 total attempts
        self.assertEqual(mock_run_cmd.call_count, 2)
        mock_rmtree.assert_called()

    @patch("services.git.git_cloner.shutil.rmtree")
    @patch("services.git.git_cloner.os.path.isdir", return_value=True)
    @patch("services.git.git_cloner._run_cmd", side_effect=subprocess.TimeoutExpired("git", 30))
    def test_retries_on_timeout(self, mock_run_cmd, _isdir, mock_rmtree):
        info = _make_info()
        ok, err = self.cloner._run_clone(info, "/fake/target")
        self.assertFalse(ok)
        self.assertEqual(err, "timeout")
        self.assertEqual(mock_run_cmd.call_count, 2)

    @patch("services.git.git_cloner.shutil.rmtree")
    @patch("services.git.git_cloner.os.path.isdir", return_value=True)
    @patch("services.git.git_cloner._run_cmd")
    def test_succeeds_on_retry(self, mock_run_cmd, _isdir, _rmtree):
        mock_run_cmd.side_effect = [subprocess.CalledProcessError(1, "git", stderr="err"), None]
        info = _make_info()
        ok, err = self.cloner._run_clone(info, "/fake/target")
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual(mock_run_cmd.call_count, 2)

    @patch("services.git.git_cloner.os.path.isdir", return_value=False)
    @patch(
        "services.git.git_cloner._run_cmd",
        side_effect=subprocess.CalledProcessError(128, "git", stderr=""),
    )
    def test_empty_stderr_uses_exit_code_message(self, mock_run_cmd, _isdir):
        info = _make_info()
        ok, err = self.cloner._run_clone(info, "/fake/target")
        self.assertFalse(ok)
        self.assertIn("128", err)

    @patch("services.git.git_cloner.os.path.isdir", return_value=False)
    @patch("services.git.git_cloner.shutil.rmtree")
    @patch(
        "services.git.git_cloner._run_cmd",
        side_effect=subprocess.CalledProcessError(1, "git", stderr="err"),
    )
    def test_no_rmtree_when_target_not_exists_on_retry(self, _run_cmd, mock_rmtree, _isdir):
        """重试前 target_path 不存在时不调用 rmtree"""
        info = _make_info()
        self.cloner._run_clone(info, "/fake/target")
        mock_rmtree.assert_not_called()


# ── _clone_single_node ────────────────────────────────────────────────────────

class TestCloneSingleNode(unittest.TestCase):

    def setUp(self):
        self.cloner = GitCloner()
        self.info = _make_info()

    def _existing(self, *names, parent: str = "/comfyui/custom_nodes"):
        """构造 existing_lower 映射：小写名 → 完整路径"""
        return {n.lower(): f"{parent}/{n}" for n in names}

    # ── 情况 1：无冲突 ──────────────────────────────────────────────────────

    @patch("services.git.git_cloner.constants")
    @patch.object(GitCloner, "_run_clone", return_value=(True, None))
    def test_new_node_returns_cloned(self, mock_run_clone, mock_constants):
        mock_constants.COMFYUI_DIR = "/comfyui"
        result = self.cloner._clone_single_node("NodeA", self.info, {}, CONFLICT_SKIP)
        self.assertEqual(result.status, STATUS_CLONED)
        mock_run_clone.assert_called_once()

    @patch("services.git.git_cloner.constants")
    @patch.object(GitCloner, "_run_clone", return_value=(True, None))
    def test_cloned_result_contains_path(self, _run_clone, mock_constants):
        mock_constants.COMFYUI_DIR = "/comfyui"
        result = self.cloner._clone_single_node("NodeA", self.info, {}, CONFLICT_SKIP)
        self.assertEqual(result.status, STATUS_CLONED)
        self.assertIsNotNone(result.path)
        self.assertIn("NodeA", result.path)

    @patch("services.git.git_cloner.constants")
    @patch.object(GitCloner, "_run_clone", return_value=(True, None))
    def test_cloned_result_has_duration(self, _run_clone, mock_constants):
        mock_constants.COMFYUI_DIR = "/comfyui"
        result = self.cloner._clone_single_node("NodeA", self.info, {}, CONFLICT_SKIP)
        self.assertGreaterEqual(result.duration, 0)

    # ── 情况 2：跳过策略 ────────────────────────────────────────────────────

    @patch("services.git.git_cloner.constants")
    def test_existing_node_skip_strategy_returns_skipped(self, mock_constants):
        mock_constants.COMFYUI_DIR = "/comfyui"
        result = self.cloner._clone_single_node("NodeA", self.info, self._existing("NodeA"), CONFLICT_SKIP)
        self.assertEqual(result.status, STATUS_SKIPPED)
        self.assertEqual(result.reason, "directory_exists")

    @patch("services.git.git_cloner.constants")
    def test_unknown_strategy_treated_as_skip(self, mock_constants):
        mock_constants.COMFYUI_DIR = "/comfyui"
        result = self.cloner._clone_single_node("NodeA", self.info, self._existing("NodeA"), "whatever")
        self.assertEqual(result.status, STATUS_SKIPPED)

    @patch("services.git.git_cloner.constants")
    def test_case_insensitive_conflict_detection(self, mock_constants):
        """node_name 大小写与 existing_lower 的小写键匹配"""
        mock_constants.COMFYUI_DIR = "/comfyui"
        result = self.cloner._clone_single_node("NODEA", self.info, self._existing("NodeA"), CONFLICT_SKIP)
        self.assertEqual(result.status, STATUS_SKIPPED)

    @patch("services.git.git_cloner.constants")
    def test_skip_applies_regardless_of_existing_dir(self, mock_constants):
        """跳过策略对默认目录和其他目录中的插件均生效"""
        mock_constants.COMFYUI_DIR = "/comfyui"
        existing_other = self._existing("NodeA", parent="/image/custom_nodes")
        result = self.cloner._clone_single_node("NodeA", self.info, existing_other, CONFLICT_SKIP)
        self.assertEqual(result.status, STATUS_SKIPPED)

    # ── 情况 3：覆盖策略 + 已有插件在默认目录 ──────────────────────────────

    @patch("services.git.git_cloner.shutil.rmtree")
    @patch("services.git.git_cloner.os.path.isdir", return_value=True)
    @patch.object(GitCloner, "_run_clone", return_value=(True, None))
    @patch.object(GitCloner, "_rename_existing_dir", return_value="/comfyui/custom_nodes/NodeA.bak.123")
    @patch("services.git.git_cloner.constants")
    def test_override_default_dir_success_backs_up_and_returns_overridden(
        self, mock_constants, _rename, _run_clone, _isdir, mock_rmtree
    ):
        mock_constants.COMFYUI_DIR = "/comfyui"
        result = self.cloner._clone_single_node("NodeA", self.info, self._existing("NodeA"), CONFLICT_OVERRIDE)
        self.assertEqual(result.status, STATUS_OVERRIDDEN)
        self.assertIsNotNone(result.previous_path)
        mock_rmtree.assert_called_with("/comfyui/custom_nodes/NodeA.bak.123", ignore_errors=True)

    @patch("services.git.git_cloner.os.rename")
    @patch("services.git.git_cloner.shutil.rmtree")
    @patch("services.git.git_cloner.os.path.isdir")
    @patch.object(GitCloner, "_run_clone", return_value=(False, "network error"))
    @patch.object(GitCloner, "_rename_existing_dir", return_value="/comfyui/custom_nodes/NodeA.bak.123")
    @patch("services.git.git_cloner.constants")
    def test_override_default_dir_clone_fails_restores_backup(
        self, mock_constants, _rename_dir, _run_clone, mock_isdir, _rmtree, mock_os_rename
    ):
        mock_constants.COMFYUI_DIR = "/comfyui"
        # backup path exists (to be restored); node_path does not exist (no cleanup needed)
        mock_isdir.side_effect = lambda p: "bak" in p
        result = self.cloner._clone_single_node("NodeA", self.info, self._existing("NodeA"), CONFLICT_OVERRIDE)
        self.assertEqual(result.status, STATUS_FAILED)
        self.assertIn("network error", result.error_msg)
        mock_os_rename.assert_called_once()

    # ── 情况 4：覆盖策略 + 已有插件在其他目录 ──────────────────────────────

    @patch("services.git.git_cloner.constants")
    @patch.object(GitCloner, "_run_clone", return_value=(True, None))
    def test_override_other_dir_clones_without_backup(self, _run_clone, mock_constants):
        """情况 4：插件在其他目录（只读）→ 直接 clone 到默认目录，无需备份"""
        mock_constants.COMFYUI_DIR = "/comfyui"
        existing_other = self._existing("NodeA", parent="/image/custom_nodes")
        result = self.cloner._clone_single_node("NodeA", self.info, existing_other, CONFLICT_OVERRIDE)
        self.assertEqual(result.status, STATUS_OVERRIDDEN)
        self.assertIsNone(result.previous_path)

    @patch("services.git.git_cloner.shutil.rmtree")
    @patch("services.git.git_cloner.os.path.isdir", return_value=True)
    @patch.object(GitCloner, "_run_clone", return_value=(False, "fatal"))
    @patch("services.git.git_cloner.constants")
    def test_override_other_dir_clone_fails_no_restore(self, mock_constants, _run_clone, _isdir, mock_rmtree):
        """情况 4 clone 失败：清理残留目录，但不还原（其他目录原本未动）"""
        mock_constants.COMFYUI_DIR = "/comfyui"
        existing_other = self._existing("NodeA", parent="/image/custom_nodes")
        result = self.cloner._clone_single_node("NodeA", self.info, existing_other, CONFLICT_OVERRIDE)
        self.assertEqual(result.status, STATUS_FAILED)
        mock_rmtree.assert_called_once()

    # ── 通用失败路径 ────────────────────────────────────────────────────────

    @patch("services.git.git_cloner.shutil.rmtree")
    @patch("services.git.git_cloner.os.path.isdir", return_value=True)
    @patch.object(GitCloner, "_run_clone", return_value=(False, "fatal"))
    @patch("services.git.git_cloner.constants")
    def test_new_node_clone_fails_cleans_up_partial_dir(self, mock_constants, _run_clone, _isdir, mock_rmtree):
        mock_constants.COMFYUI_DIR = "/comfyui"
        result = self.cloner._clone_single_node("NodeA", self.info, {}, CONFLICT_SKIP)
        self.assertEqual(result.status, STATUS_FAILED)
        mock_rmtree.assert_called_once()

    @patch("services.git.git_cloner.os.path.isdir", return_value=False)
    @patch.object(GitCloner, "_run_clone", return_value=(False, "fatal"))
    @patch("services.git.git_cloner.constants")
    def test_new_node_clone_fails_no_cleanup_if_dir_absent(self, mock_constants, _run_clone, _isdir):
        mock_constants.COMFYUI_DIR = "/comfyui"
        result = self.cloner._clone_single_node("NodeA", self.info, {}, CONFLICT_SKIP)
        self.assertEqual(result.status, STATUS_FAILED)


# ── _process_and_clone_nodes（超时）─────────────────────────────────────────

class TestProcessAndCloneNodesTimeout(unittest.TestCase):

    def setUp(self):
        self.cloner = GitCloner()

    @patch("services.git.git_cloner.constants")
    @patch.object(GitCloner, "_get_existing_lower", return_value={})
    @patch.object(GitCloner, "_clone_single_node")
    @patch("services.git.git_cloner.time.time", return_value=9999.0)
    def test_all_nodes_timeout_immediately(self, _time, mock_clone, _lower, mock_constants):
        """time.time() 远大于 start_time + timeout，所有插件应标记 failed/timeout"""
        mock_constants.COMFYUI_DIR = "/comfyui"
        info_a = _make_info()
        info_b = _make_info()
        parsed = {"NodeA": info_a, "NodeB": info_b}

        result = self.cloner._process_and_clone_nodes(parsed, CONFLICT_SKIP, timeout=1, start_time=0)

        mock_clone.assert_not_called()
        self.assertEqual(len(result), 2)
        for detail in result.values():
            self.assertEqual(detail.status, STATUS_FAILED)
            self.assertEqual(detail.error_msg, "timeout")

    @patch("services.git.git_cloner.constants")
    @patch.object(GitCloner, "_get_existing_lower", return_value={})
    @patch.object(GitCloner, "_clone_single_node")
    @patch("services.git.git_cloner.time.time")
    def test_second_node_timeout_after_first_processed(self, mock_time, mock_clone, _lower, mock_constants):
        """第一个节点处理正常，第二个节点在处理前超时"""
        mock_constants.COMFYUI_DIR = "/comfyui"
        # time.time() 在 _process_and_clone_nodes 循环里每轮调用一次做超时检测；
        # 第一轮 0.0（不超时）→ NodeA 正常处理；第二轮 9999.0（超时）→ NodeB 标记 failed
        mock_time.side_effect = [0.0, 9999.0]
        mock_clone.return_value = CloneDetail(status=STATUS_CLONED)
        parsed = {"NodeA": _make_info(), "NodeB": _make_info()}

        result = self.cloner._process_and_clone_nodes(parsed, CONFLICT_SKIP, timeout=100, start_time=0)

        self.assertEqual(result["NodeA"].status, STATUS_CLONED)
        self.assertEqual(result["NodeB"].status, STATUS_FAILED)
        self.assertEqual(result["NodeB"].error_msg, "timeout")


# ── clone_all ─────────────────────────────────────────────────────────────────

class TestCloneAll(unittest.TestCase):

    def setUp(self):
        self.cloner = GitCloner()

    @patch("services.git.git_cloner.constants")
    def test_none_nodes_map_returns_empty(self, mock_constants):
        mock_constants.DEFAULT_INSTALL_TIMEOUT = 900
        result = self.cloner.clone_all(nodes_map=None)
        self.assertEqual(result["details"], {})
        self.assertEqual(result["summary"]["total"], 0)

    @patch("services.git.git_cloner.constants")
    def test_empty_nodes_map_returns_empty(self, mock_constants):
        mock_constants.DEFAULT_INSTALL_TIMEOUT = 900
        result = self.cloner.clone_all(nodes_map={})
        self.assertEqual(result["details"], {})
        self.assertEqual(result["summary"]["total"], 0)

    @patch("services.git.git_cloner.constants")
    def test_all_invalid_entries_parsed_to_empty(self, mock_constants):
        """全部条目校验失败 → parsed 为空 → 提前返回"""
        mock_constants.DEFAULT_INSTALL_TIMEOUT = 900
        result = self.cloner.clone_all(nodes_map={"Bad": "not-a-dict"})
        self.assertEqual(result["details"], {})
        self.assertEqual(result["summary"]["total"], 0)

    @patch("services.git.git_cloner.constants")
    def test_return_structure_contains_details_and_summary(self, mock_constants):
        mock_constants.DEFAULT_INSTALL_TIMEOUT = 900
        result = self.cloner.clone_all(nodes_map={})
        self.assertIn("details", result)
        self.assertIn("summary", result)
        self.assertIsInstance(result["details"], dict)
        self.assertIsInstance(result["summary"], dict)

    @patch("services.git.git_cloner.constants")
    @patch.object(GitCloner, "_process_and_clone_nodes")
    def test_summary_counts_cloned(self, mock_process, mock_constants):
        mock_constants.DEFAULT_INSTALL_TIMEOUT = 900
        mock_process.return_value = {
            "NodeA": CloneDetail(status=STATUS_CLONED),
            "NodeB": CloneDetail(status=STATUS_CLONED),
        }
        nodes_map = {
            "NodeA": {"name": "NodeA", "source": {"type": "github", "cloneUrl": "https://a.git"}},
            "NodeB": {"name": "NodeB", "source": {"type": "github", "cloneUrl": "https://b.git"}},
        }
        result = self.cloner.clone_all(nodes_map=nodes_map)
        s = result["summary"]
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["cloned"], 2)
        self.assertEqual(s["skipped"], 0)
        self.assertEqual(s["failed"], 0)

    @patch("services.git.git_cloner.constants")
    @patch.object(GitCloner, "_process_and_clone_nodes")
    def test_summary_counts_skipped(self, mock_process, mock_constants):
        mock_constants.DEFAULT_INSTALL_TIMEOUT = 900
        mock_process.return_value = {
            "NodeA": CloneDetail(status=STATUS_SKIPPED, reason="directory_exists"),
        }
        nodes_map = {
            "NodeA": {"name": "NodeA", "source": {"type": "github", "cloneUrl": "https://a.git"}},
        }
        result = self.cloner.clone_all(nodes_map=nodes_map)
        self.assertEqual(result["summary"]["skipped"], 1)
        self.assertEqual(result["summary"]["cloned"], 0)

    @patch("services.git.git_cloner.constants")
    @patch.object(GitCloner, "_process_and_clone_nodes")
    def test_summary_counts_overridden(self, mock_process, mock_constants):
        mock_constants.DEFAULT_INSTALL_TIMEOUT = 900
        mock_process.return_value = {
            "NodeA": CloneDetail(status=STATUS_OVERRIDDEN),
        }
        nodes_map = {
            "NodeA": {"name": "NodeA", "source": {"type": "github", "cloneUrl": "https://a.git"}},
        }
        result = self.cloner.clone_all(nodes_map=nodes_map)
        self.assertEqual(result["summary"]["overridden"], 1)

    @patch("services.git.git_cloner.constants")
    @patch.object(GitCloner, "_process_and_clone_nodes")
    def test_summary_counts_failed(self, mock_process, mock_constants):
        mock_constants.DEFAULT_INSTALL_TIMEOUT = 900
        mock_process.return_value = {
            "NodeA": CloneDetail(status=STATUS_FAILED, error_msg="some error"),
        }
        nodes_map = {
            "NodeA": {"name": "NodeA", "source": {"type": "github", "cloneUrl": "https://a.git"}},
        }
        result = self.cloner.clone_all(nodes_map=nodes_map)
        self.assertEqual(result["summary"]["failed"], 1)

    @patch("services.git.git_cloner.constants")
    @patch.object(GitCloner, "_process_and_clone_nodes")
    def test_summary_mixed_counts(self, mock_process, mock_constants):
        mock_constants.DEFAULT_INSTALL_TIMEOUT = 900
        mock_process.return_value = {
            "NodeA": CloneDetail(status=STATUS_CLONED),
            "NodeB": CloneDetail(status=STATUS_SKIPPED, reason="directory_exists"),
            "NodeC": CloneDetail(status=STATUS_OVERRIDDEN),
            "NodeD": CloneDetail(status=STATUS_FAILED, error_msg="err"),
        }
        nodes_map = {
            k: {"name": k, "source": {"type": "github", "cloneUrl": f"https://{k}.git"}}
            for k in ["NodeA", "NodeB", "NodeC", "NodeD"]
        }
        result = self.cloner.clone_all(nodes_map=nodes_map)
        s = result["summary"]
        self.assertEqual(s["total"], 4)
        self.assertEqual(s["cloned"], 1)
        self.assertEqual(s["skipped"], 1)
        self.assertEqual(s["overridden"], 1)
        self.assertEqual(s["failed"], 1)

    @patch("services.git.git_cloner.constants")
    @patch.object(GitCloner, "_process_and_clone_nodes")
    def test_details_are_serialized_dicts(self, mock_process, mock_constants):
        mock_constants.DEFAULT_INSTALL_TIMEOUT = 900
        mock_process.return_value = {
            "NodeA": CloneDetail(status=STATUS_CLONED, duration=1.5, path="/comfyui/custom_nodes/NodeA"),
        }
        nodes_map = {
            "NodeA": {"name": "NodeA", "source": {"type": "github", "cloneUrl": "https://a.git"}},
        }
        result = self.cloner.clone_all(nodes_map=nodes_map)
        detail = result["details"]["NodeA"]
        self.assertIsInstance(detail, dict)
        self.assertEqual(detail["status"], STATUS_CLONED)
        self.assertIn("duration", detail)
        self.assertIn("path", detail)

    @patch("services.git.git_cloner.constants")
    @patch.object(GitCloner, "_process_and_clone_nodes")
    def test_summary_contains_duration(self, mock_process, mock_constants):
        mock_constants.DEFAULT_INSTALL_TIMEOUT = 900
        mock_process.return_value = {}
        nodes_map = {
            "NodeA": {"name": "NodeA", "source": {"type": "github", "cloneUrl": "https://a.git"}},
        }
        result = self.cloner.clone_all(nodes_map=nodes_map)
        self.assertIn("duration", result["summary"])
        self.assertGreaterEqual(result["summary"]["duration"], 0)

    @patch("services.git.git_cloner.constants")
    @patch.object(GitCloner, "_process_and_clone_nodes")
    def test_total_reflects_parsed_count_not_raw_map(self, mock_process, mock_constants):
        """total 来自解析后的有效条目数，非 nodes_map 原始长度"""
        mock_constants.DEFAULT_INSTALL_TIMEOUT = 900
        mock_process.return_value = {
            "Good": CloneDetail(status=STATUS_CLONED),
        }
        nodes_map = {
            "Good": {"name": "Good", "source": {"type": "github", "cloneUrl": "https://g.git"}},
            "Bad": "not-a-dict",
        }
        result = self.cloner.clone_all(nodes_map=nodes_map)
        self.assertEqual(result["summary"]["total"], 1)


# ── models ────────────────────────────────────────────────────────────────────

class TestModels(unittest.TestCase):
    """Pydantic 模型的基础行为验证。"""

    def test_node_map_value_name_validator_empty(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            NodeMapValue(name="", source=NodeSource(type="github"))

    def test_node_map_value_name_validator_whitespace(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            NodeMapValue(name="  ", source=NodeSource(type="github"))

    def test_clone_detail_to_dict_excludes_none(self):
        detail = CloneDetail(status=STATUS_CLONED, duration=1.0, path="/some/path")
        d = detail.to_dict()
        self.assertNotIn("reason", d)
        self.assertNotIn("error_msg", d)
        self.assertNotIn("previous_path", d)
        self.assertEqual(d["status"], STATUS_CLONED)

    def test_clone_detail_to_dict_includes_set_fields(self):
        detail = CloneDetail(
            status=STATUS_FAILED,
            error_msg="boom",
            reason="directory_exists",
        )
        d = detail.to_dict()
        self.assertEqual(d["error_msg"], "boom")
        self.assertEqual(d["reason"], "directory_exists")

    def test_clone_summary_to_dict_all_fields_present(self):
        from services.git.models import CloneSummary
        summary = CloneSummary(total=3, cloned=1, skipped=1, overridden=0, failed=1, duration=2.5)
        d = summary.to_dict()
        for key in ("total", "cloned", "skipped", "overridden", "failed", "duration"):
            self.assertIn(key, d)


if __name__ == "__main__":
    unittest.main()
