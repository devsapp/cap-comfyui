# Git clone service models (see DESIGN.md).
from typing import Optional

from pydantic import BaseModel, field_validator


# ── nodes_map 输入模型（与 DESIGN.md value 结构完全对应） ─────────────────────

class NodeSource(BaseModel):
    """与 nodes_map value.source 一致"""

    type: str  # 来源类型，必填（如 "github"）
    webUrl: Optional[str] = None
    cloneUrl: Optional[str] = None


class NodeVersion(BaseModel):
    """与 nodes_map value.version 一致"""

    type: Optional[str] = None
    value: Optional[str] = None


class NodeMapValue(BaseModel):
    """与 nodes_map 的 value 结构一致：name, source, version"""

    name: str
    source: NodeSource
    version: Optional[NodeVersion] = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("name must not be empty")
        return v


# ── 结果输出模型 ──────────────────────────────────────────────────────────────

# details 中每个插件条目的 status 取值
STATUS_CLONED = "cloned"
STATUS_SKIPPED = "skipped"
STATUS_OVERRIDDEN = "overridden"
STATUS_FAILED = "failed"


class CloneDetail(BaseModel):
    """单插件 clone 结果明细，对应返回结构中的 details[plugin_name]"""

    status: str  # STATUS_CLONED | STATUS_SKIPPED | STATUS_OVERRIDDEN | STATUS_FAILED
    duration: float = 0.0
    path: Optional[str] = None
    previous_path: Optional[str] = None  # override 时原目录路径
    reason: Optional[str] = None  # skipped 时原因，如 "directory_exists"
    error_msg: Optional[str] = None  # failed 时错误信息

    def to_dict(self) -> dict:
        return self.model_dump(exclude_none=True)


class CloneSummary(BaseModel):
    """clone_all 返回的 summary 部分"""

    total: int = 0
    cloned: int = 0
    skipped: int = 0
    overridden: int = 0
    failed: int = 0
    duration: float = 0.0

    def to_dict(self) -> dict:
        return self.model_dump()
