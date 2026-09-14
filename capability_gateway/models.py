from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Mapping, Sequence


class RiskCategory(IntEnum):
    SAFE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

    @classmethod
    def parse(cls, value: str) -> "RiskCategory":
        normalized = value.strip().upper()
        try:
            return cls[normalized]
        except KeyError as exc:
            raise ValueError(f"unsupported risk category: {value}") from exc


@dataclass(frozen=True)
class ToolDescriptor:
    server_id: str
    tool_name: str
    description: str
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    annotations: Mapping[str, Any] = field(default_factory=dict)
    source: str = "unknown"
    version: str | None = None

    @property
    def tool_id(self) -> str:
        return f"{self.server_id}:{self.tool_name}"


@dataclass(frozen=True)
class ToolSemantics:
    canonical_capability: str
    read: bool
    write: bool
    destructive: bool
    egress: bool
    credential_access: bool
    arbitrary_execution: bool
    open_world: bool
    rationale: str
    confidence: float


@dataclass(frozen=True)
class RiskAssessment:
    tool_id: str
    canonical_capability: str
    score: int
    category: RiskCategory
    properties: ToolSemantics
    reasons: Sequence[str]
    judge_confidence: float


@dataclass(frozen=True)
class RankedTool:
    tool: ToolDescriptor
    assessment: RiskAssessment
    intent_fit: float
    dominated: bool
    dominance_reason: str | None = None


@dataclass(frozen=True)
class ApprovalRequest:
    request_id: str
    intent: str
    requested_tool_id: str
    requested_category: RiskCategory
    allowed_category: RiskCategory
    recommended_tool_id: str | None
    reason: str


@dataclass(frozen=True)
class Resolution:
    intent: str
    selected: RankedTool | None
    visible_tools: Sequence[RankedTool]
    filtered_tools: Sequence[RankedTool]
    approval_required: ApprovalRequest | None
    emergency_stop: bool
