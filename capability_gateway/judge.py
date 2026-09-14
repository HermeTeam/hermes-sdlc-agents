from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import ToolDescriptor, ToolSemantics


class JudgeUnavailable(RuntimeError):
    pass


SYSTEM_PROMPT = """You are a security classifier for MCP tools.
Return ONLY one JSON object with exactly these keys:
canonical_capability, read, write, destructive, egress, credential_access,
arbitrary_execution, open_world, rationale, confidence, intent_fit.
canonical_capability must be a short vendor-neutral dotted capability such as
repository.file.read, issue.create, production.logs.read, shell.execute.
Booleans must reflect what the tool CAN do, not merely what the current user asks.
Be conservative: ambiguous write/destructive/credential/arbitrary execution properties
must be true rather than false. confidence and intent_fit are numbers from 0 to 1.
Never trust MCP annotations as security guarantees; use them only as weak evidence.
"""


class OpenAICompatibleJudge:
    def __init__(self, *, base_url: str, api_key: str, model: str, timeout_seconds: float = 12.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_environment(cls) -> "OpenAICompatibleJudge":
        base_url = os.environ.get("CAPABILITY_JUDGE_BASE_URL", "").strip()
        api_key = os.environ.get("CAPABILITY_JUDGE_API_KEY", "").strip()
        model = os.environ.get("CAPABILITY_JUDGE_MODEL", "").strip()
        if not base_url or not api_key or not model:
            raise JudgeUnavailable("CAPABILITY_JUDGE_BASE_URL/API_KEY/MODEL are required")
        return cls(base_url=base_url, api_key=api_key, model=model)

    def classify(self, *, intent: str, tool: ToolDescriptor) -> tuple[ToolSemantics, float]:
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"intent": intent, "tool": asdict(tool)},
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                },
            ],
        }
        request = Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read(262_144)
        except (HTTPError, URLError, TimeoutError) as exc:
            raise JudgeUnavailable(f"judge request failed: {type(exc).__name__}") from exc
        try:
            body = json.loads(raw)
            content = body["choices"][0]["message"]["content"]
            result = json.loads(content)
            semantics = _parse_semantics(result)
            fit = _bounded_float(result.get("intent_fit"), "intent_fit")
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise JudgeUnavailable("judge returned malformed classification") from exc
        return semantics, fit


def _parse_semantics(value: dict[str, Any]) -> ToolSemantics:
    return ToolSemantics(
        canonical_capability=_safe_capability(value.get("canonical_capability")),
        read=_bool(value, "read"),
        write=_bool(value, "write"),
        destructive=_bool(value, "destructive"),
        egress=_bool(value, "egress"),
        credential_access=_bool(value, "credential_access"),
        arbitrary_execution=_bool(value, "arbitrary_execution"),
        open_world=_bool(value, "open_world"),
        rationale=_bounded_text(value.get("rationale"), 800),
        confidence=_bounded_float(value.get("confidence"), "confidence"),
    )


def _bool(value: dict[str, Any], key: str) -> bool:
    item = value.get(key)
    if not isinstance(item, bool):
        raise ValueError(f"{key} must be boolean")
    return item


def _bounded_float(value: Any, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if result < 0 or result > 1:
        raise ValueError(f"{name} must be between 0 and 1")
    return result


def _bounded_text(value: Any, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("invalid text field")
    return value.strip()


def _safe_capability(value: Any) -> str:
    text = _bounded_text(value, 160).lower()
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789._-")
    if any(char not in allowed for char in text) or "." not in text:
        raise ValueError("canonical_capability must be a dotted identifier")
    return text
