#!/usr/bin/env python3
"""
测试 rolling_backup 性能
"""
import os
import sys
import time
import tempfile
import shutil
from pathlib import Path

# 添加 agent 目录到路径（从 test/unit/utils 目录向上找到 agent 目录）
current_dir = Path(__file__).parent
agent_dir = current_dir.parent.parent.parent
sys.path.insert(0, str(agent_dir))

# 设置环境变量，避免依赖 constants
os.environ['MODEL_ASSET_DIR'] = '/tmp'

from utils.rolling_backup import RollingBackup


def test_rolling_backup_performance():
    """测试 RollingBackup 性能"""
    temp_base = Path(tempfile.mkdtemp(prefix="rolling_backup_test_"))
    source_dir = temp_base / "output" / "serverless_api"
    archived_dir = temp_base / "output" / "serverless_api_archived"
    
    print("=" * 60)
    print("Rolling Backup 性能测试 (3万文件)")
    print("=" * 60)
    print(f"测试目录: {temp_base}")
    print(f"源目录: {source_dir}")
    print(f"归档目录: {archived_dir}")
    print()
    
    try:
        # 创建 30000 个测试文件
        file_count = 30000
        print(f"正在创建 {file_count} 个测试文件...")
        start_time = time.time()
        
        source_dir.mkdir(parents=True, exist_ok=True)
        archived_dir.mkdir(parents=True, exist_ok=True)
        
        for i in range(file_count):
            file_path = source_dir / f"test_file_{i:06d}.txt"
            file_path.write_text(f"Test file content {i}\n" * 10)
            
            # 前 1000 个是新的，其余是旧的（2天前）
            if i >= 1000:
                old_time = time.time() - (2 * 24 * 60 * 60)
                os.utime(file_path, (old_time, old_time))
        
        create_elapsed = time.time() - start_time
        print(f"创建完成，耗时: {create_elapsed:.2f} 秒")
        print(f"平均每个文件: {create_elapsed/file_count*1000:.2f} 毫秒")
        print()
        
        # 验证文件数量
        step_start = time.time()
        actual_count = sum(1 for _ in source_dir.iterdir() if _.is_file())
        count_elapsed = time.time() - step_start
        print(f"实际创建文件数: {actual_count} (验证耗时: {count_elapsed:.3f}秒)")
        print()
        
        # 使用 RollingBackup 进行测试
        print("开始执行 RollingBackup...")
        print("-" * 60)
        
        backup = RollingBackup(
            source_dir=str(source_dir),
            archived_dir=str(archived_dir),
            source_keep_count=1000,
            source_keep_days=1,  # 1天
            archived_keep_days=5
        )
        
        start_time = time.time()
        result = backup.run()
        elapsed = time.time() - start_time
        
        print("-" * 60)
        print()
        
        # 输出结果
        print("=" * 60)
        print("测试结果")
        print("=" * 60)
        print(f"总耗时: {elapsed:.2f} 秒")
        print(f"按时间移动: {result['moved_by_time']} 个文件")
        print(f"按数量移动: {result['moved_by_count']} 个文件")
        print(f"删除归档文件: {result['deleted_from_archived']} 个文件")
        print(f"源目录剩余: {result['source_file_count']} 个文件")
        print(f"归档目录文件: {result['archived_file_count']} 个文件")
        print()
        
        # 性能指标
        total_processed = result['moved_by_time'] + result['moved_by_count']
        if total_processed > 0:
            avg_time_per_file = elapsed / total_processed * 1000
            print(f"处理文件总数: {total_processed}")
            print(f"平均每个文件耗时: {avg_time_per_file:.2f} 毫秒")
            print(f"处理速度: {total_processed/elapsed:.0f} 文件/秒")
        
        # 验证结果
        print()
        print("=" * 60)
        print("验证结果")
        print("=" * 60)
        if result['source_file_count'] <= backup.source_keep_count:
            print(f"✓ 源目录文件数 ({result['source_file_count']}) <= 限制 ({backup.source_keep_count})")
        else:
            print(f"✗ 源目录文件数 ({result['source_file_count']}) > 限制 ({backup.source_keep_count})")
        
        print(f"✓ 总文件数: {result['source_file_count'] + result['archived_file_count']} (原始: {actual_count})")
        
    finally:
        # 清理测试文件
        print()
        print("=" * 60)
        print("清理测试文件...")
        try:
            shutil.rmtree(temp_base)
            print(f"已删除测试目录: {temp_base}")
        except Exception as e:
            print(f"清理失败: {e}")
            print(f"请手动删除: {temp_base}")


if __name__ == "__main__":
    test_rolling_backup_performance()

