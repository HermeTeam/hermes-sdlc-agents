from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

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


@dataclass(frozen=True)
class GovernanceSnapshot:
    emergency_stop: bool
    tool_exceptions: frozenset[str]
    capability_overrides: dict[str, RiskCategory]
    pending_approvals: tuple[PendingApproval, ...]


class GovernanceStore:
    """SQLite-backed governance state.

    The emergency stop is deliberately independent of the model judge and catalog
    adapters. Once active, resolver/execution paths can fail closed even when all
    external dependencies are unavailable.
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
            pending = tuple(
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

    def remove_capability_override(self, capability: str) -> None:
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM capability_overrides WHERE capability=?", (capability,))

    def grant_once(self, request_id: str, tool_id: str) -> None:
        _validate_identifier(request_id, 100)
        _validate_identifier(tool_id, 300)
        with self._lock, self._connect() as db:
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

    def consume_once(self, request_id: str, tool_id: str) -> bool:
        """Atomically consumes the one-shot grant; retries cannot reuse it."""
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


def _validate_identifier(value: str, limit: int) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("invalid identifier")
    if any(ord(char) < 32 for char in value):
        raise ValueError("control characters are not allowed")
