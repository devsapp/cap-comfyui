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
        history_dir: Optional[str] = None,
        source_keep_count: int = 1,
        source_keep_minutes: int = 5,  # 24小时 = 1440分钟
        history_keep_days: int = 1
    ):
        """
        初始化滚动备份管理器
        
        Args:
            source_dir: 源目录路径，默认为 ${MNT_DIR}/output/serverless_api
            history_dir: 历史目录路径，默认为 ${MNT_DIR}/output/serverless_api_archived
            source_keep_count: 源目录最多保留的文件数量
            source_keep_minutes: 源目录保留时间（分钟），超过此时间的文件会被移动到历史目录
            history_keep_days: 历史目录保留时间（天），超过此时间的文件会被删除
        """
        from constants import MNT_DIR
        
        self.mnt_dir = MNT_DIR
        self.source_dir = Path(source_dir) if source_dir else Path(MNT_DIR) / "output" / "serverless_api"
        self.history_dir = Path(history_dir) if history_dir else Path(MNT_DIR) / "output" / "serverless_api_archived"
        self.source_keep_count = source_keep_count
        self.source_keep_minutes = source_keep_minutes
        self.history_keep_days = history_keep_days
        
        # 确保目录存在
        self.source_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)
    
    def run(self) -> dict:
        """
        执行完整的生命周期管理流程
        
        Returns:
            dict: 执行结果统计
        """
        import time as time_module
        start_time = time_module.time()
        
        log("INFO", f"Starting rolling backup: source={self.source_dir}, history={self.history_dir}")
        
        try:
            # 优化：合并移动操作，只遍历一次文件列表
            moved_by_time, moved_by_count = self._move_old_files_optimized()
            
            # 清理历史目录中的过期文件
            deleted_count = self._clean_history()
            
            # 统计结果（只统计文件，不包括目录）
            source_count = len([f for f in self.source_dir.iterdir() if f.is_file()])
            history_count = len([f for f in self.history_dir.iterdir() if f.is_file()])
            
            elapsed = time_module.time() - start_time
            result = {
                "moved_by_time": moved_by_time,
                "moved_by_count": moved_by_count,
                "deleted_from_history": deleted_count,
                "source_file_count": source_count,
                "history_file_count": history_count,
                "elapsed_seconds": round(elapsed, 2)
            }
            
            log("INFO", f"Lifecycle management complete in {elapsed:.2f}s. "
                f"Source: {source_count} files, History: {history_count} files")
            
            return result
            
        except Exception as e:
            log("ERROR", f"Error during rolling backup: {str(e)}")
            raise
    
    def _move_old_files_optimized(self) -> Tuple[int, int]:
        """
        优化版本：合并时间阈值和数量限制的移动操作，只遍历一次文件列表
        
        Returns:
            tuple[int, int]: (按时间移动的数量, 按数量移动的数量)
        """
        moved_by_time = 0
        moved_by_count = 0
        cutoff_time = time.time() - (self.source_keep_minutes * 60)
        
        try:
            # 一次性获取所有文件及其修改时间
            files_with_mtime = []
            files_to_move_by_time = []
            files_to_move_by_time_set = set()  # 用于快速查找
            
            for file_path in self.source_dir.iterdir():
                if file_path.is_file():
                    try:
                        mtime = file_path.stat().st_mtime
                        files_with_mtime.append((mtime, file_path))
                        
                        # 检查是否超过时间阈值
                        if mtime < cutoff_time:
                            files_to_move_by_time.append(file_path)
                            files_to_move_by_time_set.add(file_path)
                    except (OSError, PermissionError) as e:
                        log("WARNING", f"Failed to stat file {file_path.name}: {str(e)}")
                        continue
            
            # 批量移动超过时间阈值的文件
            if files_to_move_by_time:
                moved_by_time = self._batch_move_files(files_to_move_by_time)
                if moved_by_time > 0:
                    log("INFO", f"Moved {moved_by_time} file(s) older than {self.source_keep_minutes} minutes to history")
            
            # 检查剩余文件数量，如果仍然超过限制，按时间排序移动
            # 使用 set 查找，避免重复 stat
            remaining_files_with_mtime = [(mtime, f) for mtime, f in files_with_mtime if f not in files_to_move_by_time_set]
            
            if len(remaining_files_with_mtime) > self.source_keep_count:
                # 按修改时间排序（最新的在前）
                remaining_files_with_mtime.sort(key=lambda x: x[0], reverse=True)
                
                # 移动超出的文件
                files_to_move_by_count = [f for _, f in remaining_files_with_mtime[self.source_keep_count:]]
                moved_by_count = self._batch_move_files(files_to_move_by_count)
                
                if moved_by_count > 0:
                    log("INFO", f"Moved {moved_by_count} file(s) to history (keeping {self.source_keep_count} newest)")
            
        except Exception as e:
            log("ERROR", f"Error moving old files: {str(e)}")
        
        return moved_by_time, moved_by_count
    
    def _batch_move_files(self, files: list) -> int:
        """
        批量移动文件（优化性能）
        
        Args:
            files: 要移动的文件路径列表
            
        Returns:
            int: 成功移动的文件数量
        """
        moved_count = 0
        
        # 使用 os.rename 代替 shutil.move，在同一文件系统上更快
        # 如果跨文件系统，fallback 到 shutil.move
        for file_path in files:
            try:
                dest_path = self.history_dir / file_path.name
                # 尝试使用 os.rename（更快，但要求同一文件系统）
                try:
                    os.rename(str(file_path), str(dest_path))
                except OSError:
                    # 跨文件系统，使用 shutil.move
                    shutil.move(str(file_path), str(dest_path))
                moved_count += 1
            except Exception as e:
                log("WARNING", f"Failed to move file {file_path.name}: {str(e)}")
        
        return moved_count
    
    def _clean_history(self) -> int:
        """
        清理历史目录中超过保留时间的文件（优化版本）
        
        Returns:
            int: 删除的文件数量
        """
        deleted_count = 0
        cutoff_time = time.time() - (self.history_keep_days * 24 * 60 * 60)
        files_to_delete = []
        
        try:
            # 先收集需要删除的文件
            for file_path in self.history_dir.iterdir():
                if file_path.is_file():
                    try:
                        mtime = file_path.stat().st_mtime
                        if mtime < cutoff_time:
                            files_to_delete.append(file_path)
                    except (OSError, PermissionError) as e:
                        log("WARNING", f"Failed to stat file {file_path.name}: {str(e)}")
                        continue
            
            # 批量删除
            for file_path in files_to_delete:
                try:
                    file_path.unlink()
                    deleted_count += 1
                except Exception as e:
                    log("WARNING", f"Failed to delete file {file_path.name}: {str(e)}")
            
            if deleted_count > 0:
                log("INFO", f"Deleted {deleted_count} file(s) older than {self.history_keep_days} days from history")
            
        except Exception as e:
            log("ERROR", f"Error cleaning history: {str(e)}")
        
        return deleted_count


def main():
    """命令行入口"""
    import sys
    
    # 支持从环境变量读取配置
    source_keep_count = int(os.getenv("SOURCE_KEEP_COUNT", "1000"))
    source_keep_minutes = int(os.getenv("SOURCE_KEEP_MINUTES", "1440"))
    history_keep_days = int(os.getenv("HISTORY_KEEP_DAYS", "5"))
    
    backup = RollingBackup(
        source_keep_count=source_keep_count,
        source_keep_minutes=source_keep_minutes,
        history_keep_days=history_keep_days
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

