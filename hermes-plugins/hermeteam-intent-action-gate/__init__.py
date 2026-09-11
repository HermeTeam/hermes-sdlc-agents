from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import threading
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA = "hermeteam.intent-action.v1"
VERSION = "0.1.0"
RISK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
READ_PREFIXES = ("get_", "list_", "read_", "search_", "query_", "fetch_", "inspect_", "view_")
WRITE_WORDS = ("create", "update", "push", "write", "edit", "delete", "remove", "merge", "close", "trigger", "run", "execute", "apply", "deploy", "release", "publish", "set", "modify", "upload", "commit")
CRITICAL_WORDS = ("merge", "deploy", "release", "destroy", "delete_repository", "secret", "permission", "ruleset", "branch_protection", "admin")
PROTECTED_RE = re.compile(r"(^|[/\\])(?:\.github[/\\](?:workflows|actions)|policies|kubernetes|secrets?)(?:[/\\]|$)", re.I)
PROD_RE = re.compile(r"\b(prod|production|main|master)\b", re.I)
SENSITIVE_KEYS = {"authorization", "api_key", "apikey", "token", "secret", "password", "content", "contents", "file_content", "private_key"}

STATE_LOCK = threading.Lock()
FILE_LOCK = threading.Lock()
PROPOSALS: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=64))


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def mode() -> str:
    value = env("HERMETEAM_GATE_MODE", "shadow").lower()
    return value if value in {"record", "shadow", "enforce"} else "shadow"


def block_level() -> str:
    value = env("HERMETEAM_GATE_BLOCK_LEVEL", "critical").lower()
    return value if value in RISK else "critical"


def stable_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def bounded(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return {"omitted": True, "type": type(value).__name__}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) <= 256:
            return value
        return {"type": "text", "chars": len(value), "sha256": hashlib.sha256(value.encode()).hexdigest()}
    if isinstance(value, (list, tuple)):
        return [bounded(item, depth + 1) for item in list(value)[:25]]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:50]:
            name = str(key)
            result[name] = {"omitted": True, "sha256": stable_hash(item)} if name.lower() in SENSITIVE_KEYS else bounded(item, depth + 1)
        return result
    return {"type": type(value).__name__, "repr_hash": hashlib.sha256(repr(value).encode()).hexdigest()}


def flatten_text(value: Any) -> str:
    parts: list[str] = []

    def visit(item: Any, depth: int = 0) -> None:
        if depth > 4:
            return
        if isinstance(item, str):
            parts.append(item[:1000])
        elif isinstance(item, dict):
            for key, child in list(item.items())[:50]:
                if str(key).lower() not in SENSITIVE_KEYS:
                    visit(child, depth + 1)
        elif isinstance(item, (list, tuple)):
            for child in list(item)[:50]:
                visit(child, depth + 1)

    visit(value)
    return " ".join(parts)


def classify_action(tool_name: str, args: Any) -> tuple[str, str, tuple[str, ...]]:
    name = (tool_name or "").strip().lower()
    text = f"{name} {flatten_text(args)}"
    reasons: list[str] = []
    if not name:
        return "high", "unknown", ("missing_tool_name",)
    if name.startswith(READ_PREFIXES):
        risk, category = "low", "read"
    elif any(word in name for word in CRITICAL_WORDS):
        risk, category = "critical", "privileged_write"
        reasons.append("privileged_tool")
    elif any(word in name for word in WRITE_WORDS):
        risk, category = "medium", "write"
        reasons.append("state_changing_tool")
    else:
        risk, category = "medium", "unknown"
        reasons.append("unknown_tool_semantics")
    if PROTECTED_RE.search(text):
        risk = max((risk, "high"), key=RISK.get)
        reasons.append("protected_target")
    if PROD_RE.search(text) and category != "read":
        risk = max((risk, "high"), key=RISK.get)
        reasons.append("production_or_default_branch_target")
    if any(word in name for word in ("merge", "deploy", "release", "destroy")):
        risk = "critical"
        reasons.append("irreversible_or_privileged_operation")
    return risk, category, tuple(dict.fromkeys(reasons))


def normalize_tool_call(call: dict[str, Any]) -> dict[str, Any]:
    fn = call.get("function")
    name, args = call.get("name"), call.get("arguments")
    if isinstance(fn, dict):
        name = fn.get("name") or name
        args = fn.get("arguments", args)
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = {"raw_arguments_hash": hashlib.sha256(args.encode()).hexdigest(), "chars": len(args)}
    return {"tool_call_id": str(call.get("id") or call.get("call_id") or ""), "tool_name": str(name or ""), "args": args if isinstance(args, (dict, list)) else {"value": args}}


def extract_tool_calls(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def visit(item: Any, depth: int = 0) -> None:
        if depth > 8:
            return
        if isinstance(item, dict):
            calls = item.get("tool_calls")
            if isinstance(calls, list):
                found.extend(normalize_tool_call(call) for call in calls if isinstance(call, dict))
            if item.get("type") in {"function_call", "tool_call"} and (item.get("name") or item.get("function")):
                found.append(normalize_tool_call(item))
            for child in item.values():
                visit(child, depth + 1)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child, depth + 1)

    visit(value)
    unique: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in found:
        unique[(item["tool_call_id"], item["tool_name"], stable_hash(item["args"]))] = item
    return list(unique.values())


def event(event_type: str, **fields: Any) -> dict[str, Any]:
    return {"schema": SCHEMA, "plugin_version": VERSION, "timestamp": datetime.now(timezone.utc).isoformat(), "event_type": event_type, "role": env("ORCHESTRATOR_ROLE"), "repository": env("GITHUB_REPOSITORY_FULL_NAME") or env("REPOSITORY_ID"), **fields}


def emit(payload: dict[str, Any]) -> None:
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    print(f"HERMETEAM_EVENT {line}", flush=True)
    path = env("HERMETEAM_GATE_LOG_PATH", "/opt/data/hermeteam/intent-action-events.jsonl")
    if not path:
        return
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with FILE_LOCK, target.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception as exc:
        logger.warning("HermeTeam gate event append failed: %s", exc)


def remember(session_id: str, proposal: dict[str, Any]) -> None:
    with STATE_LOCK:
        PROPOSALS[session_id].append(proposal)


def match_proposal(session_id: str, tool_call_id: str, tool_name: str, args_hash: str) -> dict[str, Any] | None:
    with STATE_LOCK:
        proposals = list(PROPOSALS.get(session_id, ()))
    if tool_call_id:
        for item in reversed(proposals):
            if item["tool_call_id"] == tool_call_id:
                return item
    for item in reversed(proposals):
        if item["tool_name"] == tool_name and item["args_hash"] == args_hash:
            return item
    return next((item for item in reversed(proposals) if item["tool_name"] == tool_name), None)


def on_pre_api_request(**kwargs: Any) -> None:
    request = kwargs.get("request")
    emit(event(
        "llm.request",
        mode=mode(),
        session_id=str(kwargs.get("session_id") or ""),
        turn_id=str(kwargs.get("turn_id") or ""),
        api_request_id=str(kwargs.get("api_request_id") or ""),
        provider=str(kwargs.get("provider") or ""),
        model=str(kwargs.get("model") or ""),
        api_mode=str(kwargs.get("api_mode") or ""),
        message_count=kwargs.get("message_count"),
        tool_count=kwargs.get("tool_count"),
        approx_input_tokens=kwargs.get("approx_input_tokens"),
        request_hash=stable_hash(request),
        request=bounded(request),
    ))


def on_post_api_request(**kwargs: Any) -> None:
    response = kwargs.get("response")
    emit(event(
        "llm.response",
        mode=mode(),
        session_id=str(kwargs.get("session_id") or ""),
        turn_id=str(kwargs.get("turn_id") or ""),
        api_request_id=str(kwargs.get("api_request_id") or ""),
        provider=str(kwargs.get("provider") or ""),
        model=str(kwargs.get("response_model") or kwargs.get("model") or ""),
        finish_reason=str(kwargs.get("finish_reason") or ""),
        usage=bounded(kwargs.get("usage")),
        response_hash=stable_hash(response),
        response=bounded(response),
    ))
    session_id = str(kwargs.get("session_id") or "")
    for call in extract_tool_calls(response):
        risk, category, reasons = classify_action(call["tool_name"], call["args"])
        proposal = {"tool_call_id": call["tool_call_id"], "tool_name": call["tool_name"], "args_hash": stable_hash(call["args"]), "risk": risk, "category": category, "reasons": reasons}
        remember(session_id, proposal)
        emit(event("intent.proposed_action", mode=mode(), session_id=session_id, turn_id=str(kwargs.get("turn_id") or ""), api_request_id=str(kwargs.get("api_request_id") or ""), tool_call_id=proposal["tool_call_id"], tool_name=proposal["tool_name"], args_hash=proposal["args_hash"], args=bounded(call["args"]), risk=risk, category=category, reasons=list(reasons)))


def on_pre_tool_call(**kwargs: Any) -> dict[str, Any] | None:
    session_id = str(kwargs.get("session_id") or "")
    tool_call_id = str(kwargs.get("tool_call_id") or "")
    tool_name = str(kwargs.get("tool_name") or "")
    args = kwargs.get("args")
    args_hash = stable_hash(args)
    risk, category, reasons = classify_action(tool_name, args)
    proposal = match_proposal(session_id, tool_call_id, tool_name, args_hash)
    mismatch = proposal is None or proposal["args_hash"] != args_hash
    if mismatch:
        risk = max((risk, "high"), key=RISK.get)
        reasons = tuple(dict.fromkeys((*reasons, "no_matching_model_proposal" if proposal is None else "intent_action_mismatch")))
    current_mode = mode()
    blocked = current_mode == "enforce" and RISK[risk] >= RISK[block_level()]
    emit(event("action.requested", mode=current_mode, session_id=session_id, turn_id=str(kwargs.get("turn_id") or ""), api_request_id=str(kwargs.get("api_request_id") or ""), tool_call_id=tool_call_id, tool_name=tool_name, args_hash=args_hash, args=bounded(args), risk=risk, category=category, reasons=list(reasons), matched_model_proposal=proposal is not None, proposal_mismatch=mismatch, decision="DENY" if blocked else ("ALLOW" if current_mode == "enforce" else "ALLOW_SHADOW")))
    if blocked:
        return {"action": "block", "message": f"HermeTeam blocked {tool_name!r}: risk={risk}; reasons={','.join(reasons) or 'threshold'}."}
    return None


def on_post_tool_call(**kwargs: Any) -> None:
    result = kwargs.get("result")
    emit(event("action.completed", mode=mode(), session_id=str(kwargs.get("session_id") or ""), turn_id=str(kwargs.get("turn_id") or ""), api_request_id=str(kwargs.get("api_request_id") or ""), tool_call_id=str(kwargs.get("tool_call_id") or ""), tool_name=str(kwargs.get("tool_name") or ""), status=str(kwargs.get("status") or ""), duration_ms=kwargs.get("duration_ms"), error_type=str(kwargs.get("error_type") or ""), result=bounded(result), result_hash=stable_hash(result)))


def register(ctx: Any) -> None:
    ctx.register_hook("pre_api_request", on_pre_api_request)
    ctx.register_hook("post_api_request", on_post_api_request)
    ctx.register_hook("pre_tool_call", on_pre_tool_call)
    ctx.register_hook("post_tool_call", on_post_tool_call)
