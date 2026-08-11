from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3

from . import db
from .config import Config
from .final_response import FinalResponseError, parse_final_response
from .hermes_client import HermesClient, HermesRunNotFound
from .transitions import ProviderTransitionAdapter, apply_failure_transition, apply_transition


COMPLETED = {"completed", "succeeded", "success", "done"}
FAILED = {"failed", "error"}
CANCELLED = {"cancelled", "canceled"}
TIMEOUT = {"timeout", "timed_out"}


def reconcile(
    conn: sqlite3.Connection,
    client: HermesClient,
    config: Config,
    provider_adapter: ProviderTransitionAdapter | None = None,
) -> dict[str, int]:
    summary = {"active": 0, "completed": 0, "failed": 0, "cancelled": 0, "timeout": 0, "invalid_output": 0, "lost": 0}
    for run in db.active_runs(conn):
        summary["active"] += 1
        if _timed_out(run["started_at"], config.run_timeout_seconds):
            raw = json.dumps({"status": "timeout", "started_at": run["started_at"]}, ensure_ascii=False, sort_keys=True)
            db.mark_run_finished(
                conn,
                run["assignment_key"],
                "TIMEOUT",
                "BLOCKED",
                raw,
                error="Run exceeded ORCHESTRATOR_RUN_TIMEOUT_SECONDS",
                timed_out=True,
            )
            apply_failure_transition(
                conn,
                item=db.row_to_work_item(run),
                assignment_key=run["assignment_key"],
                role=run["role"],
                failure_status="TIMEOUT",
                summary="Run exceeded ORCHESTRATOR_RUN_TIMEOUT_SECONDS",
                config=config,
                provider_adapter=provider_adapter,
            )
            summary["timeout"] += 1
            continue
        try:
            payload = client.get_run(run["hermes_run_id"])
        except HermesRunNotFound as exc:
            # TODO(refactor-standalone-db): When the orchestrator moves from local SQLite to
            # PostgreSQL/MongoDB, replace this local lost-run recovery with a DB-backed run
            # lease/checkpoint model shared with Hermes Gateway.
            raw = json.dumps(
                {"status": "lost", "run_id": run["hermes_run_id"], "error": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            )
            db.mark_run_finished(
                conn,
                run["assignment_key"],
                "LOST",
                None,
                raw,
                error="Hermes run disappeared from gateway runtime; likely container restart/recreate while SQLite persisted ACTIVE run",
            )
            apply_failure_transition(
                conn,
                item=db.row_to_work_item(run),
                assignment_key=run["assignment_key"],
                role=run["role"],
                failure_status="LOST",
                summary="Hermes run was not found in the gateway runtime; marked lost locally so reconciliation can continue",
                config=config,
                provider_adapter=provider_adapter,
            )
            summary["lost"] += 1
            continue
        status = str(payload.get("status") or payload.get("state") or "").lower()
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if status in COMPLETED:
            try:
                final_response = parse_final_response(payload, expected_role=run["role"], expected_assignment_key=run["assignment_key"])
            except FinalResponseError as exc:
                db.mark_run_finished(conn, run["assignment_key"], "INVALID_OUTPUT", None, raw, error=str(exc))
                apply_failure_transition(
                    conn,
                    item=db.row_to_work_item(run),
                    assignment_key=run["assignment_key"],
                    role=run["role"],
                    failure_status="INVALID_OUTPUT",
                    summary=str(exc),
                    config=config,
                    provider_adapter=provider_adapter,
                )
                summary["invalid_output"] += 1
            else:
                item = db.row_to_work_item(run)
                if not _assignment_matches_current_revision(run["assignment_key"], item.revision_key()):
                    db.mark_run_finished(
                        conn,
                        run["assignment_key"],
                        "STALE_OUTPUT",
                        final_response.final_status.value,
                        raw,
                        error="Work item revision changed while run was active",
                        final_response_json=final_response.to_json(),
                    )
                    apply_failure_transition(
                        conn,
                        item=item,
                        assignment_key=run["assignment_key"],
                        role=run["role"],
                        failure_status="STALE_OUTPUT",
                        summary="Work item revision changed while run was active; normal downstream transition was not applied",
                        config=config,
                        provider_adapter=provider_adapter,
                    )
                    summary["invalid_output"] += 1
                    continue
                db.mark_run_finished(
                    conn,
                    run["assignment_key"],
                    "COMPLETED",
                    final_response.final_status.value,
                    raw,
                    final_response_json=final_response.to_json(),
                )
                apply_transition(
                    conn,
                    item=item,
                    final_response=final_response,
                    config=config,
                    provider_adapter=provider_adapter,
                )
                summary["completed"] += 1
        elif status in FAILED:
            db.mark_run_finished(conn, run["assignment_key"], "FAILED", None, raw)
            summary["failed"] += 1
        elif status in CANCELLED:
            db.mark_run_finished(conn, run["assignment_key"], "CANCELLED", None, raw)
            summary["cancelled"] += 1
        elif status in TIMEOUT:
            db.mark_run_finished(
                conn,
                run["assignment_key"],
                "TIMEOUT",
                "BLOCKED",
                raw,
                error="Hermes run reported timeout",
                timed_out=True,
            )
            apply_failure_transition(
                conn,
                item=db.row_to_work_item(run),
                assignment_key=run["assignment_key"],
                role=run["role"],
                failure_status="TIMEOUT",
                summary="Hermes run reported timeout",
                config=config,
                provider_adapter=provider_adapter,
            )
            summary["timeout"] += 1
    return summary


def _timed_out(started_at: str, timeout_seconds: int) -> bool:
    try:
        started = datetime.fromisoformat(started_at).replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - started).total_seconds() > timeout_seconds


def _assignment_matches_current_revision(assignment_key: str, current_revision: str) -> bool:
    return assignment_key.rsplit(":", 1)[-1] == current_revision
