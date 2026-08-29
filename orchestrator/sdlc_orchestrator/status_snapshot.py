"""Bounded, read-only role queue snapshots for the dashboard status server.

This module deliberately bypasses :mod:`sdlc_orchestrator.db` because its normal
``connect`` path creates parent directories and commits.  The snapshot reader
opens an already-existing SQLite file using ``mode=ro`` and issues only static
``SELECT``/``PRAGMA table_info`` statements.  Normal read-only mode participates
in SQLite WAL shared-memory coordination so it observes committed WAL content.
SQLite may read an existing ``-shm`` sidecar for that coordination; this is not a
write privilege and is required for current WAL visibility.  It neither
initializes nor migrates the role database.

SQLite stores its default timestamps without an offset.  Those values are
interpreted as UTC, which is how SQLite's ``CURRENT_TIMESTAMP`` is generated,
and emitted as RFC 3339 UTC timestamps.  The temporal tie-break is oldest first
by active-run start, retry time, creation time, update time, then assignment
key.  Rows whose required public fields cannot be safely represented are not
returned; queue counters still describe the role-local database state.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Final
from urllib.parse import urlparse

from .config import Config
from .statuses import VALID_ROLES


MAX_QUEUE_ITEMS: Final = 50
SQLITE_READ_TIMEOUT_SECONDS: Final = 0.15
MAX_TEXT_LENGTH: Final = 500
MAX_ERROR_CODE_LENGTH: Final = 100

_ASSIGNMENT_STATUSES: Final = frozenset(
    {"PENDING", "STARTED", "COMPLETED", "BLOCKED_CONFIG", "FAILED_FINAL", "CANCELLED", "TIMEOUT"}
)
_RUN_STATUSES: Final = frozenset(
    {"ACTIVE", "COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "LOST", "INVALID_OUTPUT", "STALE_OUTPUT"}
)
_REQUIRED_SCHEMA: Final = {
    "work_items": frozenset({"id", "provider", "repository_id", "external_id", "title", "url"}),
    "role_assignments": frozenset(
        {
            "assignment_key",
            "work_item_id",
            "role",
            "status",
            "next_retry_at",
            "blocked_reason",
            "last_error_code",
            "created_at",
            "updated_at",
        }
    ),
    "agent_runs": frozenset({"id", "assignment_key", "hermes_run_id", "status", "attempt_number", "started_at"}),
}


class StatusSnapshotError(RuntimeError):
    """A predictable, safe-to-map failure while reading role-local status."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_QUEUE_COUNTS_SQL: Final = """
SELECT
  COALESCE(SUM(CASE WHEN status='PENDING' AND (next_retry_at IS NULL OR next_retry_at <= CURRENT_TIMESTAMP) THEN 1 ELSE 0 END), 0) AS pending_due,
  COALESCE(SUM(CASE WHEN status='PENDING' AND next_retry_at > CURRENT_TIMESTAMP THEN 1 ELSE 0 END), 0) AS pending_delayed,
  COALESCE(SUM(CASE WHEN status='STARTED' THEN 1 ELSE 0 END), 0) AS active,
  COALESCE(SUM(CASE WHEN status IN ('BLOCKED_CONFIG', 'FAILED_FINAL', 'CANCELLED', 'TIMEOUT') OR status NOT IN ('PENDING', 'STARTED', 'COMPLETED') THEN 1 ELSE 0 END), 0) AS blocked
FROM role_assignments
WHERE role=?
"""

_ITEMS_SQL: Final = """
SELECT
  ra.assignment_key,
  ra.status AS assignment_status,
  ra.next_retry_at,
  ra.blocked_reason,
  ra.last_error_code,
  ra.created_at AS assignment_created_at,
  ra.updated_at AS assignment_updated_at,
  wi.provider,
  wi.repository_id,
  wi.external_id,
  wi.title,
  wi.url,
  ar.hermes_run_id,
  ar.status AS run_status,
  ar.attempt_number,
  ar.started_at AS run_started_at
FROM role_assignments AS ra
JOIN work_items AS wi ON wi.id = ra.work_item_id
LEFT JOIN agent_runs AS ar ON ar.id = (
  SELECT latest.id
  FROM agent_runs AS latest
  WHERE latest.assignment_key = ra.assignment_key
  ORDER BY latest.started_at DESC, latest.id DESC
  LIMIT 1
)
WHERE ra.role=?
  AND ra.status <> 'COMPLETED'
ORDER BY
  CASE
    WHEN ra.status='STARTED' THEN 0
    WHEN ra.status IN ('BLOCKED_CONFIG', 'FAILED_FINAL', 'CANCELLED', 'TIMEOUT')
         OR ra.status NOT IN ('PENDING', 'STARTED', 'COMPLETED') THEN 1
    WHEN ra.status='PENDING' AND (ra.next_retry_at IS NULL OR ra.next_retry_at <= CURRENT_TIMESTAMP) THEN 2
    WHEN ra.status='PENDING' AND ra.next_retry_at > CURRENT_TIMESTAMP THEN 3
    ELSE 4
  END ASC,
  COALESCE(ar.started_at, ra.next_retry_at, ra.created_at, ra.updated_at) ASC,
  ra.updated_at ASC,
  ra.assignment_key ASC
LIMIT ?
"""


def read_role_status_snapshot(config: Config, *, limit: int = MAX_QUEUE_ITEMS) -> dict[str, object]:
    """Return the bounded public snapshot for exactly ``config.role``.

    The input role is intentionally not normalized: callers must supply a
    canonical role from configuration, not a request-controlled variant.
    """

    _validate_inputs(config, limit)
    path = config.db_path.resolve()
    if not path.is_file():
        raise StatusSnapshotError("missing_database")

    try:
        with closing(_open_read_only(path)) as conn:
            _verify_schema(conn)
            counters = conn.execute(_QUEUE_COUNTS_SQL, (config.role,)).fetchone()
            rows = conn.execute(_ITEMS_SQL, (config.role, limit)).fetchall()
    except sqlite3.OperationalError as exc:
        raise StatusSnapshotError(_sqlite_error_code(exc)) from exc
    except sqlite3.DatabaseError as exc:
        raise StatusSnapshotError("sqlite_error") from exc

    return {
        "role": config.role,
        "orchestratorEnabled": config.enabled,
        "generatedAt": _utc_now(),
        "queue": {
            "pendingDue": int(counters["pending_due"]),
            "pendingDelayed": int(counters["pending_delayed"]),
            "active": int(counters["active"]),
            "blocked": int(counters["blocked"]),
        },
        "items": [item for row in rows if (item := _sanitize_item(row)) is not None],
    }


def _open_read_only(path: Path) -> sqlite3.Connection:
    """Open an existing WAL-compatible SQLite database without write privileges."""

    connection = sqlite3.connect(
        f"{path.as_uri()}?mode=ro",
        uri=True,
        timeout=SQLITE_READ_TIMEOUT_SECONDS,
        isolation_level=None,
    )
    connection.execute("PRAGMA query_only=ON")
    connection.row_factory = sqlite3.Row
    return connection


def _validate_inputs(config: Config, limit: int) -> None:
    if config.role not in VALID_ROLES:
        raise ValueError("role must be a canonical orchestrator role")
    if type(limit) is not int or not 1 <= limit <= MAX_QUEUE_ITEMS:
        raise ValueError(f"limit must be an integer from 1 to {MAX_QUEUE_ITEMS}")


def _verify_schema(conn: sqlite3.Connection) -> None:
    for table, required_columns in _REQUIRED_SCHEMA.items():
        columns = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}
        if not required_columns.issubset(columns):
            raise StatusSnapshotError("schema_incompatible")


def _sanitize_item(row: sqlite3.Row) -> dict[str, object] | None:
    provider = row["provider"]
    if provider not in {"github", "gitlab"}:
        return None
    assignment_key = _required_text(row["assignment_key"])
    repository_id = _required_text(row["repository_id"])
    external_id = _required_text(row["external_id"])
    title = _bounded_text(row["title"])
    url = _validated_https_url(row["url"])
    if None in {assignment_key, repository_id, external_id, title, url}:
        return None

    assignment_status = row["assignment_status"]
    if assignment_status not in _ASSIGNMENT_STATUSES:
        # Older status values are not part of the public contract.  Preserve
        # the safe error category without exposing an arbitrary database value.
        assignment_status = "FAILED_FINAL"

    return {
        "assignmentKey": assignment_key,
        "assignmentStatus": assignment_status,
        "workItem": {
            "provider": provider,
            "repositoryId": repository_id,
            "externalId": external_id,
            "title": title,
            "url": url,
        },
        "run": _sanitize_run(row),
        "nextRetryAt": _nullable_timestamp(row["next_retry_at"]),
        "blockedReason": _nullable_text(row["blocked_reason"]),
        "lastErrorCode": _nullable_text(row["last_error_code"], maximum=MAX_ERROR_CODE_LENGTH),
    }


def _sanitize_run(row: sqlite3.Row) -> dict[str, object] | None:
    if row["hermes_run_id"] is None:
        return None
    hermes_run_id = _required_text(row["hermes_run_id"])
    started_at = _nullable_timestamp(row["run_started_at"])
    status = row["run_status"]
    attempt_number = row["attempt_number"]
    if (
        hermes_run_id is None
        or started_at is None
        or status not in _RUN_STATUSES
        or type(attempt_number) is not int
        or attempt_number < 1
    ):
        return None
    return {
        "hermesRunId": hermes_run_id,
        "status": status,
        "attemptNumber": attempt_number,
        "startedAt": started_at,
    }


def _required_text(value: object) -> str | None:
    text = _bounded_text(value)
    return text if text else None


def _nullable_text(value: object, *, maximum: int = MAX_TEXT_LENGTH) -> str | None:
    return None if value is None else _bounded_text(value, maximum=maximum)


def _bounded_text(value: object, *, maximum: int = MAX_TEXT_LENGTH) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join("".join(" " if ord(char) < 32 or ord(char) == 127 else char for char in value).split())
    return normalized[:maximum]


def _validated_https_url(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > MAX_TEXT_LENGTH or any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    return value


def _nullable_timestamp(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sqlite_error_code(exc: sqlite3.OperationalError) -> str:
    message = str(exc).lower()
    if "busy" in message or "locked" in message:
        return "sqlite_busy"
    if "no such table" in message or "no such column" in message:
        return "schema_incompatible"
    return "sqlite_error"
