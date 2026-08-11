from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
from typing import Any

from .final_response import FinalResponse
from .statuses import FinalStatus


LOGGER = logging.getLogger(__name__)
SAFE_ROOT = Path("/opt/data")
DEFAULT_WORKSPACE_DIR = Path("/opt/data/workspace")
ARTIFACT_FILE_NAME = "self-evolution-results.jsonl"
MAX_TEXT_CHARS = 4000
MAX_SERIALIZED_CHARS = 8000


def maybe_record_self_evolution_result(*, item: Any, final_response: FinalResponse, raw_payload: dict[str, Any] | None = None) -> bool:
    if not _should_record(final_response):
        return False

    try:
        workspace = _workspace_dir()
        workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            workspace.chmod(0o700)
        except OSError:
            pass
        record = {
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "role": final_response.role,
            "assignment_key": final_response.assignment_key,
            "provider": item.provider,
            "repository_id": item.repository_id,
            "kind": item.kind,
            "external_id": item.external_id,
            "url": item.url,
            "final_status": final_response.final_status.value,
            "summary": _truncate_text(final_response.summary),
            "block_reason": _truncate_text(final_response.block_reason),
            "next_handoff": _bounded_value(final_response.next_handoff),
            "evidence": _bounded_value(final_response.evidence),
        }
        line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with (workspace / ARTIFACT_FILE_NAME).open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return True
    except Exception as exc:  # pragma: no cover - exact OS failures vary by runtime
        LOGGER.warning("Failed to record self-evolution artifact: %s", exc)
        return False


def _should_record(final_response: FinalResponse) -> bool:
    if final_response.final_status == FinalStatus.PROPOSED_FOR_HUMAN_REVIEW:
        return True
    if not isinstance(final_response.next_handoff, dict):
        return False
    text = json.dumps(final_response.next_handoff, ensure_ascii=False, sort_keys=True).lower()
    return any(marker in text for marker in ("learning", "self-evolution", "hermes-agent-self-evolution"))


def _workspace_dir() -> Path:
    raw_path = os.environ.get("HERMES_WORKSPACE_DIR") or str(DEFAULT_WORKSPACE_DIR)
    workspace = Path(raw_path).expanduser().resolve(strict=False)
    safe_root = SAFE_ROOT.resolve(strict=False)
    try:
        workspace.relative_to(safe_root)
    except ValueError as exc:
        raise ValueError(f"HERMES_WORKSPACE_DIR must resolve under {safe_root}: {workspace}") from exc
    return workspace


def _truncate_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value[:MAX_TEXT_CHARS]


def _bounded_value(value: Any) -> Any:
    if value is None:
        return None
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    if len(serialized) <= MAX_SERIALIZED_CHARS:
        return value
    return {"truncated": True, "preview": serialized[:MAX_SERIALIZED_CHARS]}
