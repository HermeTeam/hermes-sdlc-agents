from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from typing import Iterable, Sequence

from .models import (
    ApprovalRequest,
    RankedTool,
    Resolution,
    RiskAssessment,
    RiskCategory,
    ToolDescriptor,
    ToolSemantics,
)


RISK_WEIGHTS = {
    "read": 5,
    "write": 22,
    "destructive": 35,
    "egress": 24,
    "credential_access": 32,
    "arbitrary_execution": 45,
    "open_world": 18,
}

CATEGORY_FLOORS = (
    (RiskCategory.CRITICAL, 80),
    (RiskCategory.HIGH, 60),
    (RiskCategory.MEDIUM, 35),
    (RiskCategory.LOW, 15),
    (RiskCategory.SAFE, 0),
)


class EmergencyStopActive(RuntimeError):
    pass


def category_for_score(score: int) -> RiskCategory:
    score = max(0, min(100, score))
    for category, floor in CATEGORY_FLOORS:
        if score >= floor:
            return category
    return RiskCategory.SAFE


def assess_risk(tool: ToolDescriptor, semantics: ToolSemantics) -> RiskAssessment:
    """Deterministic floor. Judge output may add flags but may not suppress them."""
    reasons: list[str] = []
    score = 0
    for field_name, weight in RISK_WEIGHTS.items():
        if bool(getattr(semantics, field_name)):
            score += weight
            reasons.append(f"{field_name}:+{weight}")

    # Treat externally supplied MCP annotations as evidence only, never as authority.
    if tool.annotations.get("destructiveHint") is True and not semantics.destructive:
        score += 20
        reasons.append("mcp_destructive_hint:+20")
    if tool.annotations.get("readOnlyHint") is False and not semantics.write:
        score += 8
        reasons.append("mcp_not_readonly_hint:+8")

    score = min(score, 100)
    return RiskAssessment(
        tool_id=tool.tool_id,
        canonical_capability=semantics.canonical_capability,
        score=score,
        category=category_for_score(score),
        properties=semantics,
        reasons=tuple(reasons),
        judge_confidence=semantics.confidence,
    )


def privilege_vector(semantics: ToolSemantics) -> tuple[int, ...]:
    return (
        int(semantics.arbitrary_execution),
        int(semantics.destructive),
        int(semantics.credential_access),
        int(semantics.egress),
        int(semantics.write),
        int(semantics.open_world),
        int(semantics.read),
    )


def dominates(safer: RankedTool, other: RankedTool, fit_tolerance: float = 0.08) -> bool:
    """A candidate dominates another when it satisfies the intent nearly as well
    while having no greater privilege and strictly lower risk.
    """
    if safer.intent_fit + fit_tolerance < other.intent_fit:
        return False
    if safer.assessment.score >= other.assessment.score:
        return False
    a = privilege_vector(safer.assessment.properties)
    b = privilege_vector(other.assessment.properties)
    return all(x <= y for x, y in zip(a, b, strict=True))


def mark_dominated(candidates: Sequence[RankedTool]) -> tuple[RankedTool, ...]:
    output: list[RankedTool] = []
    for candidate in candidates:
        dominator = next(
            (
                other
                for other in candidates
                if other.tool.tool_id != candidate.tool.tool_id and dominates(other, candidate)
            ),
            None,
        )
        output.append(
            replace(
                candidate,
                dominated=dominator is not None,
                dominance_reason=(
                    f"{dominator.tool.tool_id} satisfies the intent with lower privilege/risk"
                    if dominator
                    else None
                ),
            )
        )
    return tuple(output)


def _request_id(intent: str, tool_id: str) -> str:
    return sha256(f"{intent}\0{tool_id}".encode("utf-8")).hexdigest()[:24]


def resolve(
    *,
    intent: str,
    candidates: Iterable[RankedTool],
    max_auto_category: RiskCategory,
    requested_tool_id: str | None = None,
    allowed_once: frozenset[str] = frozenset(),
    exception_tools: frozenset[str] = frozenset(),
    capability_overrides: dict[str, RiskCategory] | None = None,
    emergency_stop: bool = False,
) -> Resolution:
    if emergency_stop:
        return Resolution(
            intent=intent,
            selected=None,
            visible_tools=(),
            filtered_tools=tuple(candidates),
            approval_required=None,
            emergency_stop=True,
        )

    capability_overrides = capability_overrides or {}
    marked = mark_dominated(tuple(candidates))

    def effective_category(candidate: RankedTool) -> RiskCategory:
        return capability_overrides.get(
            candidate.assessment.canonical_capability,
            candidate.assessment.category,
        )

    eligible: list[RankedTool] = []
    filtered: list[RankedTool] = []
    for candidate in marked:
        exempt = candidate.tool.tool_id in exception_tools
        permitted = effective_category(candidate) <= max_auto_category
        if not candidate.dominated and (permitted or exempt):
            eligible.append(candidate)
        else:
            filtered.append(candidate)

    eligible.sort(key=lambda item: (-item.intent_fit, item.assessment.score, item.tool.tool_id))
    selected = eligible[0] if eligible else None

    requested = next(
        (item for item in marked if item.tool.tool_id == requested_tool_id),
        None,
    )
    approval: ApprovalRequest | None = None
    if requested is not None:
        effective = effective_category(requested)
        over_limit = effective > max_auto_category
        already_allowed = requested.tool.tool_id in allowed_once or requested.tool.tool_id in exception_tools
        if over_limit and not already_allowed:
            approval = ApprovalRequest(
                request_id=_request_id(intent, requested.tool.tool_id),
                intent=intent,
                requested_tool_id=requested.tool.tool_id,
                requested_category=effective,
                allowed_category=max_auto_category,
                recommended_tool_id=selected.tool.tool_id if selected else None,
                reason=(
                    "requested tool exceeds configured risk ceiling; explicit human authority is required"
                ),
            )
            selected = None

    return Resolution(
        intent=intent,
        selected=selected,
        visible_tools=tuple(eligible),
        filtered_tools=tuple(filtered),
        approval_required=approval,
        emergency_stop=False,
    )
