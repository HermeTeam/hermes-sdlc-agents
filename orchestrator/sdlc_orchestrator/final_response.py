from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .statuses import FinalStatus, validate_final_status


class FinalResponseError(ValueError):
    """Raised when a Hermes run does not return the strict final response contract."""


@dataclass(frozen=True)
class FinalResponse:
    assignment_key: str
    role: str
    final_status: FinalStatus
    summary: str
    evidence: list[dict[str, Any]]
    decision_log: list[str]
    risks: list[str]
    assumptions: list[str]
    next_handoff: dict[str, Any] | None = None
    block_reason: str | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "assignment_key": self.assignment_key,
                "role": self.role,
                "final_status": self.final_status.value,
                "summary": self.summary,
                "evidence": self.evidence,
                "decision_log": self.decision_log,
                "risks": self.risks,
                "assumptions": self.assumptions,
                "next_handoff": self.next_handoff,
                "block_reason": self.block_reason,
            },
            ensure_ascii=False,
            sort_keys=True,
        )


def parse_final_response(payload: dict, *, expected_role: str, expected_assignment_key: str) -> FinalResponse:
    data = _extract_json_object(payload)
    assignment_key = _required_str(data, "assignment_key")
    role = _required_str(data, "role")
    final_status_value = _required_str(data, "final_status")
    summary = _required_str(data, "summary")
    evidence = data.get("evidence")
    if evidence is None:
        evidence = []
    if not isinstance(evidence, list) or not all(isinstance(item, dict) for item in evidence):
        raise FinalResponseError("evidence must be a list of objects")
    decision_log = _optional_str_list(data, "decision_log")
    risks = _optional_str_list(data, "risks")
    assumptions = _optional_str_list(data, "assumptions")
    if assignment_key != expected_assignment_key:
        raise FinalResponseError("assignment_key mismatch")
    if role != expected_role:
        raise FinalResponseError("role mismatch")
    try:
        final_status = validate_final_status(role, final_status_value)
    except ValueError as exc:
        raise FinalResponseError(str(exc)) from exc
    next_handoff = data.get("next_handoff")
    if next_handoff is not None and not isinstance(next_handoff, dict):
        raise FinalResponseError("next_handoff must be an object or null")
    block_reason = data.get("block_reason")
    if block_reason is not None and not isinstance(block_reason, str):
        raise FinalResponseError("block_reason must be a string or null")
    return FinalResponse(
        assignment_key=assignment_key,
        role=role,
        final_status=final_status,
        summary=summary,
        evidence=evidence,
        decision_log=decision_log,
        risks=risks,
        assumptions=assumptions,
        next_handoff=next_handoff,
        block_reason=block_reason,
    )


def _extract_json_object(payload: dict) -> dict:
    for key in ("final_response", "output", "result", "response", "text"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value.strip():
            text = value.strip()
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise FinalResponseError(f"{key} is not valid JSON") from exc
            if not isinstance(parsed, dict):
                raise FinalResponseError(f"{key} JSON must be an object")
            return parsed
    raise FinalResponseError("final response JSON object not found")


def _required_str(data: dict, key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise FinalResponseError(f"{key} must be a non-empty string")
    return value


def _optional_str_list(data: dict, key: str) -> list[str]:
    value = data.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise FinalResponseError(f"{key} must be a list of strings")
    return value
