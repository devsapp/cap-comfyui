"""
prompt_utils 单元测试
测试 infer_outputs_to_execute：从工作流节点字典推断输出节点 id 列表（与原生 ComfyUI validate_prompt 语义对齐）
"""
import pytest

from services.gateway.task.utils.prompt_utils import (
    KNOWN_OUTPUT_NODE_CLASS_TYPES,
    infer_outputs_to_execute,
)


class TestInferOutputsToExecute:
    def test_returns_known_output_node_ids(self):
        """已知输出节点类型（SaveImage 等）被收入结果"""
        prompt_dict = {
            "1": {"class_type": "KSampler"},
            "2": {"class_type": "SaveImage"},
            "3": {"class_type": "PreviewImage"},
        }
        result = infer_outputs_to_execute(prompt_dict)
        assert set(result) == {"2", "3"}

    def test_excludes_non_output_nodes(self):
        """非输出节点不出现在结果中"""
        prompt_dict = {
            "1": {"class_type": "KSampler"},
            "2": {"class_type": "CLIPTextEncode"},
        }
        assert infer_outputs_to_execute(prompt_dict) == []

    def test_all_known_output_types_are_collected(self):
        """KNOWN_OUTPUT_NODE_CLASS_TYPES 中每种类型都能被推断到"""
        prompt_dict = {str(i): {"class_type": ct} for i, ct in enumerate(KNOWN_OUTPUT_NODE_CLASS_TYPES)}
        result = infer_outputs_to_execute(prompt_dict)
        assert len(result) == len(KNOWN_OUTPUT_NODE_CLASS_TYPES)

    def test_empty_dict_returns_empty_list(self):
        assert infer_outputs_to_execute({}) == []

    def test_non_dict_input_returns_empty_list(self):
        assert infer_outputs_to_execute(None) == []
        assert infer_outputs_to_execute([]) == []
        assert infer_outputs_to_execute("bad") == []

    def test_node_without_class_type_is_skipped(self):
        """节点缺少 class_type 字段时跳过，不报错"""
        prompt_dict = {
            "1": {"inputs": {}},
            "2": {"class_type": "SaveImage"},
        }
        assert infer_outputs_to_execute(prompt_dict) == ["2"]

    def test_node_value_not_dict_is_skipped(self):
        """节点值不是 dict 时跳过，不报错"""
        prompt_dict = {
            "1": "bad_value",
            "2": {"class_type": "SaveImage"},
        }
        assert infer_outputs_to_execute(prompt_dict) == ["2"]

    def test_unknown_output_type_is_excluded(self):
        """未知的 class_type 不被视为输出节点"""
        prompt_dict = {"1": {"class_type": "CustomOutputNode"}}
        assert infer_outputs_to_execute(prompt_dict) == []
