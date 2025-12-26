"""
文件生命周期管理工具
用于管理 serverless_api 输出目录的文件，实现文件归档和清理
"""
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Optional

from utils.logger import log


class OutputFileCleanupService:
    """文件清理服务：管理 serverless_api 输出文件的生命周期（归档和清理）"""
    
    def __init__(
        self,
        source_dir: Optional[str] = None,
        archived_dir: Optional[str] = None,
        max_files: int = 1000,
        ttl_seconds: int = 24 * 60 * 60,  # 24小时
        archived_ttl_seconds: int = 5 * 24 * 60 * 60,  # 5天
    ):
        """
        初始化文件清理服务
        
        Args:
            source_dir: 源目录路径，默认为 ${MNT_DIR}/output/serverless_api
            archived_dir: 归档目录路径，默认为 ${MNT_DIR}/output/serverless_api_archived
            max_files: 源目录最多保留的文件数量
            ttl_seconds: 源目录保留时间（秒），超过此时间的文件会被移动到归档目录
            archived_ttl_seconds: 归档目录保留时间（秒），超过此时间的文件会被删除
        """
        from constants import MNT_DIR
        
        self.mnt_dir = MNT_DIR
        self.source_dir = Path(source_dir) if source_dir else Path(MNT_DIR) / "output" / "serverless_api"
        self.archived_dir = Path(archived_dir) if archived_dir else Path(MNT_DIR) / "output" / "serverless_api_archived"
        self.max_files = max_files
        self.ttl_seconds = ttl_seconds
        self.archived_ttl_seconds = archived_ttl_seconds
        self._cancel_event = threading.Event()
        
        # 确保目录存在
        self.source_dir.mkdir(parents=True, exist_ok=True)
        self.archived_dir.mkdir(parents=True, exist_ok=True)
    
    def cleanup(self, clean_archived: bool = True):
        """
        执行文件清理

        Args:
            clean_archived: 是否清理归档目录，默认为 True
        """
        # 重置取消标志
        self._cancel_event.clear()
        
        log("INFO", f"Start to clean up output files: source={self.source_dir}, archived={self.archived_dir}, clean_archived={clean_archived}")
        
        try:
            # 1. 移除serverless_api目录下超过时间阈值的文件
            self._archive(self._cancel_event)
            
            # 2. 清理archived目录中的过期文件（可选）
            if clean_archived and not self._cancel_event.is_set():
                self._cleanup_archived()
            
        except Exception as e:
            log("DEBUG", f"文件清理过程中出错: {str(e)}")
    
    def cancel(self):
        """
        取消正在执行的清理操作
        """
        log("INFO", "Canceling cleanup operation")
        self._cancel_event.set()
    
    def _archive(self, cancel_event: threading.Event = None):
        """        
        将serverless_api目录下超过时间阈值的文件移动到归档目录
        
        Args:
            cancel_event: 取消事件，用于检查是否需要中止操作
        """
        # expire_time: 文件过期时间点，修改时间早于此时间的文件需要移动到归档目录
        # 例如：如果 ttl_seconds=86400（1天），则 expire_time = 当前时间 - 86400秒
        # 文件的 mtime < expire_time 表示文件已经过期
        expire_time = time.time() - self.ttl_seconds
        
        try:
            # 一次性获取所有文件及其修改时间 - 使用高性能的scandir
            step_start = time.time()
            expired_files = []
            remaining_files = []  # 未过期的文件（需要检查数量限制）
            
            for item in os.scandir(self.source_dir):
                if item.is_file():
                    try: 
                        stat_info = item.stat()
                        mtime = stat_info.st_mtime
                        item_path = item.path
                        file_path = Path(item_path)
                        
                        if mtime < expire_time:
                            # 文件已过期，需要移动到归档目录
                            expired_files.append(file_path)
                        else:
                            # 文件未过期，需要检查数量限制
                            remaining_files.append((mtime, file_path))
                    except Exception as e:
                        log("DEBUG", f"Failed to process file {item.path}: {type(e).__name__}: {str(e)}")
                        continue
            
            scan_elapsed = time.time() - step_start
            total_files = len(expired_files) + len(remaining_files)
            log("DEBUG", f"Scan directory: {scan_elapsed:.2f}s ({total_files} files)")
            
            # 批量移动过期文件
            if expired_files:
                self._batch_move_files(expired_files, cancel_event)
            
            # 检查剩余文件数量，如果仍然超过限制，按时间排序移动
            if len(remaining_files) > self.max_files:
                # 按修改时间排序（最新的在前）
                remaining_files.sort(key=lambda x: x[0], reverse=True)
                
                # 移动超出的文件
                files_to_move_by_count = [f for _, f in remaining_files[self.max_files:]]
                self._batch_move_files(files_to_move_by_count, cancel_event)
            
        except Exception as e:
            log("DEBUG", f"Error moving old files: {type(e).__name__}: {str(e)}")
    
    def _batch_move_files(self, files: list, cancel_event: threading.Event = None):
        """
        批量移动文件到归档目录
        
        Args:
            files: 要移动的文件路径列表
            cancel_event: 取消事件，如果设置了则终止执行
        """
        if not files:
            return

        for file_path in files:
            if cancel_event and cancel_event.is_set():
                return
                
            dest_path = self.archived_dir / file_path.name
            
            # 处理文件名冲突：如果目标文件已存在，先删除（覆盖策略）
            if dest_path.exists():
                try:
                    os.remove(str(dest_path))
                except Exception as e:
                    log("DEBUG", f"Failed to remove file {dest_path}: {type(e).__name__}: {str(e)}")
                    continue
            
            if not file_path.exists():
                continue
            
            # 先尝试 os.rename（同一文件系统，更快）
            # 如果失败（跨文件系统或其他错误），fallback 到 shutil.move
            try:
                os.rename(str(file_path), str(dest_path))
            except FileNotFoundError:
                # 文件在移动过程中被删除，静默跳过（NFS TOCTOU 问题）
                continue
            except Exception as e:
                # 跨文件系统或其他错误，使用 shutil.move
                try:
                    shutil.move(str(file_path), str(dest_path))
                except FileNotFoundError:
                    # 文件在移动过程中被删除，静默跳过（NFS TOCTOU 问题）
                    continue
                except Exception as e2:
                    log("DEBUG", f"Failed to archive file {file_path} to {dest_path}: os.rename failed ({type(e).__name__}: {str(e)}), shutil.move also failed ({type(e2).__name__}: {str(e2)})")

    def _cleanup_archived(self):
        """
        清理归档目录中超过保留时间的文件
        """
        # expire_time: 归档文件过期时间点，修改时间早于此时间的归档文件需要删除
        # 例如：如果 archived_ttl_seconds=432000（5天），则 expire_time = 当前时间 - 432000秒
        # 文件的 mtime < expire_time 表示归档文件已经过期
        expire_time = time.time() - self.archived_ttl_seconds
        files_to_delete = []
        
        try:
            # 遍历归档目录，收集需要删除的文件
            for item in os.scandir(self.archived_dir):
                if item.is_file():
                    try:
                        stat_info = item.stat()
                        mtime = stat_info.st_mtime
                        if mtime < expire_time:
                            files_to_delete.append(Path(item.path))
                    except (OSError, PermissionError) as e:
                        log("DEBUG", f"Failed to stat file {item.path}: {type(e).__name__}: {str(e)}")
                        continue
            
            # 批量删除
            for file_path in files_to_delete:
                try:
                    os.remove(str(file_path))
                except Exception as e:
                    log("DEBUG", f"Failed to delete file {file_path}: {type(e).__name__}: {str(e)}")
            
        except Exception as e:
            log("DEBUG", f"Error cleaning archived: {type(e).__name__}: {str(e)}")

