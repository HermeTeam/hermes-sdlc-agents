from __future__ import annotations

import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .authority import InvocationContext
from .models import RiskCategory


@dataclass(frozen=True)
class PendingApproval:
    request_id: str
    intent: str
    tool_id: str
    capability: str
    requested_category: RiskCategory
    allowed_category: RiskCategory
    recommended_tool_id: str | None
    reason: str
    created_at: str
    agent_id: str | None = None
    run_id: str | None = None
    repository: str | None = None
    branch: str | None = None
    args_hash: str | None = None


@dataclass(frozen=True)
class GovernanceSnapshot:
    emergency_stop: bool
    tool_exceptions: frozenset[str]
    capability_overrides: dict[str, RiskCategory]
    pending_approvals: tuple[PendingApproval, ...]


class GovernanceStore:
    """SQLite-backed governance state.

    The emergency stop is deliberately independent of the model judge and catalog
    adapters. Once active, resolver/execution paths fail closed even when external
    dependencies are unavailable.

    Legacy resolver approvals are preserved. Dynamic execution approvals are stored
    separately and bind human authority to agent/run/repository/branch/args_hash.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS global_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                INSERT OR IGNORE INTO global_state(key, value)
                VALUES ('emergency_stop', '0');

                CREATE TABLE IF NOT EXISTS tool_exceptions (
                    tool_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS capability_overrides (
                    capability TEXT PRIMARY KEY,
                    category INTEGER NOT NULL CHECK(category BETWEEN 0 AND 4),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS allow_once (
                    request_id TEXT PRIMARY KEY,
                    tool_id TEXT NOT NULL,
                    consumed INTEGER NOT NULL DEFAULT 0 CHECK(consumed IN (0, 1)),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    consumed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS pending_approvals (
                    request_id TEXT PRIMARY KEY,
                    intent TEXT NOT NULL,
                    tool_id TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    requested_category INTEGER NOT NULL CHECK(requested_category BETWEEN 0 AND 4),
                    allowed_category INTEGER NOT NULL CHECK(allowed_category BETWEEN 0 AND 4),
                    recommended_tool_id TEXT,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','APPROVED_ONCE','EXCEPTION','CAPABILITY_OVERRIDE','SUPERSEDED')),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    decided_at TEXT
                );

                CREATE TABLE IF NOT EXISTS pending_execution_approvals (
                    request_id TEXT PRIMARY KEY,
                    intent TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    tool_id TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    repository TEXT NOT NULL,
                    branch TEXT,
                    args_hash TEXT NOT NULL,
                    requested_category INTEGER NOT NULL CHECK(requested_category BETWEEN 0 AND 4),
                    allowed_category INTEGER NOT NULL CHECK(allowed_category BETWEEN 0 AND 4),
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','APPROVED_ONCE','EXCEPTION','CAPABILITY_OVERRIDE','SUPERSEDED')),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    decided_at TEXT
                );

                CREATE TABLE IF NOT EXISTS execution_grants (
                    grant_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    authority_source TEXT NOT NULL CHECK(authority_source IN ('AUTO','HUMAN','EXCEPTION','CAPABILITY_OVERRIDE')),
                    agent_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    tool_id TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    repository TEXT NOT NULL,
                    branch TEXT,
                    args_hash TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed INTEGER NOT NULL DEFAULT 0 CHECK(consumed IN (0, 1)),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    consumed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_execution_grants_match
                ON execution_grants(agent_id,run_id,tool_id,repository,args_hash,consumed,expires_at);
                """
            )

    def snapshot(self) -> GovernanceSnapshot:
        with self._lock, self._connect() as db:
            stop = db.execute(
                "SELECT value FROM global_state WHERE key='emergency_stop'"
            ).fetchone()
            exceptions = frozenset(
                row[0] for row in db.execute("SELECT tool_id FROM tool_exceptions")
            )
            overrides = {
                row[0]: RiskCategory(int(row[1]))
                for row in db.execute(
                    "SELECT capability, category FROM capability_overrides"
                )
            }
            legacy_pending = [
                PendingApproval(
                    request_id=row[0],
                    intent=row[1],
                    tool_id=row[2],
                    capability=row[3],
                    requested_category=RiskCategory(int(row[4])),
                    allowed_category=RiskCategory(int(row[5])),
                    recommended_tool_id=row[6],
                    reason=row[7],
                    created_at=row[8],
                )
                for row in db.execute(
                    "SELECT request_id,intent,tool_id,capability,requested_category,allowed_category,recommended_tool_id,reason,created_at "
                    "FROM pending_approvals WHERE status='PENDING' ORDER BY created_at DESC LIMIT 100"
                )
            ]
            execution_pending = [
                PendingApproval(
                    request_id=row[0],
                    intent=row[1],
                    tool_id=row[4],
                    capability=row[5],
                    requested_category=RiskCategory(int(row[10])),
                    allowed_category=RiskCategory(int(row[11])),
                    recommended_tool_id=None,
                    reason=row[12],
                    created_at=row[13],
                    agent_id=row[2],
                    run_id=row[3],
                    repository=row[6],
                    branch=row[7],
                    args_hash=row[8],
                )
                for row in db.execute(
                    "SELECT request_id,intent,agent_id,run_id,tool_id,capability,repository,branch,args_hash,"
                    "status,requested_category,allowed_category,reason,created_at "
                    "FROM pending_execution_approvals WHERE status='PENDING' ORDER BY created_at DESC LIMIT 100"
                )
            ]
            pending = tuple(
                sorted(
                    legacy_pending + execution_pending,
                    key=lambda item: item.created_at,
                    reverse=True,
                )[:100]
            )
        return GovernanceSnapshot(
            bool(stop and stop[0] == "1"),
            exceptions,
            overrides,
            pending,
        )

    def record_pending_approval(
        self,
        *,
        request_id: str,
        intent: str,
        tool_id: str,
        capability: str,
        requested_category: RiskCategory,
        allowed_category: RiskCategory,
        recommended_tool_id: str | None,
        reason: str,
    ) -> None:
        for value, limit in ((request_id, 100), (tool_id, 300), (capability, 160)):
            _validate_identifier(value, limit)
        if not intent or len(intent) > 2000 or not reason or len(reason) > 1000:
            raise ValueError("invalid approval text")
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO pending_approvals(request_id,intent,tool_id,capability,requested_category,allowed_category,recommended_tool_id,reason,status) "
                "VALUES (?,?,?,?,?,?,?,?, 'PENDING') "
                "ON CONFLICT(request_id) DO UPDATE SET intent=excluded.intent,tool_id=excluded.tool_id,capability=excluded.capability,"
                "requested_category=excluded.requested_category,allowed_category=excluded.allowed_category,recommended_tool_id=excluded.recommended_tool_id,"
                "reason=excluded.reason,status='PENDING',decided_at=NULL",
                (
                    request_id,
                    intent,
                    tool_id,
                    capability,
                    int(requested_category),
                    int(allowed_category),
                    recommended_tool_id,
                    reason,
                ),
            )

    def record_execution_approval(
        self,
        *,
        context: InvocationContext,
        allowed_category: RiskCategory,
        reason: str,
        intent: str | None = None,
    ) -> None:
        if len(reason) > 1000:
            raise ValueError("invalid approval reason")
        text = intent or f"execute {context.tool_id}"
        if len(text) > 2000:
            text = text[:2000]
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO pending_execution_approvals("
                "request_id,intent,agent_id,run_id,tool_id,capability,repository,branch,args_hash,"
                "requested_category,allowed_category,reason,status) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'PENDING') "
                "ON CONFLICT(request_id) DO UPDATE SET intent=excluded.intent,agent_id=excluded.agent_id,run_id=excluded.run_id,"
                "tool_id=excluded.tool_id,capability=excluded.capability,repository=excluded.repository,branch=excluded.branch,"
                "args_hash=excluded.args_hash,requested_category=excluded.requested_category,allowed_category=excluded.allowed_category,"
                "reason=excluded.reason,status='PENDING',decided_at=NULL",
                (
                    context.request_id,
                    text,
                    context.agent_id,
                    context.run_id,
                    context.tool_id,
                    context.capability,
                    context.repository,
                    context.branch,
                    context.args_hash,
                    int(context.category),
                    int(allowed_category),
                    reason,
                ),
            )

    def set_emergency_stop(self, enabled: bool) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE global_state SET value=? WHERE key='emergency_stop'",
                ("1" if enabled else "0",),
            )

    def add_tool_exception(self, tool_id: str) -> None:
        _validate_identifier(tool_id, 300)
        with self._lock, self._connect() as db:
            db.execute("INSERT OR IGNORE INTO tool_exceptions(tool_id) VALUES (?)", (tool_id,))
            db.execute(
                "UPDATE pending_approvals SET status='EXCEPTION',decided_at=CURRENT_TIMESTAMP WHERE tool_id=? AND status='PENDING'",
                (tool_id,),
            )
            db.execute(
                "UPDATE pending_execution_approvals SET status='EXCEPTION',decided_at=CURRENT_TIMESTAMP WHERE tool_id=? AND status='PENDING'",
                (tool_id,),
            )

    def remove_tool_exception(self, tool_id: str) -> None:
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM tool_exceptions WHERE tool_id=?", (tool_id,))

    def set_capability_override(self, capability: str, category: RiskCategory) -> None:
        _validate_identifier(capability, 160)
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO capability_overrides(capability, category) VALUES (?, ?) "
                "ON CONFLICT(capability) DO UPDATE SET category=excluded.category, created_at=CURRENT_TIMESTAMP",
                (capability, int(category)),
            )
            db.execute(
                "UPDATE pending_approvals SET status='CAPABILITY_OVERRIDE',decided_at=CURRENT_TIMESTAMP WHERE capability=? AND status='PENDING'",
                (capability,),
            )
            db.execute(
                "UPDATE pending_execution_approvals SET status='CAPABILITY_OVERRIDE',decided_at=CURRENT_TIMESTAMP WHERE capability=? AND status='PENDING'",
                (capability,),
            )

    def remove_capability_override(self, capability: str) -> None:
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM capability_overrides WHERE capability=?", (capability,))

    def grant_once(self, request_id: str, tool_id: str, *, execution_ttl_seconds: int = 60) -> str | None:
        """Approve a pending request once.

        Legacy resolver requests keep the old allow_once behavior. Exact execution
        requests produce a scoped grant bound to agent/run/repository/branch/args_hash.
        """
        _validate_identifier(request_id, 100)
        _validate_identifier(tool_id, 300)
        ttl = max(10, min(int(execution_ttl_seconds), 900))
        with self._lock, self._connect() as db:
            execution = db.execute(
                "SELECT agent_id,run_id,tool_id,capability,repository,branch,args_hash "
                "FROM pending_execution_approvals WHERE request_id=? AND tool_id=? AND status='PENDING'",
                (request_id, tool_id),
            ).fetchone()
            if execution is not None:
                grant_id = secrets.token_urlsafe(24)
                expires_at = _sqlite_time(datetime.now(timezone.utc) + timedelta(seconds=ttl))
                db.execute(
                    "INSERT INTO execution_grants(grant_id,request_id,authority_source,agent_id,run_id,tool_id,capability,repository,branch,args_hash,expires_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        grant_id,
                        request_id,
                        "HUMAN",
                        execution[0],
                        execution[1],
                        execution[2],
                        execution[3],
                        execution[4],
                        execution[5],
                        execution[6],
                        expires_at,
                    ),
                )
                db.execute(
                    "UPDATE pending_execution_approvals SET status='APPROVED_ONCE',decided_at=CURRENT_TIMESTAMP WHERE request_id=?",
                    (request_id,),
                )
                return grant_id

            pending = db.execute(
                "SELECT 1 FROM pending_approvals WHERE request_id=? AND tool_id=? AND status='PENDING'",
                (request_id, tool_id),
            ).fetchone()
            if pending is None:
                raise ValueError("approval request is not pending")
            db.execute(
                "INSERT INTO allow_once(request_id, tool_id, consumed) VALUES (?, ?, 0) "
                "ON CONFLICT(request_id) DO UPDATE SET tool_id=excluded.tool_id, consumed=0, consumed_at=NULL",
                (request_id, tool_id),
            )
            db.execute(
                "UPDATE pending_approvals SET status='APPROVED_ONCE',decided_at=CURRENT_TIMESTAMP WHERE request_id=?",
                (request_id,),
            )
            return None

    def consume_execution_grant(self, context: InvocationContext) -> str | None:
        """Atomically consume a human exact-invocation grant matching this request."""
        now = _sqlite_time(datetime.now(timezone.utc))
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT grant_id FROM execution_grants "
                "WHERE agent_id=? AND run_id=? AND tool_id=? AND capability=? AND repository=? "
                "AND COALESCE(branch,'')=COALESCE(?, '') AND args_hash=? AND consumed=0 AND expires_at>? "
                "ORDER BY created_at ASC LIMIT 1",
                (
                    context.agent_id,
                    context.run_id,
                    context.tool_id,
                    context.capability,
                    context.repository,
                    context.branch,
                    context.args_hash,
                    now,
                ),
            ).fetchone()
            if row is None:
                return None
            grant_id = row[0]
            cursor = db.execute(
                "UPDATE execution_grants SET consumed=1,consumed_at=CURRENT_TIMESTAMP WHERE grant_id=? AND consumed=0",
                (grant_id,),
            )
            return grant_id if cursor.rowcount == 1 else None

    def record_auto_execution(self, context: InvocationContext, *, authority_source: str = "AUTO") -> str:
        if authority_source not in {"AUTO", "EXCEPTION", "CAPABILITY_OVERRIDE"}:
            raise ValueError("invalid authority source")
        grant_id = secrets.token_urlsafe(24)
        now = datetime.now(timezone.utc)
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO execution_grants(grant_id,request_id,authority_source,agent_id,run_id,tool_id,capability,repository,branch,args_hash,expires_at,consumed,consumed_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,1,CURRENT_TIMESTAMP)",
                (
                    grant_id,
                    context.request_id,
                    authority_source,
                    context.agent_id,
                    context.run_id,
                    context.tool_id,
                    context.capability,
                    context.repository,
                    context.branch,
                    context.args_hash,
                    _sqlite_time(now + timedelta(seconds=60)),
                ),
            )
        return grant_id

    def consume_once(self, request_id: str, tool_id: str) -> bool:
        """Atomically consumes the legacy resolver one-shot grant."""
        with self._lock, self._connect() as db:
            cursor = db.execute(
                "UPDATE allow_once SET consumed=1, consumed_at=CURRENT_TIMESTAMP "
                "WHERE request_id=? AND tool_id=? AND consumed=0",
                (request_id, tool_id),
            )
            return cursor.rowcount == 1

    def has_unconsumed_once(self, request_id: str, tool_id: str) -> bool:
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT 1 FROM allow_once WHERE request_id=? AND tool_id=? AND consumed=0",
                (request_id, tool_id),
            ).fetchone()
            return row is not None


def _sqlite_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _validate_identifier(value: str, limit: int) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("invalid identifier")
    if any(ord(char) < 32 for char in value):
        raise ValueError("control characters are not allowed")
