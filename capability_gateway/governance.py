from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from .models import RiskCategory


@dataclass(frozen=True)
class GovernanceSnapshot:
    emergency_stop: bool
    tool_exceptions: frozenset[str]
    capability_overrides: dict[str, RiskCategory]


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
        return GovernanceSnapshot(bool(stop and stop[0] == "1"), exceptions, overrides)

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

    def remove_capability_override(self, capability: str) -> None:
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM capability_overrides WHERE capability=?", (capability,))

    def grant_once(self, request_id: str, tool_id: str) -> None:
        _validate_identifier(request_id, 100)
        _validate_identifier(tool_id, 300)
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO allow_once(request_id, tool_id, consumed) VALUES (?, ?, 0) "
                "ON CONFLICT(request_id) DO UPDATE SET tool_id=excluded.tool_id, consumed=0, consumed_at=NULL",
                (request_id, tool_id),
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
