"""
shared_models 单元测试
测试共享模型配置功能

测试覆盖：
==============================================================================

## 1. TestSetupExtraModelPaths - 主函数测试（5个用例）
    - test_create_new_extra_model_paths_yaml
      测试用例1: comfyui_dir 下没有 extra_model_paths.yaml
      验证：创建新文件并包含正确的配置内容
    
    - test_append_config_to_existing_file
      测试用例2: 有 extra_model_paths.yaml 但没有 funart_shared_models 配置
      验证：追加配置到文件末尾，保留原有配置
    
    - test_update_existing_config
      测试用例3: 有 extra_model_paths.yaml 且有 funart_shared_models 配置
      验证：更新配置（删除旧配置，追加新配置），支持新增模型目录
    
    - test_skip_when_comfyui_dir_not_exists
      边界条件：ComfyUI 目录不存在时跳过
    
    - test_skip_when_shared_models_dir_not_exists
      边界条件：共享模型目录不存在时跳过

## 2. TestGenerateConfig - 配置生成测试（3个用例）
    - test_generate_config_with_directories_and_files
      测试用例4: shared_models_dir 有目录也有文件
      验证：只把目录写到配置中，忽略文件
    
    - test_generate_config_with_empty_directory
      边界条件：空目录生成基本配置（只有 header，没有子目录）
    
    - test_generate_config_subdirectories_sorted
      功能测试：子目录按字母顺序排序

## 3. TestUpdateConfigFile - 更新配置测试（6个用例）
    - test_update_config_file_basic
      测试用例5: 更新配置文件 - 基本功能
      验证：删除中间的旧配置块，追加新配置到末尾，保留其他配置
    
    - test_update_config_file_at_beginning
      边界条件：更新文件开头的配置块
    
    - test_update_config_file_at_end
      边界条件：更新文件末尾的配置块
    
    - test_update_nonexistent_config
      边界条件：尝试更新不存在的配置（不做任何操作）
    
    - test_remove_config_block
      功能测试：删除配置块
    
    - test_remove_nonexistent_config_block
      边界条件：删除不存在的配置块（返回 False）

## 4. TestConfigExists - 配置检查测试（3个用例）
    - test_config_exists_true: 配置存在
    - test_config_exists_false: 配置不存在
    - test_config_exists_empty_file: 空文件

## 5. TestWriteYamlBlock - YAML 写入测试（3个用例）
    - test_write_new_file: 创建新文件（append=False）
    - test_append_to_file: 追加到文件（append=True）
    - test_overwrite_file: 覆盖文件（append=False）

"""

import os
import tempfile
import shutil
import pytest
from services.model.shared_models import (
    setup_shared_models,
    _generate_config,
    _config_exists,
    _write_yaml_block,
    _remove_config_block,
    _update_config_file
)


class TestSetupExtraModelPaths:
    """测试 setup_shared_models 函数"""
    
    def setup_method(self):
        """每个测试方法执行前的setup"""
        # 创建临时目录
        self.test_dir = tempfile.mkdtemp()
        self.comfyui_dir = os.path.join(self.test_dir, "comfyui")
        self.shared_models_dir = os.path.join(self.test_dir, "shared", "models")
        
        # 创建目录结构
        os.makedirs(self.comfyui_dir, exist_ok=True)
        os.makedirs(self.shared_models_dir, exist_ok=True)
        
        # 在 shared_models_dir 中创建一些模型子目录
        os.makedirs(os.path.join(self.shared_models_dir, "checkpoints"))
        os.makedirs(os.path.join(self.shared_models_dir, "loras"))
        os.makedirs(os.path.join(self.shared_models_dir, "vae"))
    
    def teardown_method(self):
        """每个测试方法执行后的cleanup"""
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
    
    def test_create_new_extra_model_paths_yaml(self):
        """测试用例1: comfyui_dir 下没有 extra_model_paths.yaml - 创建新文件"""
        extra_paths_file = os.path.join(self.comfyui_dir, "extra_model_paths.yaml")
        
        # 确认文件不存在
        assert not os.path.exists(extra_paths_file)
        
        # 执行
        setup_shared_models(
            comfyui_dir=self.comfyui_dir,
            shared_models_dir=self.shared_models_dir,
            config_key="funart_shared_models"
        )
        
        # 验证文件已创建
        assert os.path.exists(extra_paths_file)
        
        # 构建预期的完整内容
        expected_content = f"""funart_shared_models:
    base_path: {self.shared_models_dir}
    is_default: false

    checkpoints: checkpoints/
    loras: loras/
    vae: vae/
"""
        
        # 验证文件内容完全匹配
        with open(extra_paths_file, 'r') as f:
            actual_content = f.read()
        
        assert actual_content == expected_content, f"Expected:\n{expected_content}\n\nActual:\n{actual_content}"
    
    def test_append_config_to_existing_file(self):
        """测试用例2: 有 extra_model_paths.yaml 但没有 funart_shared_models - 追加配置"""
        extra_paths_file = os.path.join(self.comfyui_dir, "extra_model_paths.yaml")
        
        # 创建已存在的配置文件（有其他配置）
        existing_content = """other_config:
    base_path: /other/path
    checkpoints: checkpoints/
"""
        with open(extra_paths_file, 'w') as f:
            f.write(existing_content)
        
        # 执行
        setup_shared_models(
            comfyui_dir=self.comfyui_dir,
            shared_models_dir=self.shared_models_dir,
            config_key="funart_shared_models"
        )
        
        # 构建预期的完整内容（原有配置 + 新配置）
        expected_content = f"""other_config:
    base_path: /other/path
    checkpoints: checkpoints/

funart_shared_models:
    base_path: {self.shared_models_dir}
    is_default: false

    checkpoints: checkpoints/
    loras: loras/
    vae: vae/
"""
        
        # 验证文件内容完全匹配
        with open(extra_paths_file, 'r') as f:
            actual_content = f.read()
        
        assert actual_content == expected_content, f"Expected:\n{expected_content}\n\nActual:\n{actual_content}"
    
    def test_update_existing_config(self):
        """测试用例3: 有 extra_model_paths.yaml 且有 funart_shared_models - 更新配置"""
        extra_paths_file = os.path.join(self.comfyui_dir, "extra_model_paths.yaml")
        
        # 创建已存在的配置文件（有旧的 funart_shared_models 配置）
        existing_content = """funart_shared_models:
    base_path: /old/path
    checkpoints: checkpoints/

other_config:
    base_path: /other/path
"""
        with open(extra_paths_file, 'w') as f:
            f.write(existing_content)
        
        # 在 shared_models_dir 中新增一个目录
        os.makedirs(os.path.join(self.shared_models_dir, "controlnet"))
        
        # 执行
        setup_shared_models(
            comfyui_dir=self.comfyui_dir,
            shared_models_dir=self.shared_models_dir,
            config_key="funart_shared_models"
        )
        
        # 构建预期的完整内容（删除旧配置，保留其他配置，追加新配置到末尾）
        expected_content = f"""other_config:
    base_path: /other/path

funart_shared_models:
    base_path: {self.shared_models_dir}
    is_default: false

    checkpoints: checkpoints/
    controlnet: controlnet/
    loras: loras/
    vae: vae/
"""
        
        # 验证文件内容完全匹配
        with open(extra_paths_file, 'r') as f:
            actual_content = f.read()
        
        assert actual_content == expected_content, f"Expected:\n{expected_content}\n\nActual:\n{actual_content}"
    
    def test_skip_when_comfyui_dir_not_exists(self):
        """测试：ComfyUI 目录不存在时跳过"""
        non_existent_dir = os.path.join(self.test_dir, "non_existent")
        
        # 执行（不应该抛出异常）
        setup_shared_models(
            comfyui_dir=non_existent_dir,
            shared_models_dir=self.shared_models_dir,
            config_key="funart_shared_models"
        )
        
        # 不应该创建任何文件
        assert not os.path.exists(os.path.join(non_existent_dir, "extra_model_paths.yaml"))
    
    def test_skip_when_shared_models_dir_not_exists(self):
        """测试：共享模型目录不存在时跳过"""
        non_existent_dir = os.path.join(self.test_dir, "non_existent_models")
        extra_paths_file = os.path.join(self.comfyui_dir, "extra_model_paths.yaml")
        
        # 执行（不应该抛出异常）
        setup_shared_models(
            comfyui_dir=self.comfyui_dir,
            shared_models_dir=non_existent_dir,
            config_key="funart_shared_models"
        )
        
        # 不应该创建配置文件
        assert not os.path.exists(extra_paths_file)


class TestGenerateConfig:
    """测试 _generate_config 函数"""
    
    def setup_method(self):
        """每个测试方法执行前的setup"""
        self.test_dir = tempfile.mkdtemp()
        self.shared_models_dir = os.path.join(self.test_dir, "models")
        os.makedirs(self.shared_models_dir)
    
    def teardown_method(self):
        """每个测试方法执行后的cleanup"""
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
    
    def test_generate_config_with_directories_and_files(self):
        """测试用例4: shared_models_dir 有目录也有文件 - 只把目录写到配置中"""
        # 创建目录和文件
        os.makedirs(os.path.join(self.shared_models_dir, "checkpoints"))
        os.makedirs(os.path.join(self.shared_models_dir, "loras"))
        
        # 创建一些文件（应该被忽略）
        with open(os.path.join(self.shared_models_dir, "README.md"), 'w') as f:
            f.write("test")
        with open(os.path.join(self.shared_models_dir, "config.json"), 'w') as f:
            f.write("{}")
        
        # 执行
        config = _generate_config(self.shared_models_dir, "test_config")
        
        # 构建预期的完整配置（只包含目录，不包含文件）
        expected_config = f"""test_config:
    base_path: {self.shared_models_dir}
    is_default: false

    checkpoints: checkpoints/
    loras: loras/"""
        
        # 验证配置完全匹配
        assert config == expected_config, f"Expected:\n{expected_config}\n\nActual:\n{config}"
    
    def test_generate_config_with_empty_directory(self):
        """测试：空目录生成基本配置"""
        config = _generate_config(self.shared_models_dir, "test_config")
        
        # 构建预期的完整配置（空目录，只有基本配置）
        expected_config = f"""test_config:
    base_path: {self.shared_models_dir}
    is_default: false
"""
        
        # 验证配置完全匹配
        assert config == expected_config, f"Expected:\n{expected_config}\n\nActual:\n{config}"
    
    def test_generate_config_subdirectories_sorted(self):
        """测试：子目录按字母顺序排序"""
        # 创建目录（故意乱序）
        os.makedirs(os.path.join(self.shared_models_dir, "vae"))
        os.makedirs(os.path.join(self.shared_models_dir, "checkpoints"))
        os.makedirs(os.path.join(self.shared_models_dir, "loras"))
        
        config = _generate_config(self.shared_models_dir, "test_config")
        
        # 构建预期的完整配置（按字母顺序排列）
        expected_config = f"""test_config:
    base_path: {self.shared_models_dir}
    is_default: false

    checkpoints: checkpoints/
    loras: loras/
    vae: vae/"""
        
        # 验证配置完全匹配
        assert config == expected_config, f"Expected:\n{expected_config}\n\nActual:\n{config}"


class TestUpdateConfigFile:
    """测试 _update_config_file 和相关函数"""
    
    def setup_method(self):
        """每个测试方法执行前的setup"""
        self.test_dir = tempfile.mkdtemp()
        self.config_file = os.path.join(self.test_dir, "test_config.yaml")
    
    def teardown_method(self):
        """每个测试方法执行后的cleanup"""
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
    
    def test_update_config_file_basic(self):
        """测试用例5: 更新配置文件 - 基本功能"""
        # 创建初始配置
        initial_content = """first_config:
    base_path: /first
    checkpoints: checkpoints/

funart_shared_models:
    base_path: /old
    checkpoints: checkpoints/

last_config:
    base_path: /last
"""
        with open(self.config_file, 'w') as f:
            f.write(initial_content)
        
        # 新配置
        new_yaml_block = """funart_shared_models:
    base_path: /new
    checkpoints: checkpoints/
    loras: loras/
    vae: vae/"""
        
        # 执行更新
        _update_config_file(self.config_file, "funart_shared_models", new_yaml_block)
        
        # 构建预期的完整内容（删除中间的旧配置，保留前后配置，新配置追加到末尾）
        expected_content = """first_config:
    base_path: /first
    checkpoints: checkpoints/

last_config:
    base_path: /last

funart_shared_models:
    base_path: /new
    checkpoints: checkpoints/
    loras: loras/
    vae: vae/
"""
        
        # 验证文件内容完全匹配
        with open(self.config_file, 'r') as f:
            actual_content = f.read()
        
        assert actual_content == expected_content, f"Expected:\n{expected_content}\n\nActual:\n{actual_content}"
    
    def test_update_config_file_at_beginning(self):
        """测试：更新文件开头的配置块"""
        initial_content = """funart_shared_models:
    base_path: /old
    checkpoints: checkpoints/

other_config:
    base_path: /other
"""
        with open(self.config_file, 'w') as f:
            f.write(initial_content)
        
        new_yaml_block = """funart_shared_models:
    base_path: /new
    loras: loras/"""
        
        _update_config_file(self.config_file, "funart_shared_models", new_yaml_block)
        
        # 构建预期的完整内容（删除开头的配置，保留其他，新配置追加到末尾）
        expected_content = """other_config:
    base_path: /other

funart_shared_models:
    base_path: /new
    loras: loras/
"""
        
        # 验证文件内容完全匹配
        with open(self.config_file, 'r') as f:
            actual_content = f.read()
        
        assert actual_content == expected_content, f"Expected:\n{expected_content}\n\nActual:\n{actual_content}"
    
    def test_update_config_file_at_end(self):
        """测试：更新文件末尾的配置块"""
        initial_content = """other_config:
    base_path: /other

funart_shared_models:
    base_path: /old
    checkpoints: checkpoints/"""
        
        with open(self.config_file, 'w') as f:
            f.write(initial_content)
        
        new_yaml_block = """funart_shared_models:
    base_path: /new
    vae: vae/"""
        
        _update_config_file(self.config_file, "funart_shared_models", new_yaml_block)
        
        # 构建预期的完整内容
        # 注意：删除后留下的空行 + append 模式添加的空行 = 两个空行
        expected_content = """other_config:
    base_path: /other


funart_shared_models:
    base_path: /new
    vae: vae/
"""
        
        # 验证文件内容完全匹配
        with open(self.config_file, 'r') as f:
            actual_content = f.read()
        
        assert actual_content == expected_content, f"Expected:\n{expected_content}\n\nActual:\n{actual_content}"
    
    def test_update_nonexistent_config(self):
        """测试：更新不存在的配置（应该不做任何操作）"""
        initial_content = """other_config:
    base_path: /other
"""
        with open(self.config_file, 'w') as f:
            f.write(initial_content)
        
        new_yaml_block = """funart_shared_models:
    base_path: /new"""
        
        # 执行（不应该抛出异常）
        _update_config_file(self.config_file, "funart_shared_models", new_yaml_block)
        
        # 原内容应该保持不变（因为找不到要更新的配置）
        with open(self.config_file, 'r') as f:
            actual_content = f.read()
        
        assert actual_content == initial_content, f"Expected:\n{initial_content}\n\nActual:\n{actual_content}"
        # 注意：因为没找到配置，所以返回了，不会追加
        # 如果需要追加，应该使用 append 逻辑
    
    def test_remove_config_block(self):
        """测试：删除配置块"""
        initial_content = """first_config:
    base_path: /first

funart_shared_models:
    base_path: /middle
    checkpoints: checkpoints/

last_config:
    base_path: /last
"""
        with open(self.config_file, 'w') as f:
            f.write(initial_content)
        
        # 删除配置块
        result = _remove_config_block(self.config_file, "funart_shared_models")
        
        assert result is True
        
        # 构建预期的完整内容（删除中间的配置块）
        expected_content = """first_config:
    base_path: /first

last_config:
    base_path: /last
"""
        
        # 验证文件内容完全匹配
        with open(self.config_file, 'r') as f:
            actual_content = f.read()
        
        assert actual_content == expected_content, f"Expected:\n{expected_content}\n\nActual:\n{actual_content}"
    
    def test_remove_nonexistent_config_block(self):
        """测试：删除不存在的配置块"""
        initial_content = """other_config:
    base_path: /other
"""
        with open(self.config_file, 'w') as f:
            f.write(initial_content)
        
        result = _remove_config_block(self.config_file, "nonexistent_config")
        
        assert result is False
        
        # 文件内容应该保持不变
        with open(self.config_file, 'r') as f:
            content = f.read()
        
        assert content == initial_content


class TestConfigExists:
    """测试 _config_exists 函数"""
    
    def setup_method(self):
        """每个测试方法执行前的setup"""
        self.test_dir = tempfile.mkdtemp()
        self.config_file = os.path.join(self.test_dir, "test_config.yaml")
    
    def teardown_method(self):
        """每个测试方法执行后的cleanup"""
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
    
    def test_config_exists_true(self):
        """测试：配置存在"""
        content = """funart_shared_models:
    base_path: /path
"""
        with open(self.config_file, 'w') as f:
            f.write(content)
        
        assert _config_exists(self.config_file, "funart_shared_models") is True
    
    def test_config_exists_false(self):
        """测试：配置不存在"""
        content = """other_config:
    base_path: /path
"""
        with open(self.config_file, 'w') as f:
            f.write(content)
        
        assert _config_exists(self.config_file, "funart_shared_models") is False
    
    def test_config_exists_empty_file(self):
        """测试：空文件"""
        with open(self.config_file, 'w') as f:
            f.write("")
        
        assert _config_exists(self.config_file, "funart_shared_models") is False


class TestWriteYamlBlock:
    """测试 _write_yaml_block 函数"""
    
    def setup_method(self):
        """每个测试方法执行前的setup"""
        self.test_dir = tempfile.mkdtemp()
        self.config_file = os.path.join(self.test_dir, "test_config.yaml")
    
    def teardown_method(self):
        """每个测试方法执行后的cleanup"""
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
    
    def test_write_new_file(self):
        """测试：创建新文件（append=False）"""
        # 输入的 YAML 块（不包含末尾换行）
        yaml_block = """test_config:
    base_path: /test
    checkpoints: checkpoints/"""
        
        _write_yaml_block(self.config_file, yaml_block, append=False)
        
        # 构建预期的完整内容（_write_yaml_block 会自动添加末尾换行）
        expected_content = """test_config:
    base_path: /test
    checkpoints: checkpoints/
"""
        
        # 验证文件内容完全匹配
        with open(self.config_file, 'r') as f:
            actual_content = f.read()
        
        assert actual_content == expected_content, f"Expected:\n{expected_content}\n\nActual:\n{actual_content}"
    
    def test_append_to_file(self):
        """测试：追加到文件（append=True）"""
        # 先创建文件
        initial_content = """first_config:
    base_path: /first
"""
        with open(self.config_file, 'w') as f:
            f.write(initial_content)
        
        # 追加内容
        yaml_block = """second_config:
    base_path: /second"""
        
        _write_yaml_block(self.config_file, yaml_block, append=True)
        
        # 构建预期的完整内容（原内容 + 空行 + 新内容 + 换行）
        expected_content = """first_config:
    base_path: /first

second_config:
    base_path: /second
"""
        
        # 验证文件内容完全匹配
        with open(self.config_file, 'r') as f:
            actual_content = f.read()
        
        assert actual_content == expected_content, f"Expected:\n{expected_content}\n\nActual:\n{actual_content}"
    
    def test_overwrite_file(self):
        """测试：覆盖文件（append=False）"""
        # 先创建文件
        with open(self.config_file, 'w') as f:
            f.write("old content")
        
        # 覆盖
        yaml_block = """new_config:
    base_path: /new"""
        
        _write_yaml_block(self.config_file, yaml_block, append=False)
        
        # 构建预期的完整内容（旧内容被覆盖）
        expected_content = """new_config:
    base_path: /new
"""
        
        # 验证文件内容完全匹配
        with open(self.config_file, 'r') as f:
            actual_content = f.read()
        
        assert actual_content == expected_content, f"Expected:\n{expected_content}\n\nActual:\n{actual_content}"

