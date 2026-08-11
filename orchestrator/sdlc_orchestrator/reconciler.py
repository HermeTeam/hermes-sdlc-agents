from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
    summary = {
        "active": 0,
        "completed": 0,
        "failed": 0,
        "cancelled": 0,
        "timeout": 0,
        "invalid_output": 0,
        "lost": 0,
        "requeued": 0,
        "blocked_config": 0,
        "failed_final": 0,
    }
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
                assignment_status="TIMEOUT",
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
            # TODO(refactor-standalone-db): When moving to PostgreSQL/MongoDB, replace this
            # SQLite-local retry/requeue lease with a durable DB-backed run lease/checkpoint
            # shared with Hermes Gateway.
            raw = json.dumps(
                {"status": "lost", "run_id": run["hermes_run_id"], "error": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            )
            if config.retry_lost_runs and _has_attempts_remaining(run, config):
                db.mark_run_finished(
                    conn,
                    run["assignment_key"],
                    "LOST",
                    None,
                    raw,
                    assignment_status="PENDING",
                    error="Hermes run disappeared from gateway runtime; requeued locally",
                    next_retry_at=_retry_timestamp(config.retry_delay_seconds),
                )
                db.record_transition(
                    conn,
                    assignment_key=run["assignment_key"],
                    from_role=run["role"],
                    final_status="LOST_REQUEUED",
                    next_role=None,
                    provider_applied=False,
                    provider_result=json.dumps({"mode": "local-requeue"}, ensure_ascii=False, sort_keys=True),
                )
                summary["lost"] += 1
                summary["requeued"] += 1
                continue
            db.mark_run_finished(
                conn,
                run["assignment_key"],
                "LOST",
                None,
                raw,
                assignment_status="FAILED_FINAL",
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
            summary["failed_final"] += 1
            continue
        status = str(payload.get("status") or payload.get("state") or "").lower()
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if status in COMPLETED:
            try:
                final_response = parse_final_response(payload, expected_role=run["role"], expected_assignment_key=run["assignment_key"])
            except FinalResponseError as exc:
                db.mark_run_finished(conn, run["assignment_key"], "INVALID_OUTPUT", None, raw, assignment_status="FAILED_FINAL", error=str(exc))
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
                        assignment_status="FAILED_FINAL",
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
                    assignment_status="COMPLETED",
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
            error_text = _error_text(payload)
            if _is_config_error(payload):
                db.mark_run_finished(
                    conn,
                    run["assignment_key"],
                    "FAILED",
                    None,
                    raw,
                    assignment_status="BLOCKED_CONFIG",
                    error=error_text,
                    blocked_reason=_concise_error(error_text),
                    last_error_code="CONFIG_AUTH",
                )
                apply_failure_transition(
                    conn,
                    item=db.row_to_work_item(run),
                    assignment_key=run["assignment_key"],
                    role=run["role"],
                    failure_status="BLOCKED_CONFIG",
                    summary=_concise_error(error_text),
                    config=config,
                    provider_adapter=provider_adapter,
                )
                summary["blocked_config"] += 1
            elif config.retry_transient_failures and _is_transient_error(payload) and _has_attempts_remaining(run, config):
                db.mark_run_finished(
                    conn,
                    run["assignment_key"],
                    "FAILED",
                    None,
                    raw,
                    assignment_status="PENDING",
                    error=error_text,
                    next_retry_at=_retry_timestamp(config.retry_delay_seconds),
                )
                db.record_transition(
                    conn,
                    assignment_key=run["assignment_key"],
                    from_role=run["role"],
                    final_status="FAILED_REQUEUED",
                    next_role=None,
                    provider_applied=False,
                    provider_result=json.dumps({"mode": "local-requeue"}, ensure_ascii=False, sort_keys=True),
                )
                summary["requeued"] += 1
            else:
                db.mark_run_finished(
                    conn,
                    run["assignment_key"],
                    "FAILED",
                    None,
                    raw,
                    assignment_status="FAILED_FINAL",
                    error=error_text,
                )
                apply_failure_transition(
                    conn,
                    item=db.row_to_work_item(run),
                    assignment_key=run["assignment_key"],
                    role=run["role"],
                    failure_status="FAILED_FINAL",
                    summary=_concise_error(error_text),
                    config=config,
                    provider_adapter=provider_adapter,
                )
                summary["failed_final"] += 1
            summary["failed"] += 1
        elif status in CANCELLED:
            db.mark_run_finished(conn, run["assignment_key"], "CANCELLED", None, raw, assignment_status="CANCELLED")
            summary["cancelled"] += 1
        elif status in TIMEOUT:
            db.mark_run_finished(
                conn,
                run["assignment_key"],
                "TIMEOUT",
                "BLOCKED",
                raw,
                assignment_status="TIMEOUT",
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


def _error_text(payload: dict) -> str:
    candidates = [payload.get("error"), payload.get("message"), payload.get("detail"), payload.get("output")]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
        if isinstance(candidate, dict):
            return json.dumps(candidate, ensure_ascii=False, sort_keys=True)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _is_config_error(payload: dict) -> bool:
    text = _error_text(payload).lower()
    patterns = (
        "invalid_api_key",
        "incorrect api key",
        "invalid api-key",
        "authenticationerror",
        "unauthorized",
        "http 401",
        "api key was rejected",
        "no nous authentication",
    )
    return any(pattern in text for pattern in patterns)


def _is_transient_error(payload: dict) -> bool:
    text = _error_text(payload).lower()
    patterns = (
        "http 408",
        "http 409",
        "http 425",
        "http 429",
        "http 500",
        "http 502",
        "http 503",
        "http 504",
        "rate limit",
        "timeout",
        "temporarily unavailable",
        "overloaded",
        "connection reset",
        "connection aborted",
    )
    return any(pattern in text for pattern in patterns)


def _has_attempts_remaining(run: sqlite3.Row, config: Config) -> bool:
    return int(run["attempt_number"]) < config.max_attempts_per_assignment


def _retry_timestamp(delay_seconds: int) -> str | None:
    if delay_seconds <= 0:
        return None
    return (datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)).strftime("%Y-%m-%d %H:%M:%S")


def _concise_error(text: str) -> str:
    text = " ".join(text.split())
    return text[:500]
