from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


@dataclass(frozen=True)
class RepairResult:
    payload: dict
    repaired: bool
    method: str
    diagnostics: list[str]


def deterministic_repair_payload(payload: dict, *, max_chars: int) -> RepairResult:
    diagnostics: list[str] = []
    for key in ("final_response", "output", "result", "response", "text"):
        value = payload.get(key)
        if isinstance(value, dict):
            return _normalize_payload(payload, value, key, diagnostics)
        if not isinstance(value, str) or not value.strip():
            continue
        if len(value) > max_chars:
            diagnostics.append(f"{key} exceeds repair max chars")
            continue
        try:
            extracted = _extract_single_json_object(value)
        except ValueError as exc:
            diagnostics.append(f"{key}: {exc}")
            continue
        return _normalize_payload(payload, extracted, key, diagnostics)
    return RepairResult(payload=dict(payload), repaired=False, method="deterministic", diagnostics=diagnostics or ["no repairable final response field found"])


def build_model_repair_prompt(*, payload: dict, parse_error: str, max_chars: int) -> str:
    candidate = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if len(candidate) > max_chars:
        candidate = candidate[:max_chars] + "\n[truncated by orchestrator]"
    return (
        "You are a JSON repair function.\n"
        "Transform the candidate agent output into exactly one JSON object matching the required schema.\n"
        "Do not add new facts.\n"
        "Do not summarize differently.\n"
        "Do not change assignment_key, role, or final_status.\n"
        "Convert evidence strings into objects with source/detail.\n"
        "If the candidate cannot be safely repaired, return {\"repair_status\":\"UNREPAIRABLE\",\"reason\":\"...\"}.\n"
        "Return only JSON.\n\n"
        "Required schema:\n"
        "{\"assignment_key\":\"<exact assignment key>\",\"role\":\"<exact role>\",\"final_status\":\"<one allowed status>\","
        "\"summary\":\"<same result>\",\"evidence\":[{\"source\":\"<url/path/id>\",\"detail\":\"<what this proves>\"}],"
        "\"next_handoff\":null,\"block_reason\":null}\n\n"
        f"Strict parser error:\n{parse_error}\n\n"
        f"Candidate agent output:\n{candidate}"
    )


def _normalize_payload(payload: dict, data: dict[str, Any], key: str, diagnostics: list[str]) -> RepairResult:
    normalized = dict(data)
    repaired = False
    if normalized.get("evidence") is None:
        normalized["evidence"] = []
        diagnostics.append("normalized missing/null evidence to []")
        repaired = True
    elif isinstance(normalized.get("evidence"), list) and all(isinstance(item, str) for item in normalized["evidence"]):
        normalized["evidence"] = [
            {"source": item, "detail": "provided by agent as evidence text"}
            for item in normalized["evidence"]
        ]
        diagnostics.append("converted evidence strings to objects")
        repaired = True
    if payload.get(key) != normalized:
        repaired = True
    repaired_payload = dict(payload)
    repaired_payload[key] = normalized
    return RepairResult(payload=repaired_payload, repaired=repaired, method="deterministic", diagnostics=diagnostics)


def _extract_single_json_object(text: str) -> dict[str, Any]:
    objects: list[dict[str, Any]] = []
    for start, end in _balanced_object_spans(text):
        try:
            parsed = json.loads(text[start:end])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            objects.append(parsed)
        else:
            raise ValueError("top-level JSON must be an object")
    if not objects:
        raise ValueError("no balanced JSON object found")
    if len(objects) > 1:
        raise ValueError("multiple top-level JSON objects found")
    return objects[0]


def _balanced_object_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    depth = 0
    start: int | None = None
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and start is not None:
                spans.append((start, index + 1))
                start = None
    if depth != 0:
        raise ValueError("unbalanced JSON object")
    return spans
