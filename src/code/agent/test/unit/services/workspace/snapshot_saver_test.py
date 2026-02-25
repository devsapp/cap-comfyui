import os
import pytest
import shutil
from unittest.mock import patch, MagicMock

import constants
from services.workspace.snapshot_saver import SDSnapshotSaver, ComfyUISnapshotSaver


@pytest.fixture
def setup_dirs(tmp_path):
    """设置测试环境目录"""
    constants.WORK_DIR = str(tmp_path / "work")
    constants.SNAPSHOT_DIR = str(tmp_path / "snapshots")

    # 创建必要的目录
    os.makedirs(constants.WORK_DIR, exist_ok=True)
    os.makedirs(constants.SNAPSHOT_DIR, exist_ok=True)
    os.makedirs(os.path.join(constants.WORK_DIR, "venv"))
    os.makedirs(os.path.join(constants.WORK_DIR, "stable-diffusion-webui"))
    os.makedirs(os.path.join(constants.WORK_DIR, "comfyui"))
    os.makedirs(os.path.join(constants.WORK_DIR, ".cache"))

    # 创建一些测试文件
    with open(os.path.join(constants.WORK_DIR, "venv/test.txt"), "w") as f:
        f.write("test venv content")
    with open(os.path.join(constants.WORK_DIR, "stable-diffusion-webui/test.txt"), "w") as f:
        f.write("test sd content")
    with open(os.path.join(constants.WORK_DIR, "comfyui/test.txt"), "w") as f:
        f.write("test comfy content")

    return tmp_path


class MockTimer:
    def __init__(self, name):
        self.name = name
        self.elapsed = 1.5

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.fixture
def mock_timer():
    return lambda x: MockTimer(x)


@pytest.fixture(autouse=True)
def cleanup(setup_dirs):
    yield
    shutil.rmtree(setup_dirs)


class TestSDSnapshotSaver:
    @pytest.fixture
    def saver(self, mock_timer):
        return SDSnapshotSaver(mock_timer)

    def test_save_snapshot(self, setup_dirs, saver):
        """测试保存SD快照基本功能"""
        snapshot_name = "test_snapshot"
        
        # Mock compress 和 upload 方法
        with patch.object(saver, '_compress') as mock_compress:
            with patch.object(saver, '_upload') as mock_upload:
                stage_cost = saver.save(snapshot_name)

        # 验证时间统计
        assert all(key in stage_cost for key in ["time_compress", "time_upload"])
        assert "time_clear" not in stage_cost

        # 验证快照目录已创建
        snapshot_path = os.path.join(constants.SNAPSHOT_DIR, snapshot_name)
        assert os.path.exists(snapshot_path)
        
        # 验证 compress 和 upload 被调用
        assert mock_compress.called
        assert mock_upload.called

    def test_save_snapshot_with_cache(self, setup_dirs, saver):
        """测试保存带缓存的快照"""
        snapshot_name = "test_snapshot"
        with open(os.path.join(constants.WORK_DIR, ".cache/test.txt"), "w") as f:
            f.write("test cache")

        # Mock compress 和 upload 方法
        with patch.object(saver, '_compress') as mock_compress:
            with patch.object(saver, '_upload') as mock_upload:
                stage_cost = saver.save(snapshot_name)

        # 验证快照目录已创建
        snapshot_path = os.path.join(constants.SNAPSHOT_DIR, snapshot_name)
        assert os.path.exists(snapshot_path)
        
        # 验证 compress 和 upload 被调用
        assert mock_compress.called
        assert mock_upload.called

    def test_save_with_auto_cleanup(self, setup_dirs, saver):
        """测试启用自动清理时，清理超过限制的旧快照"""
        # 创建 4 个 dev 快照（超过限制）
        snapshot_prefix = "dev"
        old_snapshots = [
            f"{snapshot_prefix}-20260101-120000",
            f"{snapshot_prefix}-20260102-120000",
            f"{snapshot_prefix}-20260103-120000",
            f"{snapshot_prefix}-20260104-120000"
        ]
        
        for old_name in old_snapshots:
            old_path = os.path.join(constants.SNAPSHOT_DIR, old_name)
            os.makedirs(old_path)
            with open(os.path.join(old_path, "test.txt"), "w") as f:
                f.write(f"old snapshot {old_name}")

        # Mock compress 和 upload 方法以避免真实文件操作
        with patch.object(saver, '_compress'):
            with patch.object(saver, '_upload'):
                # 保存新快照（第 5 个），显式启用自动清理并传递前缀
                new_name = f"{snapshot_prefix}-20260105-120000"
                stage_cost = saver.save(new_name, auto_cleanup=True, cleanup_prefix=snapshot_prefix, max_snapshots=3)

        # 验证只保留最新的 3 个（新的 + 最新的 2 个旧的）
        remaining_snapshots = [
            d for d in os.listdir(constants.SNAPSHOT_DIR)
            if d.startswith(f"{snapshot_prefix}-")
        ]
        assert len(remaining_snapshots) == 3
        
        # 验证保留的是最新的 3 个
        assert f"{snapshot_prefix}-20260103-120000" in remaining_snapshots
        assert f"{snapshot_prefix}-20260104-120000" in remaining_snapshots
        assert new_name in remaining_snapshots
        
        # 验证最旧的 2 个被删除
        assert not os.path.exists(os.path.join(constants.SNAPSHOT_DIR, f"{snapshot_prefix}-20260101-120000"))
        assert not os.path.exists(os.path.join(constants.SNAPSHOT_DIR, f"{snapshot_prefix}-20260102-120000"))
        
        # 验证清理统计
        assert "time_clean" in stage_cost
        assert stage_cost["cleaned_snapshots"] == 2
    
    def test_save_without_auto_cleanup(self, setup_dirs, saver):
        """测试默认不启用自动清理（auto_cleanup=False）"""
        # 创建一些 dev 快照
        for i in range(5):
            snapshot_name = f"dev-2026010{i}-120000"
            os.makedirs(os.path.join(constants.SNAPSHOT_DIR, snapshot_name))
        
        # Mock compress 和 upload 方法
        with patch.object(saver, '_compress'):
            with patch.object(saver, '_upload'):
                # 保存新快照但不启用自动清理（默认行为）
                new_name = "dev-20260106-120000"
                stage_cost = saver.save(new_name, auto_cleanup=False)
        
        # 验证所有快照都还存在（6 个）
        all_snapshots = [d for d in os.listdir(constants.SNAPSHOT_DIR) if d.startswith("dev-")]
        assert len(all_snapshots) == 6
        
        # 验证没有清理统计
        assert "time_clean" not in stage_cost
        assert "cleaned_snapshots" not in stage_cost
    
    def test_auto_cleanup_enabled_but_no_prefix(self, setup_dirs, saver):
        """测试启用自动清理但未提供 cleanup_prefix 时不执行清理"""
        # 创建一些快照
        for i in range(5):
            snapshot_name = f"dev-2026010{i}-120000"
            os.makedirs(os.path.join(constants.SNAPSHOT_DIR, snapshot_name))
        
        # Mock compress 和 upload 方法
        with patch.object(saver, '_compress'):
            with patch.object(saver, '_upload'):
                # 启用 auto_cleanup 但不提供 cleanup_prefix
                new_name = "dev-20260106-120000"
                stage_cost = saver.save(new_name, auto_cleanup=True, cleanup_prefix=None)
        
        # 验证所有快照都还存在（6 个），因为没有提供 cleanup_prefix
        all_snapshots = [d for d in os.listdir(constants.SNAPSHOT_DIR) if d.startswith("dev-")]
        assert len(all_snapshots) == 6
        
        # 验证没有清理统计
        assert "time_clean" not in stage_cost
        assert "cleaned_snapshots" not in stage_cost
    
    def test_cleanup_when_snapshots_not_exceed_limit(self, setup_dirs, saver):
        """测试快照数量未超过限制时不清理"""
        snapshot_prefix = "dev"
        # 只创建 2 个快照（少于限制 3 个）
        old_snapshots = [
            f"{snapshot_prefix}-20260101-120000",
            f"{snapshot_prefix}-20260102-120000"
        ]
        
        for old_name in old_snapshots:
            os.makedirs(os.path.join(constants.SNAPSHOT_DIR, old_name))
        
        with patch.object(saver, '_compress'):
            with patch.object(saver, '_upload'):
                # 保存新快照（第 3 个），刚好等于限制
                new_name = f"{snapshot_prefix}-20260103-120000"
                stage_cost = saver.save(new_name, auto_cleanup=True, cleanup_prefix=snapshot_prefix, max_snapshots=3)
        
        # 验证所有 3 个快照都保留
        remaining_snapshots = [
            d for d in os.listdir(constants.SNAPSHOT_DIR)
            if d.startswith(f"{snapshot_prefix}-")
        ]
        assert len(remaining_snapshots) == 3
        
        # 验证没有清理任何快照
        assert stage_cost.get("cleaned_snapshots", 0) == 0
    
    def test_cleanup_with_different_max_snapshots(self, setup_dirs, saver):
        """测试不同的 max_snapshots 值"""
        snapshot_prefix = "dev"
        # 创建 6 个快照
        for i in range(1, 7):
            old_name = f"{snapshot_prefix}-2026010{i}-120000"
            os.makedirs(os.path.join(constants.SNAPSHOT_DIR, old_name))
        
        with patch.object(saver, '_compress'):
            with patch.object(saver, '_upload'):
                # 保存新快照，只保留最新 2 个
                new_name = f"{snapshot_prefix}-20260107-120000"
                stage_cost = saver.save(new_name, auto_cleanup=True, cleanup_prefix=snapshot_prefix, max_snapshots=2)
        
        # 验证只保留最新的 2 个
        remaining_snapshots = [
            d for d in os.listdir(constants.SNAPSHOT_DIR)
            if d.startswith(f"{snapshot_prefix}-")
        ]
        assert len(remaining_snapshots) == 2
        
        # 验证清理了 5 个旧快照（7 - 2 = 5）
        assert stage_cost["cleaned_snapshots"] == 5
        
        # 验证保留的是最新的 2 个
        assert f"{snapshot_prefix}-20260106-120000" in remaining_snapshots
        assert new_name in remaining_snapshots
    
    def test_cleanup_only_targets_specified_prefix(self, setup_dirs, saver):
        """测试清理只针对指定前缀的快照，不影响其他类型"""
        # 创建多个 dev 快照
        for i in range(1, 5):
            dev_name = f"dev-2026010{i}-120000"
            os.makedirs(os.path.join(constants.SNAPSHOT_DIR, dev_name))
        
        # 创建多个 prod 快照
        for i in range(1, 5):
            prod_name = f"prod-2026010{i}-120000"
            os.makedirs(os.path.join(constants.SNAPSHOT_DIR, prod_name))
        
        with patch.object(saver, '_compress'):
            with patch.object(saver, '_upload'):
                # 保存新的 dev 快照，只清理 dev 类型
                new_name = "dev-20260105-120000"
                stage_cost = saver.save(new_name, auto_cleanup=True, cleanup_prefix="dev", max_snapshots=3)
        
        # 验证 dev 快照只保留 3 个
        dev_snapshots = [d for d in os.listdir(constants.SNAPSHOT_DIR) if d.startswith("dev-")]
        assert len(dev_snapshots) == 3
        
        # 验证 prod 快照完全不受影响（仍然是 4 个）
        prod_snapshots = [d for d in os.listdir(constants.SNAPSHOT_DIR) if d.startswith("prod-")]
        assert len(prod_snapshots) == 4
        
        # 验证清理了 2 个 dev 快照
        assert stage_cost["cleaned_snapshots"] == 2
    
    def test_cleanup_snapshot_dir_not_exists(self, setup_dirs, saver):
        """测试 SNAPSHOT_DIR 不存在时的清理逻辑"""
        # 删除 SNAPSHOT_DIR
        shutil.rmtree(constants.SNAPSHOT_DIR)
        
        with patch.object(saver, '_compress'):
            with patch.object(saver, '_upload'):
                # 保存会创建目录，清理应该能正常处理空目录
                new_name = "dev-20260101-120000"
                stage_cost = saver.save(new_name, auto_cleanup=True, cleanup_prefix="dev", max_snapshots=3)
        
        # 验证只有新快照
        all_snapshots = os.listdir(constants.SNAPSHOT_DIR)
        assert len(all_snapshots) == 1
        assert "dev-20260101-120000" in all_snapshots
        
        # 验证没有清理任何快照（因为只有新的一个）
        assert stage_cost.get("cleaned_snapshots", 0) == 0


class TestComfyUISnapshotSaver:
    @pytest.fixture
    def saver(self, mock_timer):
        return ComfyUISnapshotSaver(mock_timer)

    def test_save_snapshot(self, setup_dirs, saver):
        """测试保存ComfyUI开发版快照"""
        snapshot_name = "test_snapshot"
        
        # Mock compress 和 upload 方法
        with patch.object(saver, '_compress') as mock_compress:
            with patch.object(saver, '_upload') as mock_upload:
                stage_cost = saver.save(snapshot_name)

        # 验证时间统计
        assert all(key in stage_cost for key in ["time_compress", "time_upload"])

        # 验证快照目录已创建
        snapshot_path = os.path.join(constants.SNAPSHOT_DIR, snapshot_name)
        assert os.path.exists(snapshot_path)
        
        # 验证 compress 和 upload 被调用
        assert mock_compress.called
        assert mock_upload.called

    def test_save_snapshot_with_cache(self, setup_dirs, saver):
        """测试保存带缓存的ComfyUI开发版快照"""
        snapshot_name = "test_snapshot"
        # 创建缓存文件
        with open(os.path.join(constants.WORK_DIR, ".cache/test.txt"), "w") as f:
            f.write("test cache")

        # Mock compress 和 upload 方法
        with patch.object(saver, '_compress') as mock_compress:
            with patch.object(saver, '_upload') as mock_upload:
                stage_cost = saver.save(snapshot_name)

        # 验证快照目录已创建
        snapshot_path = os.path.join(constants.SNAPSHOT_DIR, snapshot_name)
        assert os.path.exists(snapshot_path)
        
        # 验证 compress 和 upload 被调用
        assert mock_compress.called
        assert mock_upload.called
    
    def test_save_with_auto_cleanup(self, setup_dirs, saver):
        """测试启用自动清理时，清理超过限制的旧快照"""
        # 创建 4 个 dev 快照
        snapshot_prefix = "dev"
        for i in range(1, 5):
            old_name = f"{snapshot_prefix}-2026010{i}-120000"
            old_path = os.path.join(constants.SNAPSHOT_DIR, old_name)
            os.makedirs(old_path)

        # Mock compress 和 upload 方法
        with patch.object(saver, '_compress'):
            with patch.object(saver, '_upload'):
                # 保存新快照并启用自动清理，指定前缀
                new_name = f"{snapshot_prefix}-20260105-120000"
                stage_cost = saver.save(new_name, auto_cleanup=True, cleanup_prefix=snapshot_prefix, max_snapshots=3)

        # 验证只保留最新的 3 个
        remaining_snapshots = [
            d for d in os.listdir(constants.SNAPSHOT_DIR)
            if d.startswith(f"{snapshot_prefix}-")
        ]
        assert len(remaining_snapshots) == 3
        assert stage_cost["cleaned_snapshots"] == 2
    
    def test_cleanup_when_snapshots_not_exceed_limit(self, setup_dirs, saver):
        """测试快照数量未超过限制时不清理"""
        snapshot_prefix = "dev"
        # 只创建 2 个快照（少于限制 3 个）
        for i in range(1, 3):
            old_name = f"{snapshot_prefix}-2026010{i}-120000"
            os.makedirs(os.path.join(constants.SNAPSHOT_DIR, old_name))
        
        with patch.object(saver, '_compress'):
            with patch.object(saver, '_upload'):
                new_name = f"{snapshot_prefix}-20260103-120000"
                stage_cost = saver.save(new_name, auto_cleanup=True, cleanup_prefix=snapshot_prefix, max_snapshots=3)
        
        # 验证所有 3 个快照都保留
        remaining_snapshots = [
            d for d in os.listdir(constants.SNAPSHOT_DIR)
            if d.startswith(f"{snapshot_prefix}-")
        ]
        assert len(remaining_snapshots) == 3
        assert stage_cost.get("cleaned_snapshots", 0) == 0
    
    def test_cleanup_only_targets_specified_prefix(self, setup_dirs, saver):
        """测试清理只针对指定前缀的快照，不影响其他类型"""
        # 创建多个 dev 快照
        for i in range(1, 5):
            dev_name = f"dev-2026010{i}-120000"
            os.makedirs(os.path.join(constants.SNAPSHOT_DIR, dev_name))
        
        # 创建多个 prod 快照
        for i in range(1, 5):
            prod_name = f"prod-2026010{i}-120000"
            os.makedirs(os.path.join(constants.SNAPSHOT_DIR, prod_name))
        
        with patch.object(saver, '_compress'):
            with patch.object(saver, '_upload'):
                new_name = "dev-20260105-120000"
                stage_cost = saver.save(new_name, auto_cleanup=True, cleanup_prefix="dev", max_snapshots=3)
        
        # 验证 dev 快照只保留 3 个
        dev_snapshots = [d for d in os.listdir(constants.SNAPSHOT_DIR) if d.startswith("dev-")]
        assert len(dev_snapshots) == 3
        
        # 验证 prod 快照完全不受影响（仍然是 4 个）
        prod_snapshots = [d for d in os.listdir(constants.SNAPSHOT_DIR) if d.startswith("prod-")]
        assert len(prod_snapshots) == 4
        
        # 验证清理了 2 个 dev 快照
        assert stage_cost["cleaned_snapshots"] == 2
    
    def test_cleanup_when_snapshots_not_exceed_limit(self, setup_dirs, saver):
        """测试快照数量未超过限制时不清理"""
        snapshot_prefix = "dev"
        # 只创建 2 个快照（少于限制 3 个）
        old_snapshots = [
            f"{snapshot_prefix}-20260101-120000",
            f"{snapshot_prefix}-20260102-120000"
        ]
        
        for old_name in old_snapshots:
            os.makedirs(os.path.join(constants.SNAPSHOT_DIR, old_name))
        
        with patch.object(saver, '_compress'):
            with patch.object(saver, '_upload'):
                # 保存新快照（第 3 个），刚好等于限制
                new_name = f"{snapshot_prefix}-20260103-120000"
                stage_cost = saver.save(new_name, auto_cleanup=True, cleanup_prefix=snapshot_prefix, max_snapshots=3)
        
        # 验证所有 3 个快照都保留
        remaining_snapshots = [
            d for d in os.listdir(constants.SNAPSHOT_DIR)
            if d.startswith(f"{snapshot_prefix}-")
        ]
        assert len(remaining_snapshots) == 3
        
        # 验证没有清理任何快照
        assert stage_cost.get("cleaned_snapshots", 0) == 0
    
    def test_cleanup_with_different_max_snapshots(self, setup_dirs, saver):
        """测试不同的 max_snapshots 值"""
        snapshot_prefix = "dev"
        # 创建 6 个快照
        for i in range(1, 7):
            old_name = f"{snapshot_prefix}-2026010{i}-120000"
            os.makedirs(os.path.join(constants.SNAPSHOT_DIR, old_name))
        
        with patch.object(saver, '_compress'):
            with patch.object(saver, '_upload'):
                # 保存新快照，只保留最新 2 个
                new_name = f"{snapshot_prefix}-20260107-120000"
                stage_cost = saver.save(new_name, auto_cleanup=True, cleanup_prefix=snapshot_prefix, max_snapshots=2)
        
        # 验证只保留最新的 2 个
        remaining_snapshots = [
            d for d in os.listdir(constants.SNAPSHOT_DIR)
            if d.startswith(f"{snapshot_prefix}-")
        ]
        assert len(remaining_snapshots) == 2
        
        # 验证清理了 5 个旧快照（7 - 2 = 5）
        assert stage_cost["cleaned_snapshots"] == 5
        
        # 验证保留的是最新的 2 个
        assert f"{snapshot_prefix}-20260106-120000" in remaining_snapshots
        assert new_name in remaining_snapshots
    
    def test_cleanup_only_targets_specified_prefix(self, setup_dirs, saver):
        """测试清理只针对指定前缀的快照，不影响其他类型"""
        # 创建多个 dev 快照
        for i in range(1, 5):
            dev_name = f"dev-2026010{i}-120000"
            os.makedirs(os.path.join(constants.SNAPSHOT_DIR, dev_name))
        
        # 创建多个 prod 快照
        for i in range(1, 5):
            prod_name = f"prod-2026010{i}-120000"
            os.makedirs(os.path.join(constants.SNAPSHOT_DIR, prod_name))
        
        with patch.object(saver, '_compress'):
            with patch.object(saver, '_upload'):
                # 保存新的 dev 快照，只清理 dev 类型
                new_name = "dev-20260105-120000"
                stage_cost = saver.save(new_name, auto_cleanup=True, cleanup_prefix="dev", max_snapshots=3)
        
        # 验证 dev 快照只保留 3 个
        dev_snapshots = [d for d in os.listdir(constants.SNAPSHOT_DIR) if d.startswith("dev-")]
        assert len(dev_snapshots) == 3
        
        # 验证 prod 快照完全不受影响（仍然是 4 个）
        prod_snapshots = [d for d in os.listdir(constants.SNAPSHOT_DIR) if d.startswith("prod-")]
        assert len(prod_snapshots) == 4
        
        # 验证清理了 2 个 dev 快照
        assert stage_cost["cleaned_snapshots"] == 2
    
    def test_cleanup_preserves_newest_snapshots(self, setup_dirs, saver):
        """测试清理时保留的是最新的快照（按名称排序）"""
        snapshot_prefix = "dev"
        # 创建时间戳不连续的快照
        old_snapshots = [
            f"{snapshot_prefix}-20260101-120000",
            f"{snapshot_prefix}-20260205-150000",  # 2月的
            f"{snapshot_prefix}-20260103-140000",
            f"{snapshot_prefix}-20260204-130000",  # 2月的
        ]
        
        for old_name in old_snapshots:
            os.makedirs(os.path.join(constants.SNAPSHOT_DIR, old_name))
        
        with patch.object(saver, '_compress'):
            with patch.object(saver, '_upload'):
                new_name = f"{snapshot_prefix}-20260206-120000"
                stage_cost = saver.save(new_name, auto_cleanup=True, cleanup_prefix=snapshot_prefix, max_snapshots=3)
        
        remaining_snapshots = [
            d for d in os.listdir(constants.SNAPSHOT_DIR)
            if d.startswith(f"{snapshot_prefix}-")
        ]
        
        # 验证保留的是最新的 3 个（按字典序排序）
        assert len(remaining_snapshots) == 3
        assert f"{snapshot_prefix}-20260204-130000" in remaining_snapshots
        assert f"{snapshot_prefix}-20260205-150000" in remaining_snapshots
        assert new_name in remaining_snapshots
        
        # 验证最旧的被删除
        assert not os.path.exists(os.path.join(constants.SNAPSHOT_DIR, f"{snapshot_prefix}-20260101-120000"))
        assert not os.path.exists(os.path.join(constants.SNAPSHOT_DIR, f"{snapshot_prefix}-20260103-140000"))
