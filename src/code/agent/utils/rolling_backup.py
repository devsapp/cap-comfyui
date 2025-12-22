"""
文件生命周期管理工具
用于管理 serverless_api 输出目录的文件，实现滚动备份和清理
"""
import os
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

from utils.logger import log


class RollingBackup:
    """文件滚动备份管理器"""
    
    def __init__(
        self,
        source_dir: Optional[str] = None,
        archived_dir: Optional[str] = None,
        source_keep_count: int = 1000,
        source_keep_days: int = 1,
        archived_keep_days: int = 5
    ):
        """
        初始化滚动备份管理器
        
        Args:
            source_dir: 源目录路径，默认为 ${MNT_DIR}/output/serverless_api
            archived_dir: 归档目录路径，默认为 ${MNT_DIR}/output/serverless_api_archived
            source_keep_count: 源目录最多保留的文件数量
            source_keep_days: 源目录保留时间（天），超过此时间的文件会被移动到归档目录
            archived_keep_days: 归档目录保留时间（天），超过此时间的文件会被删除
        """
        from constants import MNT_DIR
        
        self.mnt_dir = MNT_DIR
        self.source_dir = Path(source_dir) if source_dir else Path(MNT_DIR) / "output" / "serverless_api"
        self.archived_dir = Path(archived_dir) if archived_dir else Path(MNT_DIR) / "output" / "serverless_api_archived"
        self.source_keep_count = source_keep_count
        self.source_keep_days = source_keep_days
        self.archived_keep_days = archived_keep_days
        
        # 确保目录存在
        self.source_dir.mkdir(parents=True, exist_ok=True)
        self.archived_dir.mkdir(parents=True, exist_ok=True)
    
    def run(self) -> dict:
        """
        执行完整的生命周期管理流程
        
        Returns:
            dict: 执行结果统计
        """
        import time as time_module
        start_time = time_module.time()
        
        log("INFO", f"Starting rolling backup: source={self.source_dir}, archived={self.archived_dir}")
        
        try:
            # 1. 移除serverless_api目录下超过时间阈值的文件
            step_start = time_module.time()
            moved_by_time, moved_by_count, source_count = self._move_old_files_optimized()
            step_elapsed = time_module.time() - step_start
            log("INFO", f"Step 1 - Move old files: {step_elapsed:.2f}s (moved: {moved_by_time + moved_by_count})")
            
            # 2. 清理archived目录中的过期文件（同时统计文件数，避免重复遍历）
            step_start = time_module.time()
            deleted_count, archived_count = self._clean_archived()
            step_elapsed = time_module.time() - step_start
            log("INFO", f"Step 2 - Clean archived: {step_elapsed:.2f}s (deleted: {deleted_count}, remaining: {archived_count})")
            
            elapsed = time_module.time() - start_time
            result = {
                "moved_by_time": moved_by_time,
                "moved_by_count": moved_by_count,
                "deleted_from_archived": deleted_count,
                "source_file_count": source_count,
                "archived_file_count": archived_count,
                "elapsed_seconds": round(elapsed, 2)
            }
            
            log("INFO", f"Rolling backup complete in {elapsed:.2f}s. "
                f"Source: {source_count} files, Archived: {archived_count} files")
            
            return result
            
        except Exception as e:
            log("ERROR", f"Error during rolling backup: {str(e)}")
    
    def _move_old_files_optimized(self) -> Tuple[int, int, int]:
        """        
        移除serverless_api目录下超过时间阈值的文件
        
        Args:
            self: 滚动备份管理器实例
            
        Returns:
            tuple[int, int, int]: (按时间移动的数量, 按数量移动的数量, 源目录剩余文件数)
        """
        moved_by_time = 0
        moved_by_count = 0
        # retention_threshold: 保留时间阈值，更新时间早于此时间的文件需要移动到归档目录
        # 例如：如果 source_keep_days=1，则 retention_threshold = 当前时间 - 1天
        # 文件的 mtime < retention_threshold 表示文件已经超过保留时间
        retention_threshold = time.time() - (self.source_keep_days * 24 * 60 * 60)
        
        try:
            import time as time_module
            
            # 一次性获取所有文件及其修改时间 - 使用高性能的scandir
            step_start = time_module.time()
            files_to_move_by_time = []
            remaining_files_with_mtime = []  # 不超过时间阈值的文件（需要检查数量）
            
            for entry in os.scandir(self.source_dir):
                if entry.is_file():
                    try: 
                        stat_info = entry.stat()
                        mtime = stat_info.st_mtime
                        entry_path = entry.path
                        file_path = Path(entry_path)
                        
                        if mtime < retention_threshold:
                            # 超过保留时间阈值，需要移动
                            files_to_move_by_time.append(file_path)
                        else:
                            # 不超过时间阈值，需要检查数量
                            remaining_files_with_mtime.append((mtime, file_path))
                    except (OSError, PermissionError):
                        # 文件可能已被删除或权限不足，跳过该文件
                        continue
            
            scan_elapsed = time_module.time() - step_start
            total_files = len(files_to_move_by_time) + len(remaining_files_with_mtime)
            log("INFO", f"  - Scan directory: {scan_elapsed:.2f}s ({total_files} files)")
            
            # 批量移动超过时间阈值的文件
            if files_to_move_by_time:
                step_start = time_module.time()
                moved_by_time = self._batch_move_files(files_to_move_by_time)
                move_elapsed = time_module.time() - step_start
                log("INFO", f"  - Move by time: {move_elapsed:.2f}s ({moved_by_time} files, {moved_by_time/move_elapsed:.0f} files/s, older than {self.source_keep_days} days)")
            
            # 检查剩余文件数量，如果仍然超过限制，按时间排序移动
            # 计算剩余文件数（移动前）
            source_count = len(remaining_files_with_mtime)
            
            if len(remaining_files_with_mtime) > self.source_keep_count:
                # 按修改时间排序（最新的在前）
                remaining_files_with_mtime.sort(key=lambda x: x[0], reverse=True)
                sort_elapsed = time_module.time() - step_start
                log("INFO", f"  - Sort files: {sort_elapsed:.2f}s")
                
                # 移动超出的文件
                step_start = time_module.time()
                files_to_move_by_count = [f for _, f in remaining_files_with_mtime[self.source_keep_count:]]
                moved_by_count = self._batch_move_files(files_to_move_by_count)
                move_elapsed = time_module.time() - step_start
                log("INFO", f"  - Move by count: {move_elapsed:.2f}s ({moved_by_count} files, {moved_by_count/move_elapsed:.0f} files/s)")
                
                # 更新剩余文件数
                source_count = self.source_keep_count
            else:
                log("INFO", f"  - No files to move by count (remaining: {source_count} <= limit: {self.source_keep_count})")
            
        except Exception as e:
            log("ERROR", f"Error moving old files: {str(e)}")
            source_count = 0
        
        return moved_by_time, moved_by_count, source_count
    
    def _batch_move_files(self, files: list) -> int:
        """
        批量移动文件
        
        Args:
            files: 要移动的文件路径列表
            
        Returns:
            int: 成功移动的文件数量
        """
        if not files:
            return 0
        
        moved_count = 0
        failed_count = 0
        
        for file_path in files:
            try:
                dest_path = self.archived_dir / file_path.name
                # 先尝试 os.rename（同一文件系统，更快）
                # 如果失败（跨文件系统），fallback 到 shutil.move
                try:
                    os.rename(str(file_path), str(dest_path))
                    moved_count += 1
                except OSError:
                    # 跨文件系统，使用 shutil.move
                    try:
                        shutil.move(str(file_path), str(dest_path))
                        moved_count += 1
                    except Exception:
                        failed_count += 1
            except Exception:
                failed_count += 1
        
        # 只在有失败时记录警告
        if failed_count > 0:
            log("WARNING", f"Failed to move {failed_count} file(s)")
        
        return moved_count
    
    def _clean_archived(self) -> Tuple[int, int]:
        """
        清理归档目录中超过保留时间的文件
        同时统计剩余文件数，避免重复遍历
        
        Returns:
            tuple[int, int]: (删除的文件数量, 剩余文件数量)
        """
        deleted_count = 0
        total_files = 0
        # retention_threshold: 保留时间阈值，修改时间早于此时间的归档文件需要删除
        # 例如：如果 archived_keep_days=5，则 retention_threshold = 当前时间 - 5天
        # 文件的 mtime < retention_threshold 表示文件已经超过归档保留时间
        retention_threshold = time.time() - (self.archived_keep_days * 24 * 60 * 60)
        files_to_delete = []
        
        try:
            # 遍历归档目录，同时收集需要删除的文件和统计文件总数
            for entry in os.scandir(self.archived_dir):
                if entry.is_file():
                    total_files += 1
                    try:
                        stat_info = entry.stat()
                        mtime = stat_info.st_mtime
                        if mtime < retention_threshold:
                            files_to_delete.append(Path(entry.path))
                    except (OSError, PermissionError) as e:
                        log("DEBUG", f"Failed to stat file {entry.name}: {str(e)}")
                        continue
            
            # 批量删除
            for file_path in files_to_delete:
                try:
                    file_path.unlink()
                    deleted_count += 1
                except Exception as e:
                    log("DEBUG", f"Failed to delete file {file_path.name}: {str(e)}")
            
            # 计算剩余文件数
            remaining_count = total_files - deleted_count
            
            if deleted_count > 0:
                log("INFO", f"Deleted {deleted_count} file(s) older than {self.archived_keep_days} days from archived")
            
        except Exception as e:
            log("ERROR", f"Error cleaning archived: {str(e)}")
            remaining_count = 0
        
        return deleted_count, remaining_count


def main():
    """命令行入口"""
    import sys
    
    # 支持从环境变量读取配置
    source_keep_count = int(os.getenv("SOURCE_KEEP_COUNT", "1000"))
    source_keep_days = int(os.getenv("SOURCE_KEEP_DAYS", "1"))
    archived_keep_days = int(os.getenv("ARCHIVED_KEEP_DAYS", "5"))
    
    backup = RollingBackup(
        source_keep_count=source_keep_count,
        source_keep_days=source_keep_days,
        archived_keep_days=archived_keep_days
    )
    
    try:
        result = backup.run()
        log("INFO", f"Rolling backup completed: {result}")
        sys.exit(0)
    except Exception as e:
        log("ERROR", f"Rolling backup failed: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()

