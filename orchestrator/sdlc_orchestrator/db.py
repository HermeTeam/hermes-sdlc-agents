from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator

from .provider_base import WorkItem


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS work_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider TEXT NOT NULL,
  repository_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  external_id TEXT NOT NULL,
  title TEXT NOT NULL,
  body_text TEXT NOT NULL DEFAULT '',
  body_hash TEXT NOT NULL,
  url TEXT NOT NULL,
  labels_json TEXT NOT NULL,
  assignees_json TEXT NOT NULL,
  updated_at TEXT,
  last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(provider, repository_id, external_id)
);
CREATE TABLE IF NOT EXISTS role_assignments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  assignment_key TEXT NOT NULL UNIQUE,
  work_item_id INTEGER NOT NULL,
  role TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(work_item_id) REFERENCES work_items(id)
);
CREATE TABLE IF NOT EXISTS agent_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  assignment_key TEXT NOT NULL UNIQUE,
  hermes_run_id TEXT NOT NULL UNIQUE,
  session_id TEXT,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  completed_at TEXT,
  raw_status TEXT,
  final_status TEXT,
  final_response_json TEXT,
  timed_out_at TEXT,
  error TEXT,
  FOREIGN KEY(assignment_key) REFERENCES role_assignments(assignment_key)
);
CREATE TABLE IF NOT EXISTS transitions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  assignment_key TEXT NOT NULL,
  from_role TEXT NOT NULL,
  final_status TEXT NOT NULL,
  next_role TEXT,
  provider_applied INTEGER NOT NULL DEFAULT 0,
  provider_result TEXT,
  error TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(assignment_key) REFERENCES role_assignments(assignment_key)
);
CREATE TABLE IF NOT EXISTS poll_state (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    work_item_columns = {row["name"] for row in conn.execute("PRAGMA table_info(work_items)")}
    if "body_text" not in work_item_columns:
        conn.execute("ALTER TABLE work_items ADD COLUMN body_text TEXT NOT NULL DEFAULT ''")
    agent_run_columns = {row["name"] for row in conn.execute("PRAGMA table_info(agent_runs)")}
    if "final_response_json" not in agent_run_columns:
        conn.execute("ALTER TABLE agent_runs ADD COLUMN final_response_json TEXT")
    if "timed_out_at" not in agent_run_columns:
        conn.execute("ALTER TABLE agent_runs ADD COLUMN timed_out_at TEXT")


def upsert_work_item(conn: sqlite3.Connection, item: WorkItem) -> int:
    conn.execute(
        """
        INSERT INTO work_items(provider, repository_id, kind, external_id, title, body_text, body_hash, url, labels_json, assignees_json, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(provider, repository_id, external_id) DO UPDATE SET
          title=excluded.title,
          body_text=excluded.body_text,
          body_hash=excluded.body_hash,
          url=excluded.url,
          labels_json=excluded.labels_json,
          assignees_json=excluded.assignees_json,
          updated_at=excluded.updated_at,
          last_seen_at=CURRENT_TIMESTAMP
        """,
        (
            item.provider,
            item.repository_id,
            item.kind,
            item.external_id,
            item.title,
            item.body,
            item.body_hash,
            item.url,
            "\n".join(item.labels),
            "\n".join(item.assignees),
            item.updated_at,
        ),
    )
    row = conn.execute(
        "SELECT id FROM work_items WHERE provider=? AND repository_id=? AND external_id=?",
        (item.provider, item.repository_id, item.external_id),
    ).fetchone()
    return int(row["id"])


def ensure_assignment(conn: sqlite3.Connection, key: str, work_item_id: int, role: str) -> bool:
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO role_assignments(assignment_key, work_item_id, role)
        VALUES (?, ?, ?)
        """,
        (key, work_item_id, role),
    )
    return cur.rowcount == 1


def pending_assignments(conn: sqlite3.Connection, role: str, limit: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT ra.assignment_key, ra.role, wi.*
            FROM role_assignments ra
            JOIN work_items wi ON wi.id = ra.work_item_id
            WHERE ra.status = 'PENDING' AND ra.role = ?
            ORDER BY ra.created_at ASC
            LIMIT ?
            """,
            (role, limit),
        )
    )


def mark_assignment_started(conn: sqlite3.Connection, assignment_key: str, hermes_run_id: str, session_id: str | None) -> None:
    conn.execute(
        "UPDATE role_assignments SET status='STARTED', updated_at=CURRENT_TIMESTAMP WHERE assignment_key=?",
        (assignment_key,),
    )
    conn.execute(
        """
        INSERT INTO agent_runs(assignment_key, hermes_run_id, session_id, status)
        VALUES (?, ?, ?, 'ACTIVE')
        """,
        (assignment_key, hermes_run_id, session_id),
    )


def active_runs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT
              ar.assignment_key,
              ar.hermes_run_id,
              ar.session_id,
              ar.status AS run_status,
              ar.started_at,
              ra.role,
              wi.provider,
              wi.repository_id,
              wi.kind,
              wi.external_id,
              wi.title,
              wi.body_text,
              wi.body_hash,
              wi.url,
              wi.labels_json,
              wi.assignees_json,
              wi.updated_at
            FROM agent_runs ar
            JOIN role_assignments ra ON ra.assignment_key = ar.assignment_key
            JOIN work_items wi ON wi.id = ra.work_item_id
            WHERE ar.status='ACTIVE'
            ORDER BY ar.started_at ASC
            """
        )
    )


def mark_run_finished(
    conn: sqlite3.Connection,
    assignment_key: str,
    run_status: str,
    final_status: str | None,
    raw_status: str,
    error: str | None = None,
    final_response_json: str | None = None,
    timed_out: bool = False,
) -> None:
    conn.execute(
        """
        UPDATE agent_runs
        SET status=?, raw_status=?, final_status=?, final_response_json=?, error=?,
            completed_at=CURRENT_TIMESTAMP,
            timed_out_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE timed_out_at END
        WHERE assignment_key=?
        """,
        (run_status, raw_status, final_status, final_response_json, error, 1 if timed_out else 0, assignment_key),
    )
    conn.execute(
        "UPDATE role_assignments SET status=?, updated_at=CURRENT_TIMESTAMP WHERE assignment_key=?",
        (run_status, assignment_key),
    )


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    result = {}
    for table in ("work_items", "role_assignments", "agent_runs", "transitions"):
        result[table] = int(conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])
    return result


def record_transition(
    conn: sqlite3.Connection,
    *,
    assignment_key: str,
    from_role: str,
    final_status: str,
    next_role: str | None,
    provider_applied: bool,
    provider_result: str | None = None,
    error: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO transitions(assignment_key, from_role, final_status, next_role, provider_applied, provider_result, error)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (assignment_key, from_role, final_status, next_role, 1 if provider_applied else 0, provider_result, error),
    )


def row_to_work_item(row: sqlite3.Row) -> WorkItem:
    return WorkItem(
        provider=row["provider"],
        repository_id=row["repository_id"],
        kind=row["kind"],
        external_id=row["external_id"],
        title=row["title"],
        body=row["body_text"],
        body_hash=row["body_hash"],
        url=row["url"],
        labels=tuple(filter(None, row["labels_json"].split("\n"))),
        assignees=tuple(filter(None, row["assignees_json"].split("\n"))),
        updated_at=row["updated_at"],
    )
