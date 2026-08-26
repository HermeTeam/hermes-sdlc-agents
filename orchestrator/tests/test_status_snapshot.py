from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sdlc_orchestrator.config import Config
from sdlc_orchestrator.db import connect, ensure_assignment, init_db, mark_assignment_started, upsert_work_item
from sdlc_orchestrator.provider_base import WorkItem
from sdlc_orchestrator.status_snapshot import StatusSnapshotError, read_role_status_snapshot


def make_config(path: Path, *, role: str = "builder", enabled: bool = True) -> Config:
    return Config(
        enabled=enabled,
        role=role,
        provider="github",
        repository_id="org/repository",
        hermes_url="http://127.0.0.1:8642",
        api_server_key="not-returned",
        db_path=path,
        lock_path=path.with_suffix(".lock"),
        max_starts_per_tick=1,
        run_timeout_seconds=5400,
    )


def work_item(index: int, *, url: str | None = None, title: str = "Title") -> WorkItem:
    return WorkItem(
        provider="github",
        repository_id="org/repository",
        kind="issue",
        external_id=str(index),
        title=title,
        body="body with canary-secret",
        body_hash=f"hash-{index}",
        url=url or f"https://github.com/org/repository/issues/{index}",
        labels=("hermes:builder",),
        assignees=("hermes-builder",),
        updated_at="2026-08-26T00:00:00Z",
    )


def add_assignment(
    conn: sqlite3.Connection,
    key: str,
    *,
    role: str = "builder",
    index: int,
    status: str = "PENDING",
    retry_at: str | None = None,
    title: str = "Title",
    url: str | None = None,
    blocked_reason: str | None = None,
    error_code: str | None = None,
) -> None:
    item_id = upsert_work_item(conn, work_item(index, url=url, title=title))
    ensure_assignment(conn, key, item_id, role)
    conn.execute(
        """
        UPDATE role_assignments
        SET status=?, next_retry_at=?, blocked_reason=?, last_error_code=?, created_at=?, updated_at=?
        WHERE assignment_key=?
        """,
        (status, retry_at, blocked_reason, error_code, "2026-08-26 00:00:00", "2026-08-26 00:00:00", key),
    )


class RoleStatusSnapshotTests(unittest.TestCase):
    def test_missing_database_is_not_created(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "missing.sqlite"
            with self.assertRaisesRegex(StatusSnapshotError, "missing_database"):
                read_role_status_snapshot(make_config(path))
            self.assertFalse(path.exists())
            self.assertFalse(path.parent.joinpath("missing.sqlite-journal").exists())

    def test_read_path_does_not_mutate_database_or_create_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "orchestrator.sqlite"
            with connect(path) as conn:
                init_db(conn)
                add_assignment(conn, "read-only", index=1)
            before = path.read_bytes()
            sidecars_before = {
                suffix: path.with_name(path.name + suffix).read_bytes()
                for suffix in ("-journal", "-wal", "-shm")
                if path.with_name(path.name + suffix).exists()
            }
            snapshot = read_role_status_snapshot(make_config(path))
            self.assertEqual(snapshot["queue"], {"pendingDue": 1, "pendingDelayed": 0, "active": 0, "blocked": 0})
            self.assertEqual(path.read_bytes(), before)
            sidecars_after = {
                suffix: path.with_name(path.name + suffix).read_bytes()
                for suffix in ("-journal", "-wal", "-shm")
                if path.with_name(path.name + suffix).exists()
            }
            self.assertEqual(sidecars_after, sidecars_before)

    def test_role_isolation_and_all_queue_counters(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "orchestrator.sqlite"
            with connect(path) as conn:
                init_db(conn)
                add_assignment(conn, "due", index=1)
                add_assignment(conn, "delayed", index=2, retry_at="2999-01-01 00:00:00")
                add_assignment(conn, "blocked", index=3, status="BLOCKED_CONFIG", blocked_reason="missing\x00 configuration", error_code="CONFIG_AUTH")
                add_assignment(conn, "other-role", role="planner", index=4, status="BLOCKED_CONFIG")
                add_assignment(conn, "active", index=5)
                mark_assignment_started(conn, "active", "run-active", "sensitive-session")
            snapshot = read_role_status_snapshot(make_config(path))
            self.assertEqual(snapshot["role"], "builder")
            self.assertTrue(snapshot["orchestratorEnabled"])
            self.assertEqual(snapshot["queue"], {"pendingDue": 1, "pendingDelayed": 1, "active": 1, "blocked": 1})
            self.assertEqual([item["assignmentKey"] for item in snapshot["items"]], ["active", "blocked", "due", "delayed"])
            blocked = snapshot["items"][1]
            self.assertEqual(blocked["blockedReason"], "missing configuration")
            self.assertEqual(blocked["lastErrorCode"], "CONFIG_AUTH")
            self.assertNotIn("other-role", str(snapshot))
            self.assertNotIn("sensitive-session", str(snapshot))

    def test_ordering_precedence_and_deterministic_temporal_tie_break(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "orchestrator.sqlite"
            with connect(path) as conn:
                init_db(conn)
                add_assignment(conn, "z-due", index=1)
                add_assignment(conn, "a-due", index=2)
                add_assignment(conn, "retry", index=3, retry_at="2999-01-01 00:00:00")
                add_assignment(conn, "blocked", index=4, status="FAILED_FINAL")
                add_assignment(conn, "started", index=5)
                mark_assignment_started(conn, "started", "run-started", None)
                conn.execute("UPDATE agent_runs SET started_at='2026-08-25 00:00:00' WHERE hermes_run_id='run-started'")
            snapshot = read_role_status_snapshot(make_config(path))
            self.assertEqual([item["assignmentKey"] for item in snapshot["items"]], ["started", "blocked", "a-due", "z-due", "retry"])
            self.assertEqual(snapshot["items"][0]["run"], {"hermesRunId": "run-started", "status": "ACTIVE", "attemptNumber": 1, "startedAt": "2026-08-25T00:00:00Z"})

    def test_limit_is_validated_and_hard_capped_at_fifty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "orchestrator.sqlite"
            with connect(path) as conn:
                init_db(conn)
                for index in range(51):
                    add_assignment(conn, f"item-{index:02d}", index=index)
            snapshot = read_role_status_snapshot(make_config(path), limit=50)
            self.assertEqual(len(snapshot["items"]), 50)
            self.assertEqual(snapshot["items"][0]["assignmentKey"], "item-00")
            with self.assertRaises(ValueError):
                read_role_status_snapshot(make_config(path), limit=0)
            with self.assertRaises(ValueError):
                read_role_status_snapshot(make_config(path), limit=51)

    def test_sanitizes_sensitive_columns_and_rejects_unsafe_urls(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "orchestrator.sqlite"
            with connect(path) as conn:
                init_db(conn)
                add_assignment(conn, "safe", index=1, title="  Dashboard\nstatus\x00 query  ")
                add_assignment(conn, "plain-http", index=2, url="http://github.com/org/repository/issues/2")
                add_assignment(conn, "credential-url", index=3, url="https://token@github.com/org/repository/issues/3")
            snapshot = read_role_status_snapshot(make_config(path))
            self.assertEqual([item["assignmentKey"] for item in snapshot["items"]], ["safe"])
            item = snapshot["items"][0]
            self.assertEqual(item["workItem"]["title"], "Dashboard status query")
            serialized = str(snapshot)
            self.assertNotIn("canary-secret", serialized)
            self.assertNotIn("body_text", serialized)
            self.assertNotIn("body_hash", serialized)
            self.assertNotIn("labels_json", serialized)
            self.assertNotIn("assignees_json", serialized)
            self.assertNotIn("raw_status", serialized)
            self.assertNotIn("final_response_json", serialized)
            self.assertNotIn("sensitive-session", serialized)

    def test_nullable_run_and_retry_fields_are_normalized_to_utc(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "orchestrator.sqlite"
            with connect(path) as conn:
                init_db(conn)
                add_assignment(conn, "retry", index=1, retry_at="2999-01-01T03:00:00+03:00")
            snapshot = read_role_status_snapshot(make_config(path, enabled=False))
            self.assertFalse(snapshot["orchestratorEnabled"])
            item = snapshot["items"][0]
            self.assertIsNone(item["run"])
            self.assertEqual(item["nextRetryAt"], "2999-01-01T00:00:00Z")
            generated_at = datetime.fromisoformat(str(snapshot["generatedAt"]).replace("Z", "+00:00"))
            self.assertEqual(generated_at.tzinfo, timezone.utc)

    def test_schema_and_busy_errors_have_predictable_codes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "orchestrator.sqlite"
            sqlite3.connect(path).close()
            with self.assertRaisesRegex(StatusSnapshotError, "schema_incompatible"):
                read_role_status_snapshot(make_config(path))

            with connect(path) as conn:
                init_db(conn)
                add_assignment(conn, "item", index=1)
            with patch(
                "sdlc_orchestrator.status_snapshot._open_read_only",
                side_effect=sqlite3.OperationalError("database is locked"),
            ):
                with self.assertRaisesRegex(StatusSnapshotError, "sqlite_busy"):
                    read_role_status_snapshot(make_config(path))


if __name__ == "__main__":
    unittest.main()
