"""
模型目录双向同步监听模块

实现了 ComfyUI 模型目录与用户存储目录之间的双向自动同步机制，确保两个目录中的模型文件保持一致。

1. ComfyUI 目录监听（ComfyUIModelDirWatcher）
监听 ComfyUI 的模型目录（/root/comfyui/models），当用户在 ComfyUI 中下载或添加新模型时：
- 文件创建：检测到新增的实体文件后，等待文件稳定（下载完成），移动到用户模型目录（/mnt/auto/models），
  并在原位置创建软链接指向用户目录，确保 ComfyUI 仍能正常访问
- 文件变化：如果文件正在下载或写入过程中发生修改，更新文件的最后修改时间，重新计算稳定性等待时间，
  避免处理未完成的文件
- 文件删除：如果文件在处理前被删除，从待处理队列中移除，不再进行同步


2. 用户模型目录监听（UserModelDirPoller）
（如 /mnt/auto/models），当用户在外部上传或修改模型时：
- 使用定时轮询机制扫描目录（NFS 网络存储不支持 inotify）
- 检测新增、修改或删除的文件
- 在 ComfyUI 目录创建/更新/删除对应的软链接

"""

import os
import time
import threading
import constants

from typing import Optional, Dict
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from utils.logger import log


# 配置常量
# 忽略的文件模式（临时文件、下载中的文件）
IGNORE_PATTERNS = {
    '*.tmp', '*.temp', '*.incomplete', '*.part', '*.download',
    '*.crdownload', '*.lock', '.DS_Store', 'Thumbs.db'
}

# 忽略的目录模式
IGNORE_DIRS = {'.locks', '.cache', '.git', '__pycache__'}

# 文件稳定性检查配置
STABILITY_TIMEOUT = 5  # 文件必须5秒内无变化才处理（秒）
STABILITY_CHECK_INTERVAL = 2  # 每2秒检查一次稳定性（秒）

# 用户目录轮询配置
USER_DIR_POLL_INTERVAL = 30  # 扫描间隔（秒）


class ComfyUIModelDirWatcher:
    """ComfyUI 模型目录监听器
    
    监听 /root/comfyui/models 目录，将新增的实体文件同步到用户目录
    """
    
    def __init__(self, comfyui_models_dir: str, user_models_dir: str):
        """
        初始化 ComfyUI 目录监听器
        
        Args:
            comfyui_models_dir: ComfyUI 模型目录（如 /root/comfyui/models）
            user_models_dir: 用户模型目录（如 /mnt/auto/models）
        """
        self.comfyui_models_dir = comfyui_models_dir
        self.user_models_dir = user_models_dir
        
        # watchdog observer
        self.observer = Observer()
        
        # 待处理文件队列：{file_path: last_modified_time}
        self.pending_files: Dict[str, float] = {}
        self.pending_lock = threading.Lock()
        
        # 后台处理线程
        self.processor_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.is_running = False
    
    def start(self) -> None:
        """启动监听"""
        if self.is_running:
            log("WARNING", "ComfyUIModelDirWatcher is already running")
            return
        
        if not os.path.isdir(self.comfyui_models_dir):
            log("WARNING", f"ComfyUI models directory does not exist: {self.comfyui_models_dir}")
            return
        
        log("INFO", f"Starting ComfyUI directory watcher: {self.comfyui_models_dir}")
        
        # 1. 创建事件处理器
        handler = self._ComfyUIEventHandler(
            comfyui_models_dir=self.comfyui_models_dir,
            pending_files=self.pending_files,
            pending_lock=self.pending_lock
        )
        
        # 2. 启动 watchdog observer
        self.observer.schedule(handler, self.comfyui_models_dir, recursive=True)
        self.observer.start()
        
        # 3. 启动后台处理线程
        self.stop_event.clear()
        self.processor_thread = threading.Thread(
            target=self._background_processor,
            daemon=True,
            name="ComfyUIWatcherProcessor"
        )
        self.processor_thread.start()
        
        self.is_running = True
        log("INFO", "ComfyUI directory watcher started")
    
    def stop(self) -> None:
        """停止监听"""
        if not self.is_running:
            return
        
        log("INFO", "Stopping ComfyUI directory watcher...")
        
        # 停止后台处理线程
        self.stop_event.set()
        if self.processor_thread:
            self.processor_thread.join(timeout=5)
        
        # 停止 watchdog observer
        self.observer.stop()
        self.observer.join(timeout=5)
        
        self.is_running = False
        log("INFO", "ComfyUI directory watcher stopped")
    
    def _background_processor(self) -> None:
        """后台处理待处理文件队列"""
        log("DEBUG", "ComfyUI watcher processor thread started")
        
        while not self.stop_event.is_set():
            try:
                self._process_pending_files()
            except Exception as e:
                log("ERROR", f"ComfyUI watcher processor error: {e}")
            
            # 每隔一段时间检查一次
            self.stop_event.wait(STABILITY_CHECK_INTERVAL)
        
        log("DEBUG", "ComfyUI watcher processor thread stopped")
    
    def _process_pending_files(self) -> None:
        """处理待处理文件队列"""
        now = time.time()
        stable_files = []
        
        with self.pending_lock:
            for file_path, last_modified in list(self.pending_files.items()):
                # 检查文件是否已稳定
                if now - last_modified > STABILITY_TIMEOUT:
                    # 验证文件是否真的稳定
                    if self._verify_file_stable(file_path):
                        stable_files.append(file_path)
                        del self.pending_files[file_path]
        
        # 处理稳定的文件
        for file_path in stable_files:
            try:
                self._sync_to_user_dir(file_path)
            except Exception as e:
                log("ERROR", f"Failed to sync file to user directory: {file_path}, error: {e}")
    
    def _verify_file_stable(self, file_path: str) -> bool:
        """验证文件是否稳定（不再变化）"""
        if not os.path.exists(file_path):
            log("DEBUG", f"File no longer exists, removing from queue: {file_path}")
            return False
        
        # 检查文件是否被占用
        if self._is_file_in_use(file_path):
            log("DEBUG", f"File is in use, will retry later: {os.path.basename(file_path)}")
            return False
        
        # 检查文件大小是否稳定
        try:
            size1 = os.path.getsize(file_path)
            time.sleep(0.5)
            size2 = os.path.getsize(file_path)
            
            if size1 != size2:
                log("DEBUG", f"File size still changing, will retry later: {os.path.basename(file_path)}")
                return False
                
        except OSError:
            return False
        
        return True
    
    def _is_file_in_use(self, file_path: str) -> bool:
        """检查文件是否被其他进程占用"""
        try:
            # 尝试以独占模式打开文件
            with open(file_path, 'rb') as f:
                pass
            return False
        except (IOError, OSError, PermissionError):
            return True
    
    def _sync_to_user_dir(self, source_path: str) -> None:
        """将 ComfyUI 模型目录中的文件同步到用户目录"""
        try:
            # 如果已经是软链接，跳过（可能已经被处理过）
            if os.path.islink(source_path):
                log("DEBUG", f"File is already a symlink, skipping: {source_path}")
                return
            
            # 规范化路径（解析符号链接），避免 macOS 上 /var -> /private/var 导致的路径问题
            normalized_source = os.path.realpath(source_path)
            normalized_base = os.path.realpath(self.comfyui_models_dir)
            
            # 计算相对路径
            rel_path = os.path.relpath(normalized_source, normalized_base)
            target_path = os.path.join(self.user_models_dir, rel_path)
            
            # 确保目标目录存在
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            
            # 移动文件到用户目录
            import shutil
            shutil.move(source_path, target_path)
            
            # 创建软链接
            os.symlink(target_path, source_path)
            
            log("INFO", f"File synced to user directory: {rel_path}")
            
        except Exception as e:
            log("ERROR", f"Failed to sync file to user directory: {e}")
            raise
    
    class _ComfyUIEventHandler(FileSystemEventHandler):
        """ComfyUI 目录事件处理器"""
        
        def __init__(
            self,
            comfyui_models_dir: str,
            pending_files: Dict[str, float],
            pending_lock: threading.Lock
        ):
            super().__init__()
            self.comfyui_models_dir = comfyui_models_dir
            self.pending_files = pending_files
            self.pending_lock = pending_lock
        
        def on_created(self, event: FileSystemEvent) -> None:
            """文件创建事件"""
            if event.is_directory:
                return
            
            file_path = event.src_path
            
            # 过滤：忽略临时文件和不关心的文件
            if self._should_ignore(file_path):
                log("DEBUG", f"Ignoring file: {os.path.basename(file_path)}")
                return
            
            # 检查是否是实体文件（不是软链接）
            if not os.path.islink(file_path):
                # 实体文件 → 加入待处理队列
                with self.pending_lock:
                    self.pending_files[file_path] = time.time()
                log("DEBUG", f"New real file detected, adding to pending queue: {os.path.basename(file_path)}")
        
        def on_deleted(self, event: FileSystemEvent) -> None:
            """文件删除事件"""
            if event.is_directory:
                return
            
            file_path = event.src_path
            
            # 如果文件在待处理队列中，移除
            with self.pending_lock:
                if file_path in self.pending_files:
                    del self.pending_files[file_path]
                    log("DEBUG", f"File deleted, removing from queue: {os.path.basename(file_path)}")
        
        def on_modified(self, event: FileSystemEvent) -> None:
            """文件修改事件"""
            if event.is_directory:
                return
            
            file_path = event.src_path
            
            # 如果文件在待处理队列中，更新最后修改时间
            with self.pending_lock:
                if file_path in self.pending_files:
                    self.pending_files[file_path] = time.time()
        
        def on_moved(self, event: FileSystemEvent) -> None:
            """文件移动事件
            
            处理文件从 .cache 或其他被忽略的目录移动到正常目录的情况
            （例如 huggingface_cli 下载时会先下载到 .cache 再 move 到目标目录）
            """
            if event.is_directory:
                return
            
            dest_path = event.dest_path
            src_path = event.src_path
            
            # 检查源路径是否应该被忽略，目标路径是否不应该被忽略
            src_should_ignore = self._should_ignore(src_path)
            dest_should_ignore = self._should_ignore(dest_path)
            
            # 如果文件从被忽略的位置移动到不被忽略的位置，视为新文件创建
            if src_should_ignore and not dest_should_ignore:
                log("DEBUG", f"File moved from ignored location to target, treating as new file: {os.path.basename(dest_path)}")
                # 检查是否是实体文件（不是软链接）
                if not os.path.islink(dest_path):
                    with self.pending_lock:
                        self.pending_files[dest_path] = time.time()
                    log("DEBUG", f"New real file detected (moved), adding to pending queue: {os.path.basename(dest_path)}")
            # 如果在正常位置之间移动，更新队列中的路径
            elif not src_should_ignore and not dest_should_ignore:
                with self.pending_lock:
                    if src_path in self.pending_files:
                        # 将旧路径的时间戳移到新路径
                        del self.pending_files[src_path]
                        self.pending_files[dest_path] = time.time()
                        log("DEBUG", f"File moved within watched directory, updating queue: {os.path.basename(dest_path)}")
        
        def _should_ignore(self, file_path: str) -> bool:
            """判断是否应该忽略该文件"""
            filename = os.path.basename(file_path)
            
            # 检查文件名模式
            for pattern in IGNORE_PATTERNS:
                if pattern.startswith('*.'):
                    ext = pattern[1:]  # 去掉 *
                    if filename.endswith(ext):
                        return True
                elif filename == pattern:
                    return True
            
            # 检查路径中的所有目录（不仅仅是直接父目录）
            # 例如：/root/comfyui/models/vae/.cache/file.safetensors 应该被忽略
            path_parts = file_path.split(os.sep)
            for part in path_parts:
                if part in IGNORE_DIRS:
                    return True
            
            return False


class UserModelDirPoller:
    """用户模型目录轮询器
    
    轮询 /mnt/auto/models 目录，将变化同步到 ComfyUI 目录（创建软链接）
    用于 NAS 等不支持 inotify 的文件系统
    """
    
    def __init__(self, user_models_dir: str, comfyui_models_dir: str):
        """
        初始化用户目录轮询器
        
        Args:
            user_models_dir: 用户模型目录（如 /mnt/auto/models）
            comfyui_models_dir: ComfyUI 模型目录（如 /root/comfyui/models）
        """
        self.user_models_dir = user_models_dir
        self.comfyui_models_dir = comfyui_models_dir
        
        # 已知文件快照：{filepath: mtime}
        self.known_files: Dict[str, float] = {}
        
        # 轮询线程
        self.poller_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.is_running = False
    
    def start(self) -> None:
        """启动轮询"""
        if self.is_running:
            log("WARNING", "UserModelDirPoller is already running")
            return
        
        if not os.path.isdir(self.user_models_dir):
            log("WARNING", f"User models directory does not exist: {self.user_models_dir}")
            return
        
        log("INFO", f"Starting user directory poller: {self.user_models_dir} (interval: {USER_DIR_POLL_INTERVAL}s)")
        
        # 启动轮询线程
        self.stop_event.clear()
        self.poller_thread = threading.Thread(
            target=self._polling_loop,
            daemon=True,
            name="UserModelDirPoller"
        )
        self.poller_thread.start()
        
        self.is_running = True
        log("INFO", "User directory poller started")
    
    def stop(self) -> None:
        """停止轮询"""
        if not self.is_running:
            return
        
        log("INFO", "Stopping user directory poller...")
        
        # 停止轮询线程
        self.stop_event.set()
        if self.poller_thread:
            self.poller_thread.join(timeout=5)
        
        self.is_running = False
        log("INFO", "User directory poller stopped")
    
    def _polling_loop(self) -> None:
        """轮询循环"""
        log("DEBUG", "User directory poller loop started")
        
        # 初始化：扫描当前所有文件
        self._initial_scan()
        
        # 定期扫描
        while not self.stop_event.is_set():
            try:
                self._check_changes()
            except Exception as e:
                log("ERROR", f"User directory polling error: {e}")
            
            # 等待下一次扫描
            self.stop_event.wait(USER_DIR_POLL_INTERVAL)
        
        log("DEBUG", "User directory poller loop stopped")
    
    def _initial_scan(self) -> None:
        """初始扫描：记录所有已存在的文件"""
        try:
            for root, dirs, files in os.walk(self.user_models_dir):
                for filename in files:
                    filepath = os.path.join(root, filename)
                    try:
                        mtime = os.path.getmtime(filepath)
                        self.known_files[filepath] = mtime
                    except OSError:
                        pass
            log("DEBUG", f"Initial scan completed: {len(self.known_files)} files found")
        except Exception as e:
            log("ERROR", f"Initial scan failed: {e}")
    
    def _check_changes(self) -> None:
        """检查文件变化"""
        current_files = {}
        
        # 扫描当前所有文件
        try:
            for root, dirs, files in os.walk(self.user_models_dir):
                for filename in files:
                    filepath = os.path.join(root, filename)
                    try:
                        mtime = os.path.getmtime(filepath)
                        current_files[filepath] = mtime
                    except OSError:
                        pass
        except Exception as e:
            log("ERROR", f"Directory scan failed: {e}")
            return
        
        # 检测新增或修改的文件
        for filepath, mtime in current_files.items():
            if filepath not in self.known_files:
                # 新增文件
                log("DEBUG", f"New file detected in user directory: {os.path.basename(filepath)}")
                self._sync_to_comfyui(filepath)
            elif mtime > self.known_files[filepath]:
                # 文件被修改（重新创建软链接）
                log("DEBUG", f"Modified file detected in user directory: {os.path.basename(filepath)}")
                self._sync_to_comfyui(filepath)
        
        # 检测删除的文件
        removed_files = set(self.known_files.keys()) - set(current_files.keys())
        for filepath in removed_files:
            log("DEBUG", f"Deleted file detected in user directory: {os.path.basename(filepath)}")
            self._remove_from_comfyui(filepath)
        
        # 更新已知文件列表
        self.known_files = current_files
    
    def _sync_to_comfyui(self, source_path: str) -> None:
        """将用户目录中的文件同步到 ComfyUI 目录（创建软链接）"""
        try:
            rel_path = os.path.relpath(source_path, self.user_models_dir)
            comfyui_path = os.path.join(self.comfyui_models_dir, rel_path)
            
            # 确保目标目录存在
            os.makedirs(os.path.dirname(comfyui_path), exist_ok=True)
            
            # 如果目标已存在
            if os.path.exists(comfyui_path) or os.path.islink(comfyui_path):
                if os.path.islink(comfyui_path):
                    # 更新软链接
                    os.unlink(comfyui_path)
                    os.symlink(source_path, comfyui_path)
                    log("INFO", f"User model updated: {rel_path}")
                else:
                    # 实体文件，不覆盖
                    log("DEBUG", f"Real file exists in ComfyUI directory, skipping: {rel_path}")
            else:
                # 创建新软链接
                os.symlink(source_path, comfyui_path)
                log("INFO", f"User model linked: {rel_path}")
                
        except Exception as e:
            log("ERROR", f"Failed to sync user model to ComfyUI directory: {e}")
    
    def _remove_from_comfyui(self, source_path: str) -> None:
        """从 ComfyUI 目录中删除软链接"""
        try:
            rel_path = os.path.relpath(source_path, self.user_models_dir)
            comfyui_path = os.path.join(self.comfyui_models_dir, rel_path)
            
            # 删除 ComfyUI 目录中的软链接
            if os.path.islink(comfyui_path):
                os.unlink(comfyui_path)
                log("INFO", f"User model unlinked: {rel_path}")
            
        except Exception as e:
            log("ERROR", f"Failed to remove symlink: {e}")


# 全局单例
_comfyui_watcher: Optional[ComfyUIModelDirWatcher] = None
_user_poller: Optional[UserModelDirPoller] = None
_watcher_lock = threading.Lock()


def start_model_watcher(
    comfyui_models_dir: str,
    user_models_dir: Optional[str] = None
) -> None:
    """
    启动模型目录双向监听（全局单例）
    
    Args:
        comfyui_models_dir: ComfyUI 模型目录
        user_models_dir: 用户模型目录
    """
    global _comfyui_watcher, _user_poller
    
    if not user_models_dir:
        log("INFO", "User models directory not configured, skipping model watcher")
        return
    
    with _watcher_lock:
        # 停止旧实例
        if _comfyui_watcher is not None:
            log("WARNING", "ComfyUIModelDirWatcher already exists, stopping old instance")
            _comfyui_watcher.stop()
        if _user_poller is not None:
            log("WARNING", "UserModelDirPoller already exists, stopping old instance")
            _user_poller.stop()
        
        # 创建并启动用户目录轮询器
        if not constants.USE_API_MODE:
            _user_poller = UserModelDirPoller(
                user_models_dir=user_models_dir,
                comfyui_models_dir=comfyui_models_dir
            )
            _user_poller.start()

        # 创建并启动 ComfyUI 目录监听器
        _comfyui_watcher = ComfyUIModelDirWatcher(
            comfyui_models_dir=comfyui_models_dir,
            user_models_dir=user_models_dir
        )
        _comfyui_watcher.start()
        
        log("INFO", "Model directory watcher started successfully")


def stop_model_watcher() -> None:
    """停止模型目录监听"""
    global _comfyui_watcher, _user_poller
    
    with _watcher_lock:
        if _comfyui_watcher is not None:
            _comfyui_watcher.stop()
            _comfyui_watcher = None
        
        if _user_poller is not None:
            _user_poller.stop()
            _user_poller = None
        
        log("INFO", "Model directory watcher stopped")
