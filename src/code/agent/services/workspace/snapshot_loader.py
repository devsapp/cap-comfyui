import os
from abc import ABC, abstractmethod
from typing import Dict

import constants
from utils import file_ops
from utils.logger import log


class SnapshotLoader(ABC):
    def __init__(self, timer):
        self.timer = timer

    def load(self, snapshot_path: str) -> Dict:
        stage_cost = {}
        from services.management_service import ManagementService
        from services.management_service import StartingSubStatus
        service = ManagementService()
        with self.timer("Clearing work dir") as t_clear:
            self._clear()
        stage_cost["time_clear"] = round(t_clear.elapsed, 2)

        service.sub_status = StartingSubStatus.DOWNLOADING.value
        with self.timer(f"Downloading snapshot from {snapshot_path}") as t_download:
            self._download(snapshot_path)
        stage_cost["time_download"] = round(t_download.elapsed, 2)

        service.sub_status = StartingSubStatus.EXTRACTING.value
        with self.timer("Extracting snapshot") as t_extract:
            self._extract()
        stage_cost["time_extract"] = round(t_extract.elapsed, 2)

        self._create_symlinks(snapshot_path)
        return stage_cost

    def prepare_link(self):
        with self.timer("Creating symbolic link"):
            self._create_symlinks("")

    @abstractmethod
    def _clear(self):
        """清理工作目录"""
        pass

    @abstractmethod
    def _download(self, snapshot_path: str):
        """下载快照"""
        pass

    @abstractmethod
    def _extract(self):
        """解压依赖"""
        pass

    @abstractmethod
    def _create_symlinks(self, snapshot_path: str):
        """创建相关目录软链接"""
        pass


class ComfyUIDevSnapshotLoader(SnapshotLoader):
    def _clear(self):
        file_ops.remove(constants.COMFYUI_DIR)
        file_ops.remove(constants.VENV_DIR)

    def _download(self, snapshot_path: str):
        # 优先使用 zstd 格式，降级到旧格式（向后兼容）
        if os.path.exists(f"{snapshot_path}/venv.tar.zst"):
            file_ops.copy(f"{snapshot_path}/venv.tar.zst", f"{constants.WORK_DIR}/venv.tar.zst")
        else:
            log("WARNING", "venv.tar.zst not found, falling back to venv.tar")
            file_ops.copy(f"{snapshot_path}/venv.tar", f"{constants.WORK_DIR}/venv.tar")
        
        if os.path.exists(f"{snapshot_path}/comfyui.tar.zst"):
            file_ops.copy(f"{snapshot_path}/comfyui.tar.zst", f"{constants.WORK_DIR}/comfyui.tar.zst")
        else:
            log("WARNING", "comfyui.tar.zst not found, falling back to comfyui.zip")
            file_ops.copy(f"{snapshot_path}/comfyui.zip", f"{constants.WORK_DIR}/comfyui.zip")

    def _extract(self):
        # 解压 venv（优先 zstd，降级到 tar）
        if os.path.exists(f"{constants.WORK_DIR}/venv.tar.zst"):
            file_ops.extract_zstd(f"{constants.WORK_DIR}/venv.tar.zst")
            file_ops.remove(f"{constants.WORK_DIR}/venv.tar.zst")
        else:
            file_ops.extract(f"{constants.WORK_DIR}/venv.tar")
            file_ops.remove(f"{constants.WORK_DIR}/venv.tar")
        
        # 解压 comfyui（优先 zstd，降级到 zip）
        if os.path.exists(f"{constants.WORK_DIR}/comfyui.tar.zst"):
            file_ops.extract_zstd(f"{constants.WORK_DIR}/comfyui.tar.zst")
            file_ops.remove(f"{constants.WORK_DIR}/comfyui.tar.zst")
        else:
            file_ops.extract(f"{constants.WORK_DIR}/comfyui.zip")
            file_ops.remove(f"{constants.WORK_DIR}/comfyui.zip")

    def _create_symlinks(self, snapshot_path: str):
        file_ops.create_symlink(
            source_path=f"{constants.MNT_DIR}/custom_nodes",
            link_path=f"{constants.COMFYUI_DIR}/custom_nodes",
            force=True
        )
        
        # 新建 .cache 目录软链接
        mnt_cache_dir = f"{constants.MNT_DIR}/.cache"
        work_cache_dir = f"{constants.WORK_DIR}/.cache"
        if not os.path.exists(mnt_cache_dir):
            os.makedirs(mnt_cache_dir, exist_ok=True)
        file_ops.create_symlink(
            source_path=mnt_cache_dir,
            link_path=work_cache_dir,
            force=True
        )


class ComfyUIProdSnapshotLoader(SnapshotLoader):
    def _clear(self):
        file_ops.remove(constants.COMFYUI_DIR)
        file_ops.remove(constants.VENV_DIR)

    def _download(self, snapshot_path: str):
        # 优先使用 zstd 格式，降级到旧格式（向后兼容）
        if os.path.exists(f"{snapshot_path}/venv.tar.zst"):
            file_ops.copy(f"{snapshot_path}/venv.tar.zst", f"{constants.WORK_DIR}/venv.tar.zst")
        else:
            log("WARNING", "venv.tar.zst not found, falling back to venv.tar")
            file_ops.copy(f"{snapshot_path}/venv.tar", f"{constants.WORK_DIR}/venv.tar")
        
        if os.path.exists(f"{snapshot_path}/comfyui.tar.zst"):
            file_ops.copy(f"{snapshot_path}/comfyui.tar.zst", f"{constants.WORK_DIR}/comfyui.tar.zst")
        else:
            log("WARNING", "comfyui.tar.zst not found, falling back to comfyui.zip")
            file_ops.copy(f"{snapshot_path}/comfyui.zip", f"{constants.WORK_DIR}/comfyui.zip")
        
        if os.path.exists(f"{snapshot_path}/.cache"):
            file_ops.remove(f"{constants.WORK_DIR}/.cache")
            file_ops.copy(f"{snapshot_path}/.cache", f"{constants.WORK_DIR}/.cache")
        
        if not constants.SKIP_NODES_LOADING:
            if os.path.exists(f"{snapshot_path}/custom_nodes.tar.zst"):
                file_ops.copy(f"{snapshot_path}/custom_nodes.tar.zst", f"{constants.WORK_DIR}/custom_nodes.tar.zst")
            else:
                log("WARNING", "custom_nodes.tar.zst not found, falling back to custom_nodes.zip")
                file_ops.copy(f"{snapshot_path}/custom_nodes.zip", f"{constants.WORK_DIR}/custom_nodes.zip")

    def _extract(self):
        # 解压 venv（优先 zstd，降级到 tar）
        if os.path.exists(f"{constants.WORK_DIR}/venv.tar.zst"):
            file_ops.extract_zstd(f"{constants.WORK_DIR}/venv.tar.zst")
            file_ops.remove(f"{constants.WORK_DIR}/venv.tar.zst")
        else:
            file_ops.extract(f"{constants.WORK_DIR}/venv.tar")
            file_ops.remove(f"{constants.WORK_DIR}/venv.tar")
        
        # 解压 comfyui（优先 zstd，降级到 zip）
        if os.path.exists(f"{constants.WORK_DIR}/comfyui.tar.zst"):
            file_ops.extract_zstd(f"{constants.WORK_DIR}/comfyui.tar.zst")
            file_ops.remove(f"{constants.WORK_DIR}/comfyui.tar.zst")
        else:
            file_ops.extract(f"{constants.WORK_DIR}/comfyui.zip")
            file_ops.remove(f"{constants.WORK_DIR}/comfyui.zip")
        
        if not constants.SKIP_NODES_LOADING:
            file_ops.remove(f"{constants.COMFYUI_DIR}/custom_nodes")  # 解压时不会强制覆盖，需手动删除解压时会产生冲突的文件
            
            # 解压 custom_nodes（优先 zstd，降级到 zip）
            if os.path.exists(f"{constants.WORK_DIR}/custom_nodes.tar.zst"):
                file_ops.extract_zstd(f"{constants.WORK_DIR}/custom_nodes.tar.zst", output_dir=f"{constants.COMFYUI_DIR}/custom_nodes")
                file_ops.remove(f"{constants.WORK_DIR}/custom_nodes.tar.zst")
            else:
                file_ops.extract(f"{constants.WORK_DIR}/custom_nodes.zip", output_dir=f"{constants.COMFYUI_DIR}/custom_nodes")
                file_ops.remove(f"{constants.WORK_DIR}/custom_nodes.zip")

    def _create_symlinks(self, snapshot_path: str):
        if constants.SKIP_NODES_LOADING and snapshot_path:
            file_ops.remove(f"{constants.COMFYUI_DIR}/custom_nodes")
            file_ops.create_symlink(
                source_path=f"{snapshot_path}/custom_nodes",
                link_path=f"{constants.COMFYUI_DIR}/custom_nodes",
                force=True
            )
        # 线上服务GPU实例使用实例磁盘中的input目录，需确保目录存在防止comfyui启动过程中LoadImage节点加载失败
        if not os.path.exists(constants.INPUT_DIR):
            os.makedirs(constants.INPUT_DIR, exist_ok=True)


class SDSnapshotLoader(SnapshotLoader):
    def _clear(self):
        file_ops.remove(constants.SD_DIR)
        file_ops.remove(constants.VENV_DIR)

    def _download(self, snapshot_path: str):
        # 优先使用 zstd 格式，降级到旧格式（向后兼容）
        if os.path.exists(f"{snapshot_path}/venv.tar.zst"):
            file_ops.copy(f"{snapshot_path}/venv.tar.zst", f"{constants.WORK_DIR}/venv.tar.zst")
        else:
            log("WARNING", "venv.tar.zst not found, falling back to venv.tar")
            file_ops.copy(f"{snapshot_path}/venv.tar", f"{constants.WORK_DIR}/venv.tar")
        
        if os.path.exists(f"{snapshot_path}/stable-diffusion-webui.tar.zst"):
            file_ops.copy(f"{snapshot_path}/stable-diffusion-webui.tar.zst", f"{constants.WORK_DIR}/stable-diffusion-webui.tar.zst")
        else:
            log("WARNING", "stable-diffusion-webui.tar.zst not found, falling back to stable-diffusion-webui.zip")
            file_ops.copy(f"{snapshot_path}/stable-diffusion-webui.zip", f"{constants.WORK_DIR}/stable-diffusion-webui.zip")
        
        # 处理 cache（优先 zstd，降级到 zip）
        cache_zst_path = f"{snapshot_path}/.cache.tar.zst"
        cache_zip_path = f"{snapshot_path}/.cache.zip"
        if os.path.exists(cache_zst_path):
            file_ops.copy(cache_zst_path, f"{constants.WORK_DIR}/.cache.tar.zst")
        elif os.path.exists(cache_zip_path):
            log("WARNING", ".cache.tar.zst not found, falling back to .cache.zip")
            file_ops.copy(cache_zip_path, f"{constants.WORK_DIR}/.cache.zip")

    def _extract(self):
        # 解压 venv（优先 zstd，降级到 tar）
        if os.path.exists(f"{constants.WORK_DIR}/venv.tar.zst"):
            file_ops.extract_zstd(f"{constants.WORK_DIR}/venv.tar.zst")
            file_ops.remove(f"{constants.WORK_DIR}/venv.tar.zst")
        else:
            file_ops.extract(f"{constants.WORK_DIR}/venv.tar")
            file_ops.remove(f"{constants.WORK_DIR}/venv.tar")
        
        # 解压 stable-diffusion-webui（优先 zstd，降级到 zip）
        if os.path.exists(f"{constants.WORK_DIR}/stable-diffusion-webui.tar.zst"):
            file_ops.extract_zstd(f"{constants.WORK_DIR}/stable-diffusion-webui.tar.zst")
            file_ops.remove(f"{constants.WORK_DIR}/stable-diffusion-webui.tar.zst")
        else:
            file_ops.extract(f"{constants.WORK_DIR}/stable-diffusion-webui.zip")
            file_ops.remove(f"{constants.WORK_DIR}/stable-diffusion-webui.zip")
        
        # 解压 cache（优先 zstd，降级到 zip）
        cache_zst_path = f"{constants.WORK_DIR}/.cache.tar.zst"
        cache_zip_path = f"{constants.WORK_DIR}/.cache.zip"
        if os.path.exists(cache_zst_path):
            file_ops.extract_zstd(cache_zst_path)
            file_ops.remove(cache_zst_path)
        elif os.path.exists(cache_zip_path):
            file_ops.extract(cache_zip_path)
            file_ops.remove(cache_zip_path)

    def _create_symlinks(self, snapshot_path: str):
        file_ops.create_symlink(
            source_path=f"{constants.MODEL_DIR}",
            link_path=f"{constants.SD_DIR}/models",
            force=True
        )

        config_path = f"{constants.MNT_DIR}/config.json"
        origin_config_path = f"{constants.SD_DIR}/config.json"
        if not os.path.exists(config_path):
            log("INFO", f'Init config.json in MNT_DIR: {constants.MNT_DIR}')
            # 基于工作空间快照中的config.json作修改后写入挂载目录
            import json
            with open(origin_config_path, "r") as f:
                config = json.load(f)
            config.update({
                "outdir_samples": f"{constants.MNT_DIR}/output",  # 单图输出目录
                "outdir_grids": f"{constants.MNT_DIR}/output",  # 网格图输出目录
                "outdir_save": f"{constants.MNT_DIR}/output/saves",  # Save按钮保存图输出目录
                "outdir_init_images": f"{constants.MNT_DIR}/input",  # 图生图输入图片存储目录
                "save_init_img": True  # 图生图上传图片时是否自动保存输入图片
            })
            with open(config_path, "w") as f:
                json.dump(config, f, indent=4)

        # 将SD目录下的config.json替换为软链接
        file_ops.create_symlink(
            source_path=config_path,
            link_path=origin_config_path,
            force=True
        )
