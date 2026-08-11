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
  attempt_count INTEGER NOT NULL DEFAULT 0,
  next_retry_at TEXT,
  blocked_reason TEXT,
  last_error_code TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(work_item_id) REFERENCES work_items(id)
);
CREATE TABLE IF NOT EXISTS agent_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  assignment_key TEXT NOT NULL,
  hermes_run_id TEXT NOT NULL UNIQUE,
  session_id TEXT,
  status TEXT NOT NULL,
  attempt_number INTEGER NOT NULL DEFAULT 1,
  started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  completed_at TEXT,
  raw_status TEXT,
  final_status TEXT,
  final_response_json TEXT,
  timed_out_at TEXT,
  error TEXT,
  FOREIGN KEY(assignment_key) REFERENCES role_assignments(assignment_key)
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_assignment_key ON agent_runs(assignment_key);
CREATE INDEX IF NOT EXISTS idx_agent_runs_status_started ON agent_runs(status, started_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_runs_hermes_run_id ON agent_runs(hermes_run_id);
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
    role_assignment_columns = {row["name"] for row in conn.execute("PRAGMA table_info(role_assignments)")}
    if "attempt_count" not in role_assignment_columns:
        conn.execute("ALTER TABLE role_assignments ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0")
    if "next_retry_at" not in role_assignment_columns:
        conn.execute("ALTER TABLE role_assignments ADD COLUMN next_retry_at TEXT")
    if "blocked_reason" not in role_assignment_columns:
        conn.execute("ALTER TABLE role_assignments ADD COLUMN blocked_reason TEXT")
    if "last_error_code" not in role_assignment_columns:
        conn.execute("ALTER TABLE role_assignments ADD COLUMN last_error_code TEXT")
    _migrate_agent_runs_assignment_key_unique(conn)
    agent_run_columns = {row["name"] for row in conn.execute("PRAGMA table_info(agent_runs)")}
    if "attempt_number" not in agent_run_columns:
        conn.execute("ALTER TABLE agent_runs ADD COLUMN attempt_number INTEGER NOT NULL DEFAULT 1")
    if "final_response_json" not in agent_run_columns:
        conn.execute("ALTER TABLE agent_runs ADD COLUMN final_response_json TEXT")
    if "timed_out_at" not in agent_run_columns:
        conn.execute("ALTER TABLE agent_runs ADD COLUMN timed_out_at TEXT")
    conn.execute(
        """
        UPDATE role_assignments
        SET attempt_count = (
          SELECT COALESCE(MAX(ar.attempt_number), 0)
          FROM agent_runs ar
          WHERE ar.assignment_key = role_assignments.assignment_key
        )
        WHERE attempt_count < (
          SELECT COALESCE(MAX(ar.attempt_number), 0)
          FROM agent_runs ar
          WHERE ar.assignment_key = role_assignments.assignment_key
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_runs_assignment_key ON agent_runs(assignment_key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_runs_status_started ON agent_runs(status, started_at)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_runs_hermes_run_id ON agent_runs(hermes_run_id)")


def _migrate_agent_runs_assignment_key_unique(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='agent_runs'").fetchone()
    table_sql = row["sql"] if row else ""
    if "assignment_key TEXT NOT NULL UNIQUE" not in table_sql:
        return
    conn.executescript(
        """
        CREATE TABLE agent_runs_new (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          assignment_key TEXT NOT NULL,
          hermes_run_id TEXT NOT NULL UNIQUE,
          session_id TEXT,
          status TEXT NOT NULL,
          attempt_number INTEGER NOT NULL DEFAULT 1,
          started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          completed_at TEXT,
          raw_status TEXT,
          final_status TEXT,
          final_response_json TEXT,
          timed_out_at TEXT,
          error TEXT,
          FOREIGN KEY(assignment_key) REFERENCES role_assignments(assignment_key)
        );
        INSERT INTO agent_runs_new(
          id, assignment_key, hermes_run_id, session_id, status, attempt_number,
          started_at, completed_at, raw_status, final_status, final_response_json,
          timed_out_at, error
        )
        SELECT
          id, assignment_key, hermes_run_id, session_id, status, 1,
          started_at, completed_at, raw_status, final_status, final_response_json,
          timed_out_at, error
        FROM agent_runs;
        DROP TABLE agent_runs;
        ALTER TABLE agent_runs_new RENAME TO agent_runs;
        """
    )


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
            WHERE ra.status = 'PENDING'
              AND ra.role = ?
              AND (ra.next_retry_at IS NULL OR ra.next_retry_at <= CURRENT_TIMESTAMP)
            ORDER BY COALESCE(ra.next_retry_at, ra.created_at), ra.updated_at
            LIMIT ?
            """,
            (role, limit),
        )
    )


def mark_assignment_started(conn: sqlite3.Connection, assignment_key: str, hermes_run_id: str, session_id: str | None) -> None:
    active = conn.execute(
        "SELECT 1 FROM agent_runs WHERE assignment_key=? AND status='ACTIVE'",
        (assignment_key,),
    ).fetchone()
    if active is not None:
        raise RuntimeError(f"assignment {assignment_key} already has an ACTIVE run")
    row = conn.execute("SELECT attempt_count FROM role_assignments WHERE assignment_key=?", (assignment_key,)).fetchone()
    if row is None:
        raise RuntimeError(f"assignment {assignment_key} does not exist")
    attempt_number = int(row["attempt_count"]) + 1
    conn.execute(
        """
        UPDATE role_assignments
        SET status='STARTED', attempt_count=?, next_retry_at=NULL, blocked_reason=NULL,
            last_error_code=NULL, updated_at=CURRENT_TIMESTAMP
        WHERE assignment_key=?
        """,
        (attempt_number, assignment_key),
    )
    conn.execute(
        """
        INSERT INTO agent_runs(assignment_key, hermes_run_id, session_id, status, attempt_number)
        VALUES (?, ?, ?, 'ACTIVE', ?)
        """,
        (assignment_key, hermes_run_id, session_id, attempt_number),
    )


def active_runs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT
              ar.assignment_key,
              ar.hermes_run_id,
              ar.session_id,
              ar.attempt_number,
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
    *,
    assignment_status: str | None = None,
    error: str | None = None,
    final_response_json: str | None = None,
    timed_out: bool = False,
    next_retry_at: str | None = None,
    blocked_reason: str | None = None,
    last_error_code: str | None = None,
) -> None:
    assignment_status = assignment_status or run_status
    conn.execute(
        """
        UPDATE agent_runs
        SET status=?, raw_status=?, final_status=?, final_response_json=?, error=?,
            completed_at=CURRENT_TIMESTAMP,
            timed_out_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE timed_out_at END
        WHERE assignment_key=? AND status='ACTIVE'
        """,
        (run_status, raw_status, final_status, final_response_json, error, 1 if timed_out else 0, assignment_key),
    )
    conn.execute(
        """
        UPDATE role_assignments
        SET status=?, next_retry_at=?, blocked_reason=?, last_error_code=?, updated_at=CURRENT_TIMESTAMP
        WHERE assignment_key=?
        """,
        (assignment_status, next_retry_at, blocked_reason, last_error_code, assignment_key),
    )


def assignment_attempt_count(conn: sqlite3.Connection, assignment_key: str) -> int:
    row = conn.execute("SELECT attempt_count FROM role_assignments WHERE assignment_key=?", (assignment_key,)).fetchone()
    return int(row["attempt_count"]) if row else 0


def requeue_assignment(conn: sqlite3.Connection, assignment_key: str, *, next_retry_at: str | None = None, reason: str | None = None) -> None:
    conn.execute(
        """
        UPDATE role_assignments
        SET status='PENDING', next_retry_at=?, blocked_reason=NULL, last_error_code=NULL,
            updated_at=CURRENT_TIMESTAMP
        WHERE assignment_key=?
        """,
        (next_retry_at, assignment_key),
    )
    if reason is not None:
        conn.execute(
            """
            INSERT INTO transitions(assignment_key, from_role, final_status, next_role, provider_applied, provider_result)
            SELECT assignment_key, role, ?, NULL, 0, ? FROM role_assignments WHERE assignment_key=?
            """,
            (reason, '{"mode":"local-requeue"}', assignment_key),
        )


def block_assignment(
    conn: sqlite3.Connection,
    assignment_key: str,
    *,
    status: str,
    blocked_reason: str,
    last_error_code: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE role_assignments
        SET status=?, blocked_reason=?, last_error_code=?, next_retry_at=NULL, updated_at=CURRENT_TIMESTAMP
        WHERE assignment_key=?
        """,
        (status, blocked_reason, last_error_code, assignment_key),
    )


def assignment_status_counts(conn: sqlite3.Connection, role: str | None = None) -> dict[str, int]:
    if role is None:
        rows = conn.execute("SELECT status, COUNT(*) AS count FROM role_assignments GROUP BY status").fetchall()
    else:
        rows = conn.execute("SELECT status, COUNT(*) AS count FROM role_assignments WHERE role=? GROUP BY status", (role,)).fetchall()
    return {row["status"]: int(row["count"]) for row in rows}


def run_status_counts(conn: sqlite3.Connection, role: str | None = None) -> dict[str, int]:
    if role is None:
        rows = conn.execute("SELECT status, COUNT(*) AS count FROM agent_runs GROUP BY status").fetchall()
    else:
        rows = conn.execute(
            """
            SELECT ar.status, COUNT(*) AS count
            FROM agent_runs ar
            JOIN role_assignments ra ON ra.assignment_key = ar.assignment_key
            WHERE ra.role=?
            GROUP BY ar.status
            """,
            (role,),
        ).fetchall()
    return {row["status"]: int(row["count"]) for row in rows}


def queue_counts(conn: sqlite3.Connection, role: str) -> dict[str, int]:
    row = conn.execute(
        """
        SELECT
          SUM(CASE WHEN status='PENDING' AND (next_retry_at IS NULL OR next_retry_at <= CURRENT_TIMESTAMP) THEN 1 ELSE 0 END) AS pending_due,
          SUM(CASE WHEN status='PENDING' AND next_retry_at > CURRENT_TIMESTAMP THEN 1 ELSE 0 END) AS pending_delayed,
          SUM(CASE WHEN status='STARTED' THEN 1 ELSE 0 END) AS active
        FROM role_assignments
        WHERE role=?
        """,
        (role,),
    ).fetchone()
    return {key: int(row[key] or 0) for key in ("pending_due", "pending_delayed", "active")}


def matching_requeue_assignments(
    conn: sqlite3.Connection,
    *,
    role: str,
    statuses: set[str],
    assignment_key: str | None = None,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    placeholders = ",".join("?" for _ in statuses)
    params: list[object] = [role, *sorted(statuses)]
    where = f"role=? AND status IN ({placeholders})"
    if assignment_key is not None:
        where += " AND assignment_key=?"
        params.append(assignment_key)
    sql = f"SELECT assignment_key, role, status, attempt_count, blocked_reason, last_error_code FROM role_assignments WHERE {where} ORDER BY updated_at ASC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return list(conn.execute(sql, params))


def requeue_assignments(
    conn: sqlite3.Connection,
    *,
    role: str,
    statuses: set[str],
    assignment_key: str | None = None,
    limit: int | None = None,
) -> int:
    rows = matching_requeue_assignments(conn, role=role, statuses=statuses, assignment_key=assignment_key, limit=limit)
    for row in rows:
        conn.execute(
            """
            UPDATE role_assignments
            SET status='PENDING', next_retry_at=NULL, blocked_reason=NULL, last_error_code=NULL,
                updated_at=CURRENT_TIMESTAMP
            WHERE assignment_key=?
            """,
            (row["assignment_key"],),
        )
    return len(rows)


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
