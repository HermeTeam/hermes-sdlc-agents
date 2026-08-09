from __future__ import annotations

import json
import re
import sqlite3

from . import db
from .hermes_client import HermesClient


ACCEPTED_FINAL_STATUSES = {
    "READY_FOR_BUILD",
    "PR_READY_FOR_REVIEW",
    "APPROVE",
    "REQUEST_CHANGES",
    "BLOCKED",
    "NO_ACTION",
    "MONITORING",
    "ESCALATED",
    "PROPOSED_FOR_HUMAN_REVIEW",
    "BLOCKED_NO_ACTION",
}
COMPLETED = {"completed", "succeeded", "success", "done"}
FAILED = {"failed", "error"}
CANCELLED = {"cancelled", "canceled"}
TIMEOUT = {"timeout", "timed_out"}


def reconcile(conn: sqlite3.Connection, client: HermesClient) -> dict[str, int]:
    summary = {"active": 0, "completed": 0, "failed": 0, "cancelled": 0, "timeout": 0, "invalid_output": 0}
    for run in db.active_runs(conn):
        summary["active"] += 1
        payload = client.get_run(run["hermes_run_id"])
        status = str(payload.get("status") or payload.get("state") or "").lower()
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if status in COMPLETED:
            final = extract_final_status(payload)
            if final in ACCEPTED_FINAL_STATUSES:
                db.mark_run_finished(conn, run["assignment_key"], "COMPLETED", final, raw)
                summary["completed"] += 1
            else:
                db.mark_run_finished(conn, run["assignment_key"], "INVALID_OUTPUT", final, raw)
                summary["invalid_output"] += 1
        elif status in FAILED:
            db.mark_run_finished(conn, run["assignment_key"], "FAILED", None, raw)
            summary["failed"] += 1
        elif status in CANCELLED:
            db.mark_run_finished(conn, run["assignment_key"], "CANCELLED", None, raw)
            summary["cancelled"] += 1
        elif status in TIMEOUT:
            db.mark_run_finished(conn, run["assignment_key"], "TIMEOUT", None, raw)
            summary["timeout"] += 1
    return summary


def extract_final_status(payload: dict) -> str | None:
    text_parts = []
    for key in ("final_status", "output", "result", "response", "text"):
        value = payload.get(key)
        if isinstance(value, str):
            text_parts.append(value)
        elif value is not None:
            text_parts.append(json.dumps(value, ensure_ascii=False))
    text = "\n".join(text_parts)
    match = re.search(r"\b(READY_FOR_BUILD|PR_READY_FOR_REVIEW|APPROVE|REQUEST_CHANGES|BLOCKED|NO_ACTION|MONITORING|ESCALATED|PROPOSED_FOR_HUMAN_REVIEW|BLOCKED_NO_ACTION)\b", text)
    return match.group(1) if match else None
