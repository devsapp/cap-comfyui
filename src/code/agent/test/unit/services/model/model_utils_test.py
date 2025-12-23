"""
model_utils 单元测试
测试模型准备功能，验证平台共享模型和用户模型的链接逻辑
"""

import os
import tempfile
import shutil
import pytest
import constants
from types import SimpleNamespace

from services.model.linker import prepare_models


def _create_test_file(path: str, content: str):
    """创建测试文件"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)


def _read_file(path: str) -> str:
    """读取文件内容"""
    with open(path, 'r') as f:
        return f.read()


class TestPrepareModels:
    """测试 prepare_models 函数"""
    
    def setup_method(self):
        """每个测试方法执行前的setup"""
        # 创建临时测试目录
        # 模拟以下目录结构和文件:
        # test_dir/
        # ├── shared/models/              # 平台共享模型目录（所有用户共享）
        # │   ├── checkpoints/
        # │   │   ├── base_model.ckpt         # 共享检查点（与用户模型重名）
        # │   │   └── sd_v1.5.safetensors     # SD 1.5 模型
        # │   ├── loras/
        # │   │   └── style_lora.safetensors  # 风格 LoRA
        # │   └── vae/
        # │       └── vae_model.safetensors   # VAE 模型
        # ├── user/models/                # 用户私有模型目录
        # │   ├── checkpoints/
        # │   │   ├── base_model.ckpt         # 用户检查点（覆盖共享模型）
        # │   │   └── my_model.safetensors    # 用户自定义模型
        # │   └── embeddings/
        # │       └── my_embedding.pt         # 用户 embedding
        # └── comfyui/models/             # ComfyUI 实际使用的模型目录（链接目标）
        #     预期结果: 通过软链接合并 shared 和 user 目录，user 优先
        test_dir = tempfile.mkdtemp()
        
        self.setup = SimpleNamespace(
            test_dir=test_dir,
            shared_models_dir=os.path.join(test_dir, "shared/models"),      # 平台共享模型
            user_models_dir=os.path.join(test_dir, "user/models"),          # 用户模型
            target_models_dir=os.path.join(test_dir, "comfyui/models")      # 目标目录
        )
        
        # 创建测试目录结构
        os.makedirs(os.path.join(self.setup.shared_models_dir, "checkpoints"), exist_ok=True)
        os.makedirs(os.path.join(self.setup.shared_models_dir, "loras"), exist_ok=True)
        os.makedirs(os.path.join(self.setup.shared_models_dir, "vae"), exist_ok=True)
        
        os.makedirs(os.path.join(self.setup.user_models_dir, "checkpoints"), exist_ok=True)
        os.makedirs(os.path.join(self.setup.user_models_dir, "embeddings"), exist_ok=True)
        
        # 创建测试文件
        # 平台共享模型
        _create_test_file(
            os.path.join(self.setup.shared_models_dir, "checkpoints/base_model.ckpt"),
            "shared_checkpoint_1"
        )
        _create_test_file(
            os.path.join(self.setup.shared_models_dir, "checkpoints/sd_v1.5.safetensors"),
            "shared_checkpoint_2"
        )
        _create_test_file(
            os.path.join(self.setup.shared_models_dir, "loras/style_lora.safetensors"),
            "shared_lora"
        )
        _create_test_file(
            os.path.join(self.setup.shared_models_dir, "vae/vae_model.safetensors"),
            "shared_vae"
        )
        
        # 用户模型（包含一个与平台模型同名的文件）
        _create_test_file(
            os.path.join(self.setup.user_models_dir, "checkpoints/base_model.ckpt"),
            "user_checkpoint"
        )
        _create_test_file(
            os.path.join(self.setup.user_models_dir, "checkpoints/my_model.safetensors"),
            "user_checkpoint_2"
        )
        _create_test_file(
            os.path.join(self.setup.user_models_dir, "embeddings/my_embedding.pt"),
            "user_embedding"
        )
    
    def teardown_method(self):
        """每个测试方法执行后的cleanup"""
        if hasattr(self, 'setup') and os.path.exists(self.setup.test_dir):
            shutil.rmtree(self.setup.test_dir)
    
    def test_prepare_models_basic(self):
        """测试基本的模型准备功能"""
        prepare_models(
            target_dir=self.setup.target_models_dir,
            user_models_dir=self.setup.user_models_dir,
            shared_models_dir=self.setup.shared_models_dir
        )
        
        # 验证目标目录已创建
        assert os.path.exists(self.setup.target_models_dir)
        
        # 验证平台共享模型已链接到正确位置
        # 1. checkpoints/base_model.ckpt" (user)
        base_model= os.path.join(self.setup.target_models_dir, "checkpoints/base_model.ckpt")
        assert os.path.islink(base_model), "basic_models 应该是软链接"
        assert os.readlink(base_model) == os.path.join(
            self.setup.user_models_dir, "checkpoints/base_model.ckpt"
        ), "base_model 应该链接到 user/models/checkpoints/"
        assert _read_file(base_model) == "user_checkpoint"

       
        # 2. sd_v1.5.safetensors (shared)
        shared_sd = os.path.join(self.setup.target_models_dir, "checkpoints/sd_v1.5.safetensors")
        assert os.path.islink(shared_sd), "sd_v1.5 应该是软链接"
        assert os.readlink(shared_sd) == os.path.join(
            self.setup.shared_models_dir, "checkpoints/sd_v1.5.safetensors"
        ), "sd_v1.5 应该链接到 shared/models/checkpoints/"
        assert _read_file(shared_sd) == "shared_checkpoint_2"
        
        # 3. style_lora.safetensors (shared)
        shared_lora = os.path.join(self.setup.target_models_dir, "loras/style_lora.safetensors")
        assert os.path.islink(shared_lora), "style_lora 应该是软链接"
        assert os.readlink(shared_lora) == os.path.join(
            self.setup.shared_models_dir, "loras/style_lora.safetensors"
        ), "style_lora 应该链接到 shared/models/loras/"
        assert _read_file(shared_lora) == "shared_lora"
        

        # 4. vae_model.safetensors (shared)
        shared_vae = os.path.join(self.setup.target_models_dir, "vae/vae_model.safetensors")
        assert os.path.islink(shared_vae), "vae_model 应该是软链接"
        assert os.readlink(shared_vae) == os.path.join(
            self.setup.shared_models_dir, "vae/vae_model.safetensors"
        ), "vae_model 应该链接到 shared/models/vae/"
        assert _read_file(shared_vae) == "shared_vae"
        
        # 验证用户模型已链接到正确位置
        # 5. my_model.safetensors (user)
        user_model = os.path.join(self.setup.target_models_dir, "checkpoints/my_model.safetensors")
        assert os.path.islink(user_model), "my_model 应该是软链接"
        assert os.readlink(user_model) == os.path.join(
            self.setup.user_models_dir, "checkpoints/my_model.safetensors"
        ), "my_model 应该链接到 user/models/checkpoints/"
        assert _read_file(user_model) == "user_checkpoint_2"
        
        # 6. my_embedding.pt (user)
        user_embedding = os.path.join(self.setup.target_models_dir, "embeddings/my_embedding.pt")
        assert os.path.islink(user_embedding), "my_embedding 应该是软链接"
        assert os.readlink(user_embedding) == os.path.join(
            self.setup.user_models_dir, "embeddings/my_embedding.pt"
        ), "my_embedding 应该链接到 user/models/embeddings/"
        assert _read_file(user_embedding) == "user_embedding"

    def test_missing_shared_models_dir(self):
        """测试平台共享模型目录不存在的情况"""
        # 不应该抛出异常
        prepare_models(
            target_dir=self.setup.target_models_dir,
            user_models_dir=self.setup.user_models_dir,
            shared_models_dir=None
        )
        
        # 当只有用户模型目录存在时，target_models_dir 会直接链接到 user_models_dir（优化策略）
        assert os.path.islink(self.setup.target_models_dir), "target_models_dir 应该是软链接"
        assert os.readlink(self.setup.target_models_dir) == self.setup.user_models_dir, \
            "target_models_dir 应该直接链接到 user_models_dir"
        
        # 验证可以访问用户模型
        user_model = os.path.join(self.setup.target_models_dir, "checkpoints/my_model.safetensors")
        assert os.path.exists(user_model), "用户模型应该可以访问"
        assert _read_file(user_model) == "user_checkpoint_2"
    
    def test_missing_user_models_dir(self):
        """测试用户模型目录不存在的情况"""
        # 不应该抛出异常
        prepare_models(
            target_dir=self.setup.target_models_dir,
            user_models_dir=None,
            shared_models_dir=self.setup.shared_models_dir
        )
        
        # 当 user_models_dir=None 时，逐个文件链接共享模型
        # 验证平台共享模型被正确链接
        shared_model = os.path.join(self.setup.target_models_dir, "loras/style_lora.safetensors")
        assert os.path.islink(shared_model), "共享模型应该是软链接"
        assert os.readlink(shared_model) == os.path.join(
            self.setup.shared_models_dir, "loras/style_lora.safetensors"
        ), "共享模型应该链接到正确的位置"
        assert _read_file(shared_model) == "shared_lora"
    
    def test_directory_structure_preserved(self):
        """测试目录结构被保持"""
        prepare_models(
            target_dir=self.setup.target_models_dir,
            user_models_dir=self.setup.user_models_dir,
            shared_models_dir=self.setup.shared_models_dir
        )
        
        # 验证目录结构
        assert os.path.isdir(os.path.join(self.setup.target_models_dir, "checkpoints"))
        assert os.path.isdir(os.path.join(self.setup.target_models_dir, "loras"))
        assert os.path.isdir(os.path.join(self.setup.target_models_dir, "vae"))
        assert os.path.isdir(os.path.join(self.setup.target_models_dir, "embeddings"))
    
    def test_nested_multilevel_directories(self):
        """测试多级嵌套目录结构的正确处理
        
        验证深层嵌套的目录（如 checkpoints/category/subcategory/model.ckpt）
        能够被正确链接，且目录结构被完整保留
        """
        # 创建多级目录结构的测试文件
        # 共享模型：3级嵌套
        _create_test_file(
            os.path.join(self.setup.shared_models_dir, "checkpoints/sdxl/base/model_v1.safetensors"),
            "shared_nested_checkpoint"
        )
        # 共享模型：4级嵌套
        _create_test_file(
            os.path.join(self.setup.shared_models_dir, "loras/styles/anime/characters/lora.safetensors"),
            "shared_deep_nested_lora"
        )
        
        # 用户模型：3级嵌套
        _create_test_file(
            os.path.join(self.setup.user_models_dir, "checkpoints/custom/finetune/my_model.ckpt"),
            "user_nested_checkpoint"
        )
        # 用户模型：与共享模型同路径但不同文件名
        _create_test_file(
            os.path.join(self.setup.user_models_dir, "loras/styles/anime/my_anime.safetensors"),
            "user_nested_lora"
        )
        
        # 执行模型准备
        prepare_models(
            target_dir=self.setup.target_models_dir,
            user_models_dir=self.setup.user_models_dir,
            shared_models_dir=self.setup.shared_models_dir
        )
        
        # 验证共享模型的多级目录
        shared_nested = os.path.join(
            self.setup.target_models_dir, "checkpoints/sdxl/base/model_v1.safetensors"
        )
        assert os.path.exists(shared_nested), "多级目录文件应该存在"
        assert os.path.islink(shared_nested), "应该是软链接"
        assert os.readlink(shared_nested) == os.path.join(
            self.setup.shared_models_dir, "checkpoints/sdxl/base/model_v1.safetensors"
        ), "应该链接到正确的共享模型位置"
        assert _read_file(shared_nested) == "shared_nested_checkpoint"
        
        shared_deep = os.path.join(
            self.setup.target_models_dir, "loras/styles/anime/characters/lora.safetensors"
        )
        assert os.path.exists(shared_deep), "深层嵌套文件应该存在"
        assert os.path.islink(shared_deep), "应该是软链接"
        assert _read_file(shared_deep) == "shared_deep_nested_lora"
        
        # 验证用户模型的多级目录
        user_nested = os.path.join(
            self.setup.target_models_dir, "checkpoints/custom/finetune/my_model.ckpt"
        )
        assert os.path.exists(user_nested), "用户多级目录文件应该存在"
        assert os.path.islink(user_nested), "应该是软链接"
        assert os.readlink(user_nested) == os.path.join(
            self.setup.user_models_dir, "checkpoints/custom/finetune/my_model.ckpt"
        ), "应该链接到正确的用户模型位置"
        assert _read_file(user_nested) == "user_nested_checkpoint"
        
        user_in_shared_path = os.path.join(
            self.setup.target_models_dir, "loras/styles/anime/my_anime.safetensors"
        )
        assert os.path.exists(user_in_shared_path), "用户文件应该存在"
        assert os.path.islink(user_in_shared_path), "应该是软链接"
        assert _read_file(user_in_shared_path) == "user_nested_lora"
        
        # 验证目录结构完整保留
        assert os.path.isdir(os.path.join(self.setup.target_models_dir, "checkpoints/sdxl/base"))
        assert os.path.isdir(os.path.join(self.setup.target_models_dir, "checkpoints/custom/finetune"))
        assert os.path.isdir(os.path.join(self.setup.target_models_dir, "loras/styles/anime/characters"))
        assert os.path.isdir(os.path.join(self.setup.target_models_dir, "loras/styles/anime"))
    
    def test_mixed_errors_some_files_succeed(self):
        """测试混合错误场景：部分文件失败不影响其他文件成功链接"""
        from unittest.mock import patch
        
        # 创建更多测试文件
        _create_test_file(
            os.path.join(self.setup.user_models_dir, "checkpoints/user3.ckpt"),
            "user3"
        )
        _create_test_file(
            os.path.join(self.setup.shared_models_dir, "checkpoints/shared_extra.ckpt"),
            "shared_extra"
        )
        
        original_symlink = os.symlink
        
        def selective_fail_symlink(src, dst):
            # 让包含 "base_model" 的链接失败（模拟权限问题）
            if "base_model" in dst:
                raise PermissionError("Mock: Permission denied for base_model")
            return original_symlink(src, dst)
        
        with patch('services.model.linker.os.symlink', side_effect=selective_fail_symlink):
            # 执行 prepare_models
            prepare_models(
                target_dir=self.setup.target_models_dir,
                user_models_dir=self.setup.user_models_dir,
                shared_models_dir=self.setup.shared_models_dir
            )
        
        # 验证成功的文件
        sd_link = os.path.join(self.setup.target_models_dir, "checkpoints/sd_v1.5.safetensors")
        my_model_link = os.path.join(self.setup.target_models_dir, "checkpoints/my_model.safetensors")
        lora_link = os.path.join(self.setup.target_models_dir, "loras/style_lora.safetensors")
        user3_link = os.path.join(self.setup.target_models_dir, "checkpoints/user3.ckpt")
        
        assert os.path.islink(sd_link), "sd_v1.5 应该成功链接"
        assert os.path.islink(my_model_link), "my_model 应该成功链接"
        assert os.path.islink(lora_link), "style_lora 应该成功链接"
        assert os.path.islink(user3_link), "user3 应该成功链接"
        
        # 验证失败的文件不存在或不是软链接
        base_model_link = os.path.join(self.setup.target_models_dir, "checkpoints/base_model.ckpt")
        # base_model 应该链接失败（虽然在 shared 和 user 中都存在）
        assert not os.path.exists(base_model_link) or not os.path.islink(base_model_link), \
            "base_model 应该因为权限错误而失败"
    
    def test_no_crash_on_complete_failure(self):
        """测试所有文件链接都失败时不会崩溃，启动流程继续"""
        from unittest.mock import patch
        
        # 模拟所有 symlink 操作都失败
        with patch('services.model.linker.os.symlink', side_effect=OSError("Mock: Complete failure - disk full")):
            # 执行 prepare_models - 应该不会抛出异常
            try:
                prepare_models(
                    target_dir=self.setup.target_models_dir,
                    user_models_dir=self.setup.user_models_dir,
                    shared_models_dir=self.setup.shared_models_dir
                )
                # 成功完成（虽然所有链接都失败了）
                success = True
            except Exception as e:
                success = False
                pytest.fail(f"prepare_models 不应该崩溃，即使所有文件都失败: {e}")
        
        assert success, "prepare_models 应该完成而不崩溃"
        # 目标目录应该被创建（即使是空的或只有目录结构）
        assert os.path.isdir(self.setup.target_models_dir), "目标目录应该存在"
        # 子目录应该被创建（即使链接失败）
        checkpoints_dir = os.path.join(self.setup.target_models_dir, "checkpoints")
        assert os.path.isdir(checkpoints_dir), "子目录应该被创建"

class TestModelWatcher:
    """测试 model_watcher 自动同步功能
    
    注意：这些测试需要 watchdog 依赖，并且涉及异步操作
    """
    
    def setup_method(self):
        """每个测试方法执行前的setup
        
        创建以下目录结构和文件:
        test_dir/
        ├── user/models/                # 用户私有模型目录
        │   ├── checkpoints/
        │   │   └── existing.ckpt       # 测试用的用户模型
        │   └── loras/
        ├── shared/models/              # 平台共享模型目录
        │   └── checkpoints/
        │       └── shared.ckpt         # 测试用的共享模型
        └── comfyui/models/             # ComfyUI 实际使用的模型目录
            预期行为: watcher 会监听这个目录的变化
        """
        # del os.environ["AUTO_LAUNCH_SNAPSHOT_NAME"]
        constants.USE_API_MODE = False
        test_dir = tempfile.mkdtemp()
        
        self.setup = SimpleNamespace(
            test_dir=test_dir,
            user_models_dir=os.path.join(test_dir, "user/models"),
            shared_models_dir=os.path.join(test_dir, "shared/models"),
            comfyui_models_dir=os.path.join(test_dir, "comfyui/models")
        )
        
        # 创建初始目录和文件
        os.makedirs(os.path.join(self.setup.user_models_dir, "checkpoints"), exist_ok=True)
        os.makedirs(os.path.join(self.setup.user_models_dir, "loras"), exist_ok=True)
        os.makedirs(os.path.join(self.setup.shared_models_dir, "checkpoints"), exist_ok=True)
        
        _create_test_file(
            os.path.join(self.setup.user_models_dir, "checkpoints/existing.ckpt"),
            "existing_model"
        )
        _create_test_file(
            os.path.join(self.setup.shared_models_dir, "checkpoints/shared.ckpt"),
            "shared_model"
        )
    
    def teardown_method(self):
        """每个测试方法执行后的cleanup"""
        try:
            from services.model.watcher import stop_model_watcher
            stop_model_watcher()
        except:
            pass
        
        if hasattr(self, 'setup') and os.path.exists(self.setup.test_dir):
            shutil.rmtree(self.setup.test_dir)
    
    def test_watcher_started(self):
        """测试 watcher 被正确启动"""
        # 调用 prepare_models，watcher 会自动启动
        prepare_models(
            target_dir=self.setup.comfyui_models_dir,
            user_models_dir=self.setup.user_models_dir,
            shared_models_dir=self.setup.shared_models_dir
        )
        
        # 在 prepare_models 之后导入全局变量
        from services.model.watcher import _comfyui_watcher, _user_poller
        
        # 验证 watcher 已启动
        assert _comfyui_watcher is not None, "ComfyUI watcher 应该被创建"
        assert _comfyui_watcher.is_running, "ComfyUI watcher 应该在运行"
        
        assert _user_poller is not None, "User poller 应该被创建"
        assert _user_poller.is_running, "User poller 应该在运行"
    
    
    @pytest.mark.slow
    def test_create_file_in_comfyui_syncs_to_user(self):
        """测试在 comfyui/models 中创建实体文件，watcher 自动移动到 user_models 并保留软链接
        
        注意：此测试需要等待约 8 秒让 watcher 处理文件
        """
        import time
        
        # 启动 prepare_models，watcher 会自动启动
        prepare_models(
            target_dir=self.setup.comfyui_models_dir,
            user_models_dir=self.setup.user_models_dir,
            shared_models_dir=self.setup.shared_models_dir
        )
        
        # 在 comfyui/models 中创建新的实体文件
        new_file_in_comfyui = os.path.join(
            self.setup.comfyui_models_dir, "loras/new_lora.safetensors"
        )
        _create_test_file(new_file_in_comfyui, "new_lora_content")
        
        # 验证初始是实体文件
        assert not os.path.islink(new_file_in_comfyui), "初始应该是实体文件"
        
        # 等待 watcher 检测并处理（稳定性超时 5秒 + 检查间隔 2秒 + 缓冲）
        time.sleep(8)
        
        # 验证文件已移动到 user_models
        user_file = os.path.join(self.setup.user_models_dir, "loras/new_lora.safetensors")
        assert os.path.exists(user_file), "文件应该存在于 user_models"
        assert not os.path.islink(user_file), "user_models 中应该是实体文件"
        assert _read_file(user_file) == "new_lora_content"
        
        # 验证 comfyui/models 中保留软链接
        assert os.path.islink(new_file_in_comfyui), "comfyui/models 中应该是软链接"
        assert os.readlink(new_file_in_comfyui) == user_file, "应该链接到 user_models"
        assert _read_file(new_file_in_comfyui) == "new_lora_content"
    
    def test_delete_symlink_in_comfyui_preserves_user_file(self):
        """测试删除 comfyui/models 中的软链接，user_models 中的文件保留"""
        # 启动 prepare_models
        prepare_models(
            target_dir=self.setup.comfyui_models_dir,
            user_models_dir=self.setup.user_models_dir,
            shared_models_dir=self.setup.shared_models_dir
        )
        
        comfyui_file = os.path.join(self.setup.comfyui_models_dir, "checkpoints/existing.ckpt")
        user_file = os.path.join(self.setup.user_models_dir, "checkpoints/existing.ckpt")
        
        assert os.path.islink(comfyui_file), "应该是软链接"
        original_content = _read_file(user_file)
        
        # 删除 comfyui 中的软链接
        os.remove(comfyui_file)
        
        # user_models 中的文件应该保留
        assert os.path.exists(user_file), "user_models 中的文件应该保留"
        assert not os.path.islink(user_file), "应该是实体文件"
        assert _read_file(user_file) == original_content, "内容不变"
    

    def test_create_file_in_user_creates_symlink_in_comfyui(self):
        """测试在 user_models 中创建文件，poller 自动在 comfyui/models 中创建软链接
        
        注意：此测试需要等待约 35 秒让 poller 轮询检测文件变化
        """
        import time
        
        # 启动 prepare_models，watcher 会自动启动
        prepare_models(
            target_dir=self.setup.comfyui_models_dir,
            user_models_dir=self.setup.user_models_dir,
            shared_models_dir=self.setup.shared_models_dir
        )
        
        # 等待 poller 完成初始扫描（避免竞态条件）
        time.sleep(1)
        
        # 在 user_models 中创建新文件
        new_user_file = os.path.join(self.setup.user_models_dir, "loras/user_lora.safetensors")
        _create_test_file(new_user_file, "user_lora_content")
        
        # 等待 poller 检测并处理（轮询间隔 30秒）
        time.sleep(33)  # 等待至少一个完整轮询周期 + 缓冲
        
        # 验证 comfyui/models 中创建了软链接
        comfyui_file = os.path.join(self.setup.comfyui_models_dir, "loras/user_lora.safetensors")
        assert os.path.exists(comfyui_file), "comfyui/models 中应该有软链接"
        assert os.path.islink(comfyui_file), "应该是软链接"
        assert os.readlink(comfyui_file) == new_user_file, "应该链接到 user_models"
        assert _read_file(comfyui_file) == "user_lora_content"
    
    
    def test_update_file_in_user_syncs_through_symlink(self):
        """测试修改 user_models 中的文件，comfyui/models 的软链接立即反映变化"""
        # 启动 prepare_models（会创建初始链接）
        prepare_models(
            target_dir=self.setup.comfyui_models_dir,
            user_models_dir=self.setup.user_models_dir,
            shared_models_dir=self.setup.shared_models_dir
        )
        
        # 验证初始链接
        comfyui_file = os.path.join(self.setup.comfyui_models_dir, "checkpoints/existing.ckpt")
        user_file = os.path.join(self.setup.user_models_dir, "checkpoints/existing.ckpt")
        
        assert os.path.islink(comfyui_file), "应该是软链接"
        assert _read_file(comfyui_file) == "existing_model"
        
        # 修改 user_models 中的文件
        _create_test_file(user_file, "updated_content")
        
        # 通过软链接立即读到新内容（不需要等待）
        assert _read_file(comfyui_file) == "updated_content", "软链接应该立即反映文件修改"
    
    def test_delete_file_in_user_removes_symlink_in_comfyui(self):
        """测试删除 user_models 中的文件，poller 自动删除 comfyui/models 中的软链接"""
        import time
        
        # 启动 prepare_models
        prepare_models(
            target_dir=self.setup.comfyui_models_dir,
            user_models_dir=self.setup.user_models_dir,
            shared_models_dir=self.setup.shared_models_dir
        )
        
        comfyui_file = os.path.join(self.setup.comfyui_models_dir, "checkpoints/existing.ckpt")
        user_file = os.path.join(self.setup.user_models_dir, "checkpoints/existing.ckpt")
        
        assert os.path.islink(comfyui_file), "初始应该有软链接"
        
        # 删除 user_models 中的文件
        os.remove(user_file)
        
        # 等待 poller 检测并处理
        time.sleep(35)  # 等待至少一个轮询周期
        
        # 验证 comfyui/models 中的软链接被删除
        assert not os.path.exists(comfyui_file), "软链接应该被删除"

    
    @pytest.mark.slow
    def test_file_moved_from_cache_to_target_syncs_to_user(self):
        """测试文件从 .cache 目录移动到正常目录时，watcher 自动同步到 user_models
        
        模拟 huggingface_cli 下载行为：先下载到 .cache，下载完成后 move 到目标目录
        """
        import time
        
        # 启动 prepare_models 并启用 watcher
        prepare_models(
            target_dir=self.setup.comfyui_models_dir,
            user_models_dir=self.setup.user_models_dir,
            shared_models_dir=self.setup.shared_models_dir
        )
        
        # 创建 .cache 目录（被忽略的目录）
        cache_dir = os.path.join(self.setup.comfyui_models_dir, "checkpoints/.cache")
        os.makedirs(cache_dir, exist_ok=True)
        
        # 在 .cache 目录中创建文件（模拟下载中）
        cache_file = os.path.join(cache_dir, "new_model.safetensors")
        _create_test_file(cache_file, "new_model_content")
        
        # 等待一下，确保 watcher 看到这个文件（但应该被忽略）
        time.sleep(1)
        
        # 将文件从 .cache 移动到正常目录（模拟下载完成）
        target_file = os.path.join(self.setup.comfyui_models_dir, "checkpoints/new_model.safetensors")
        user_file = os.path.join(self.setup.user_models_dir, "checkpoints/new_model.safetensors")
        
        shutil.move(cache_file, target_file)
        
        # 等待 watcher 处理（文件稳定性检查 + 处理时间）
        time.sleep(8)
        
        # 验证文件被同步到 user_models
        assert os.path.exists(user_file), "文件应该被移动到 user_models"
        assert _read_file(user_file) == "new_model_content", "文件内容应该正确"
        
        # 验证 comfyui/models 中现在是软链接
        assert os.path.islink(target_file), "comfyui/models 中应该是软链接"
        assert os.readlink(target_file) == user_file, "软链接应该指向 user_models"