from __future__ import annotations

import json
import os
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .catalogs import CatalogUnavailable, discover_tools
from .core import assess_risk, resolve
from .governance import GovernanceStore
from .judge import JudgeUnavailable, OpenAICompatibleJudge
from .models import RankedTool, RiskCategory, ToolDescriptor


MAX_BODY = 64 * 1024
MAX_TOOLS = 80


class CapabilityGateway:
    def __init__(self) -> None:
        self.store = GovernanceStore(
            Path(os.environ.get("CAPABILITY_GATEWAY_DB", "/opt/data/capability-gateway.sqlite3"))
        )
        self.max_auto_category = RiskCategory.parse(
            os.environ.get("CAPABILITY_MAX_AUTO_RISK", "MEDIUM")
        )
        self.judge = OpenAICompatibleJudge.from_environment()
        self.admin_key = os.environ.get("CAPABILITY_ADMIN_KEY", "").strip()
        if len(self.admin_key) < 24:
            raise RuntimeError("CAPABILITY_ADMIN_KEY must contain at least 24 characters")

    def resolve_intent(self, body: dict[str, Any]) -> dict[str, Any]:
        intent = _text(body.get("intent"), "intent", 2000)
        requested_tool_id = _optional_text(body.get("requested_tool_id"), 300)
        tools = _parse_tools(body.get("tools"))
        if not tools:
            query = _optional_text(body.get("catalog_query"), 300) or intent
            tools = discover_tools(query)
        if not tools:
            return {
                "intent": intent,
                "selected": None,
                "visible_tools": [],
                "filtered_tools": [],
                "status": "no_tools",
            }
        if len(tools) > MAX_TOOLS:
            tools = tools[:MAX_TOOLS]

        ranked: list[RankedTool] = []
        for tool in tools:
            semantics, fit = self.judge.classify(intent=intent, tool=tool)
            assessment = assess_risk(tool, semantics)
            ranked.append(
                RankedTool(
                    tool=tool,
                    assessment=assessment,
                    intent_fit=fit,
                    dominated=False,
                )
            )

        snapshot = self.store.snapshot()
        resolution = resolve(
            intent=intent,
            candidates=ranked,
            max_auto_category=self.max_auto_category,
            requested_tool_id=requested_tool_id,
            exception_tools=snapshot.tool_exceptions,
            capability_overrides=snapshot.capability_overrides,
            emergency_stop=snapshot.emergency_stop,
        )

        if resolution.approval_required is not None:
            request = resolution.approval_required
            requested = next(
                item for item in ranked if item.tool.tool_id == request.requested_tool_id
            )
            if self.store.has_unconsumed_once(request.request_id, request.requested_tool_id):
                resolution = resolve(
                    intent=intent,
                    candidates=ranked,
                    max_auto_category=self.max_auto_category,
                    requested_tool_id=requested_tool_id,
                    allowed_once=frozenset({request.requested_tool_id}),
                    exception_tools=snapshot.tool_exceptions,
                    capability_overrides=snapshot.capability_overrides,
                    emergency_stop=snapshot.emergency_stop,
                )
                # Conservative MVP semantics: the one-shot authority is spent when the
                # gateway exposes the approved risky tool for this resolution. If the
                # downstream executor fails, a new human approval is required.
                if resolution.selected and resolution.selected.tool.tool_id == request.requested_tool_id:
                    if not self.store.consume_once(request.request_id, request.requested_tool_id):
                        return {
                            "intent": intent,
                            "selected": None,
                            "visible_tools": [],
                            "filtered_tools": [],
                            "status": "one_shot_grant_already_consumed",
                        }
            else:
                self.store.record_pending_approval(
                    request_id=request.request_id,
                    intent=request.intent,
                    tool_id=request.requested_tool_id,
                    capability=requested.assessment.canonical_capability,
                    requested_category=request.requested_category,
                    allowed_category=request.allowed_category,
                    recommended_tool_id=request.recommended_tool_id,
                    reason=request.reason,
                )

        return _resolution_json(resolution)

    def governance_state(self) -> dict[str, Any]:
        snapshot = self.store.snapshot()
        return {
            "emergency_stop": snapshot.emergency_stop,
            "max_auto_category": self.max_auto_category.name,
            "tool_exceptions": sorted(snapshot.tool_exceptions),
            "capability_overrides": {
                key: value.name for key, value in sorted(snapshot.capability_overrides.items())
            },
            "pending_approvals": [
                {
                    "request_id": item.request_id,
                    "intent": item.intent,
                    "tool_id": item.tool_id,
                    "capability": item.capability,
                    "requested_category": item.requested_category.name,
                    "allowed_category": item.allowed_category.name,
                    "recommended_tool_id": item.recommended_tool_id,
                    "reason": item.reason,
                    "created_at": item.created_at,
                }
                for item in snapshot.pending_approvals
            ],
        }


def make_handler(gateway: CapabilityGateway):
    class Handler(BaseHTTPRequestHandler):
        server_version = "HermeTeamCapabilityGateway/0.1"

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                return self._json(200, {"status": "ok"})
            if self.path == "/v1/governance":
                if not self._admin():
                    return
                return self._json(200, gateway.governance_state())
            return self._json(404, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            try:
                body = self._body()
                if self.path == "/v1/resolve":
                    result = gateway.resolve_intent(body)
                    status = 423 if result.get("emergency_stop") else 200
                    return self._json(status, result)
                if not self._admin():
                    return
                if self.path == "/v1/governance/emergency-stop":
                    enabled = body.get("enabled")
                    if not isinstance(enabled, bool):
                        return self._json(400, {"error": "enabled_must_be_boolean"})
                    gateway.store.set_emergency_stop(enabled)
                    return self._json(200, gateway.governance_state())
                if self.path == "/v1/governance/allow-once":
                    request_id = _text(body.get("request_id"), "request_id", 100)
                    tool_id = _text(body.get("tool_id"), "tool_id", 300)
                    gateway.store.grant_once(request_id, tool_id)
                    return self._json(200, gateway.governance_state())
                if self.path == "/v1/governance/tool-exception":
                    tool_id = _text(body.get("tool_id"), "tool_id", 300)
                    gateway.store.add_tool_exception(tool_id)
                    return self._json(200, gateway.governance_state())
                if self.path == "/v1/governance/capability-risk":
                    capability = _text(body.get("capability"), "capability", 160)
                    category = RiskCategory.parse(_text(body.get("category"), "category", 20))
                    gateway.store.set_capability_override(capability, category)
                    return self._json(200, gateway.governance_state())
                return self._json(404, {"error": "not_found"})
            except (ValueError, TypeError) as exc:
                return self._json(400, {"error": "invalid_request", "message": str(exc)})
            except JudgeUnavailable:
                # The judge is mandatory for MVP. Never silently downgrade to semantic guessing.
                return self._json(503, {"error": "judge_unavailable"})
            except CatalogUnavailable:
                return self._json(503, {"error": "catalog_unavailable"})

        def log_message(self, fmt: str, *args: object) -> None:
            return

        def _admin(self) -> bool:
            expected = f"Bearer {gateway.admin_key}"
            if self.headers.get("Authorization") != expected:
                self._json(401, {"error": "unauthorized"})
                return False
            return True

        def _body(self) -> dict[str, Any]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ValueError("invalid content length") from exc
            if length <= 0 or length > MAX_BODY:
                raise ValueError("invalid request body length")
            raw = self.rfile.read(length)
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("request body must be an object")
            return value

        def _json(self, status: int, value: Any) -> None:
            raw = json.dumps(value, separators=(",", ":"), default=_json_default).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    return Handler


def _parse_tools(value: Any) -> tuple[ToolDescriptor, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("tools must be an array")
    output: list[ToolDescriptor] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("each tool must be an object")
        output.append(
            ToolDescriptor(
                server_id=_text(item.get("server_id"), "server_id", 200),
                tool_name=_text(item.get("tool_name"), "tool_name", 200),
                description=_text(item.get("description", ""), "description", 4000, allow_empty=True),
                input_schema=item.get("input_schema") if isinstance(item.get("input_schema"), dict) else {},
                annotations=item.get("annotations") if isinstance(item.get("annotations"), dict) else {},
                source=_optional_text(item.get("source"), 100) or "request",
                version=_optional_text(item.get("version"), 100),
            )
        )
    return tuple(output)


def _resolution_json(value: Any) -> dict[str, Any]:
    data = asdict(value)
    data["visible_tools"] = [_ranked_json(item) for item in value.visible_tools]
    data["filtered_tools"] = [_ranked_json(item) for item in value.filtered_tools]
    data["selected"] = _ranked_json(value.selected) if value.selected else None
    if value.approval_required:
        data["approval_required"]["requested_category"] = value.approval_required.requested_category.name
        data["approval_required"]["allowed_category"] = value.approval_required.allowed_category.name
    return data


def _ranked_json(value: Any) -> dict[str, Any]:
    data = asdict(value)
    data["assessment"]["category"] = value.assessment.category.name
    return data


def _json_default(value: Any) -> Any:
    if isinstance(value, RiskCategory):
        return value.name
    raise TypeError(type(value).__name__)


def _text(value: Any, name: str, limit: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit or (not allow_empty and not value.strip()):
        raise ValueError(f"{name} must be a bounded string")
    if any(ord(char) < 32 and char not in "\t\n\r" for char in value):
        raise ValueError(f"{name} contains control characters")
    return value.strip()


def _optional_text(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    return _text(value, "value", limit)


def main() -> None:
    gateway = CapabilityGateway()
    bind = os.environ.get("CAPABILITY_GATEWAY_BIND", "127.0.0.1")
    port = int(os.environ.get("CAPABILITY_GATEWAY_PORT", "8787"))
    server = ThreadingHTTPServer((bind, port), make_handler(gateway))
    server.serve_forever()


if __name__ == "__main__":
    main()
