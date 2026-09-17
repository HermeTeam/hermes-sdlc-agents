from __future__ import annotations

import json
import os
from pathlib import Path
import socket
from typing import Any

PLUGIN_VERSION = "0.2.0"
WORKSPACE_ROOT = Path("/opt/data/workspace")
SOCKET_PATH = Path("/opt/data/workspace/.hermeteam-openhands/runner.sock")
MAX_RESPONSE_BYTES = 100000


def _result(**payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _safe_workspace(relative: str) -> str:
    root = WORKSPACE_ROOT.resolve()
    candidate = (root / (relative or ".")).resolve()
    try:
        rel = candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("workspace must stay under /opt/data/workspace") from exc
    candidate.mkdir(parents=True, exist_ok=True)
    return "." if str(rel) == "." else str(rel)


def _call_runner(request: dict[str, Any], timeout: int) -> dict[str, Any]:
    if not SOCKET_PATH.is_socket():
        raise RuntimeError("OpenHands runner socket is unavailable")
    wire = (json.dumps(request, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    payload = bytearray()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout + 10)
        client.connect(str(SOCKET_PATH))
        client.sendall(wire)
        client.shutdown(socket.SHUT_WR)
        while len(payload) <= MAX_RESPONSE_BYTES:
            chunk = client.recv(8192)
            if not chunk:
                break
            payload.extend(chunk)
            if b"\n" in chunk:
                break
    if len(payload) > MAX_RESPONSE_BYTES:
        raise RuntimeError("OpenHands runner response exceeded limit")
    response = json.loads(bytes(payload).split(b"\n", 1)[0].decode("utf-8"))
    if not isinstance(response, dict):
        raise RuntimeError("OpenHands runner returned an invalid response")
    return response


def delegate(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    if os.environ.get("ORCHESTRATOR_ROLE", "").strip() != "builder":
        return _result(success=False, error="openhands_delegate is restricted to the builder role")
    if os.environ.get("BUILDER_OPENHANDS_ENABLED", "true").lower() not in {"1", "true", "yes", "on"}:
        return _result(success=False, error="OpenHands delegation is disabled")

    task = str(params.get("task") or "").strip()
    if not task:
        return _result(success=False, error="task is required")
    if len(task) > 12000:
        return _result(success=False, error="task exceeds 12000 characters")
    try:
        timeout = int(params.get("timeout_seconds") or 900)
    except (TypeError, ValueError):
        timeout = 900
    timeout = min(max(timeout, 30), 1800)

    try:
        workspace = _safe_workspace(str(params.get("workspace") or "."))
        response = _call_runner(
            {"task": task, "workspace": workspace, "timeout_seconds": timeout},
            timeout,
        )
        response["plugin_version"] = PLUGIN_VERSION
        return json.dumps(response, ensure_ascii=False, sort_keys=True)
    except Exception as exc:  # noqa: BLE001
        return _result(success=False, error=str(exc), plugin_version=PLUGIN_VERSION)


def register(ctx: Any) -> None:
    schema = {
        "name": "openhands_delegate",
        "description": (
            "Delegate a bounded coding/refactoring task to the isolated OpenHands runner using the builder scratch "
            "workspace. The runner container has dedicated LLM credentials but no Git/provider/MCP credentials. "
            "Provider writes must still be performed by Hermes through repository MCP/API after reviewing changes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Concrete coding task for OpenHands."},
                "workspace": {
                    "type": "string",
                    "description": "Relative path below /opt/data/workspace; defaults to the workspace root.",
                    "default": ".",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "minimum": 30,
                    "maximum": 1800,
                    "default": 900,
                },
            },
            "required": ["task"],
        },
    }
    ctx.register_tool(
        name="openhands_delegate",
        toolset="hermeteam-openhands",
        schema=schema,
        handler=delegate,
        description=schema["description"],
        max_result_size_chars=50000,
    )
