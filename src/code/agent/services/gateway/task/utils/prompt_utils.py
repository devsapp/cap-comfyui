"""
Prompt 工具函数
提供与 ComfyUI prompt（工作流节点字典）相关的纯工具函数，供 history_manager、queue_handler 等多处共用。
"""
from typing import Any, List, Tuple

# 与原生 ComfyUI 一致：outputs_to_execute 由服务端推断。原生见 execution.py validate_prompt，
# 收集 class_.OUTPUT_NODE is True 的节点。此处用常见输出节点 class_type 做推断（无 NODE_CLASS_MAPPINGS 时）
KNOWN_OUTPUT_NODE_CLASS_TYPES = frozenset({
    "SaveImage", "PreviewImage", "SaveImageToFolder",
    "SaveAnimatedWEBP", "SaveAnimatedPNG", "SaveAnimatedGIF",
    "VHS_VideoCombine", "VHS_VideoCombineMerge", "SaveVideo",
})


def infer_outputs_to_execute(prompt_dict: dict) -> List[str]:
    """
    从工作流节点字典推断输出节点 id 列表（与原生 ComfyUI validate_prompt 语义对齐：
    原生见 execution.py 1051-1053 行，收集 OUTPUT_NODE 为 True 的节点）。
    """
    if not isinstance(prompt_dict, dict):
        return []
    out = []
    for node_id, node_data in prompt_dict.items():
        if not isinstance(node_data, dict):
            continue
        class_type = node_data.get("class_type")
        if class_type and class_type in KNOWN_OUTPUT_NODE_CLASS_TYPES:
            out.append(node_id)
    return out


def parse_prompt_body(prompt_body: Any, client_id: str = "") -> Tuple[dict, List[str], dict]:
    """
    从 prompt_body 解析 (prompt_dict, outputs_to_execute, extra_data)。
    支持两种格式：
      - 嵌套格式：{prompt: {...}, outputs_to_execute: [...], extra_data: {...}}
      - 直接格式：{node_id: {...}, ...}（节点定义字典）
    extra_data 不含 create_time，由调用方按需填充。
    """
    prompt_dict = prompt_body or {}
    outputs_to_execute = []

    if isinstance(prompt_dict, dict):
        if "prompt" in prompt_dict and isinstance(prompt_dict.get("prompt"), dict):
            outputs_to_execute = prompt_dict.get("outputs_to_execute", [])
            prompt_dict = prompt_dict["prompt"]

    if not outputs_to_execute and isinstance(prompt_dict, dict):
        outputs_to_execute = infer_outputs_to_execute(prompt_dict)

    raw = prompt_body if isinstance(prompt_body, dict) else {}
    extra_data = dict(raw.get("extra_data", {})) if isinstance(raw.get("extra_data"), dict) else {}
    if client_id:
        extra_data["client_id"] = client_id

    return prompt_dict, outputs_to_execute, extra_data
