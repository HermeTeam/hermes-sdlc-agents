from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sdlc_orchestrator.assignment import assignment_key, matches_role
from sdlc_orchestrator.config import Config, ConfigError
from sdlc_orchestrator.cli import requeue as orchestrator_requeue, status as orchestrator_status
from sdlc_orchestrator.db import connect, ensure_assignment, init_db, mark_assignment_started, pending_assignments, upsert_work_item
from sdlc_orchestrator.final_response import FinalResponseError, parse_final_response
from sdlc_orchestrator.final_response_repair import deterministic_repair_payload
from sdlc_orchestrator.hermes_client import HermesClient, HermesRunNotFound
from sdlc_orchestrator.locking import LockNotAcquired, nonblocking_lock
from sdlc_orchestrator.prompts import build_prompt
from sdlc_orchestrator.provider_base import WorkItem
from sdlc_orchestrator.provider_github import GitHubTransitionAdapter, normalize_issue as normalize_github_issue
from sdlc_orchestrator.provider_gitlab import fetch_issues as fetch_gitlab_issues
from sdlc_orchestrator.reconciler import reconcile
from sdlc_orchestrator.statuses import FinalStatus
from sdlc_orchestrator.transitions import ProviderTransitionResult
from sdlc_orchestrator.workspace_artifacts import ARTIFACT_FILE_NAME, maybe_record_self_evolution_result


def item(labels=(), assignees=(), body="Body", updated_at="2026-08-08T00:00:00Z") -> WorkItem:
    return WorkItem(
        provider="github",
        repository_id="test-project/test-project",
        kind="issue",
        external_id="123",
        title="Title",
        body=body,
        body_hash=str(abs(hash(body))),
        url="https://github.com/test-project/test-project/issues/123",
        labels=tuple(labels),
        assignees=tuple(assignees),
        updated_at=updated_at,
    )


def config(**overrides) -> Config:
    values = dict(
        enabled=True,
        role="builder",
        provider="github",
        repository_id="test-project/test-project",
        hermes_url="http://127.0.0.1:8642",
        api_server_key="secret",
        db_path=Path("/opt/data/sdlc-orchestrator/test.sqlite"),
        lock_path=Path("/opt/data/sdlc-orchestrator/test.lock"),
        max_starts_per_tick=1,
        run_timeout_seconds=5400,
        role_labels={"hermes:builder", "state:ready-for-build"},
        terminal_labels={"state:done", "state:cancelled", "hermes:blocked", "hermes:manual-only"},
        role_assignees={"hermes-builder"},
        apply_transitions=False,
        transition_comment_only=True,
    )
    values.update(overrides)
    return Config(**values)


class ConfigTests(unittest.TestCase):
    def test_config_rejects_non_local_hermes_url(self) -> None:
        old_env = dict(__import__("os").environ)
        env = __import__("os").environ
        try:
            env.clear()
            env.update(
                {
                    "ORCHESTRATOR_ROLE": "builder",
                    "ORCHESTRATOR_HERMES_URL": "https://example.com:8642",
                    "API_SERVER_KEY": "secret",
                    "REPOSITORY_ID": "test-project/test-project",
                }
            )
            with self.assertRaises(ConfigError):
                Config.from_env()
        finally:
            env.clear()
            env.update(old_env)

    def test_project_manager_role_loads_from_env(self) -> None:
        old_env = dict(__import__("os").environ)
        env = __import__("os").environ
        try:
            env.clear()
            env.update(
                {
                    "ORCHESTRATOR_ROLE": "project-manager",
                    "ORCHESTRATOR_HERMES_URL": "http://127.0.0.1:8642",
                    "API_SERVER_KEY": "secret",
                    "REPOSITORY_ID": "test-project/test-project",
                    "ORCHESTRATOR_PROJECT_MANAGER_LABELS": "Hermes:Project-Manager, state:custom-pm",
                }
            )
            loaded = Config.from_env()
        finally:
            env.clear()
            env.update(old_env)
        self.assertEqual(loaded.role, "project-manager")
        self.assertEqual(loaded.role_labels, {"hermes:project-manager", "state:custom-pm"})

    def test_status_exposes_transition_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = orchestrator_status(
                config(
                    db_path=Path(tmp) / "orchestrator.sqlite",
                    apply_transitions=True,
                    transition_comment_only=True,
                )
            )
        self.assertTrue(payload["apply_transitions"])
        self.assertTrue(payload["transition_comment_only"])

    def test_status_includes_queue_breakdowns_and_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orchestrator.sqlite"
            cfg = config(db_path=path)
            with connect(path) as conn:
                init_db(conn)
                work_item_id = upsert_work_item(conn, item(labels=("hermes:builder",)))
                ensure_assignment(conn, "pending-key", work_item_id, "builder")
                ensure_assignment(conn, "blocked-key", work_item_id, "builder")
                conn.execute("UPDATE role_assignments SET status='BLOCKED_CONFIG' WHERE assignment_key='blocked-key'")
                mark_assignment_started(conn, "pending-key", "run_1", "session")
                conn.execute("UPDATE agent_runs SET status='FAILED' WHERE assignment_key='pending-key'")
            payload = orchestrator_status(cfg)
        self.assertIn("counts", payload)
        self.assertEqual(payload["assignment_statuses"], {"BLOCKED_CONFIG": 1, "STARTED": 1})
        self.assertEqual(payload["run_statuses"], {"FAILED": 1})
        self.assertEqual(payload["queue"]["active"], 1)


class FilteringTests(unittest.TestCase):
    def test_role_filter_ignores_other_roles(self) -> None:
        self.assertFalse(matches_role(item(labels=("hermes:planner",)), config()))

    def test_terminal_labels_suppress_matching(self) -> None:
        self.assertFalse(matches_role(item(labels=("hermes:builder", "state:done")), config()))

    def test_role_assignee_matches(self) -> None:
        self.assertTrue(matches_role(item(assignees=("hermes-builder",)), config()))


class PromptTests(unittest.TestCase):
    def test_build_prompt_includes_hard_final_response_contract(self) -> None:
        prompt = build_prompt(item(), "planner", "assignment-1")
        self.assertIn("FINAL RESPONSE CONTRACT - HARD REQUIREMENT", prompt)
        self.assertIn("The first character of the final message must be { and the last character must be }", prompt)
        self.assertIn("The `evidence` field MUST be a list of objects. Never use strings in `evidence`.", prompt)

    def test_planner_prompt_discourages_redundant_issue_read(self) -> None:
        prompt = build_prompt(item(), "planner", "assignment-1")
        self.assertIn("Do not call `issue_read` or similar repository issue-read tools for this same issue unless the excerpt is insufficient", prompt)
        self.assertIn("Create a traceable implementation spec/plan only. Do not write repository changes.", prompt)


class DatabaseTests(unittest.TestCase):
    def test_sqlite_dedupe_prevents_duplicate_assignments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orchestrator.sqlite"
            with connect(path) as conn:
                init_db(conn)
                work_item_id = upsert_work_item(conn, item(labels=("hermes:builder",)))
                key = "github:test:issue:123:builder:v1"
                self.assertTrue(ensure_assignment(conn, key, work_item_id, "builder"))
                self.assertFalse(ensure_assignment(conn, key, work_item_id, "builder"))
                self.assertEqual(len(pending_assignments(conn, "builder", 10)), 1)

    def test_assignment_key_ignores_updated_at(self) -> None:
        first = item(updated_at="2026-08-08T00:00:00Z")
        changed = item(updated_at="2026-08-09T00:00:00Z")
        self.assertEqual(assignment_key(first, "builder"), assignment_key(changed, "builder"))
        self.assertIn(":v2:", assignment_key(first, "builder"))

    def test_assignment_key_changes_when_body_changes(self) -> None:
        self.assertNotEqual(assignment_key(item(body="A"), "builder"), assignment_key(item(body="B"), "builder"))

    def test_pending_assignments_are_role_filtered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orchestrator.sqlite"
            with connect(path) as conn:
                init_db(conn)
                work_item_id = upsert_work_item(conn, item(labels=("hermes:builder",)))
                ensure_assignment(conn, "planner-key", work_item_id, "planner")
                ensure_assignment(conn, "builder-key", work_item_id, "builder")
                rows = pending_assignments(conn, "builder", 10)
                self.assertEqual([row["assignment_key"] for row in rows], ["builder-key"])

    def test_pending_assignments_ignore_delayed_retries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orchestrator.sqlite"
            with connect(path) as conn:
                init_db(conn)
                work_item_id = upsert_work_item(conn, item(labels=("hermes:builder",)))
                ensure_assignment(conn, "due-key", work_item_id, "builder")
                ensure_assignment(conn, "delayed-key", work_item_id, "builder")
                conn.execute("UPDATE role_assignments SET next_retry_at='2999-01-01 00:00:00' WHERE assignment_key='delayed-key'")
                rows = pending_assignments(conn, "builder", 10)
                self.assertEqual([row["assignment_key"] for row in rows], ["due-key"])

    def test_migration_allows_second_run_attempt_for_same_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orchestrator.sqlite"
            with connect(path) as conn:
                conn.executescript(
                    """
                    CREATE TABLE work_items (
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
                    CREATE TABLE role_assignments (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      assignment_key TEXT NOT NULL UNIQUE,
                      work_item_id INTEGER NOT NULL,
                      role TEXT NOT NULL,
                      status TEXT NOT NULL DEFAULT 'PENDING',
                      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE agent_runs (
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
                      error TEXT
                    );
                    CREATE TABLE transitions (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      assignment_key TEXT NOT NULL,
                      from_role TEXT NOT NULL,
                      final_status TEXT NOT NULL,
                      next_role TEXT,
                      provider_applied INTEGER NOT NULL DEFAULT 0,
                      provider_result TEXT,
                      error TEXT,
                      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )
                work_item_id = upsert_work_item(conn, item(labels=("hermes:builder",)))
                ensure_assignment(conn, "retry-key", work_item_id, "builder")
                conn.execute("INSERT INTO agent_runs(assignment_key, hermes_run_id, session_id, status) VALUES ('retry-key', 'run_1', 'session', 'FAILED')")
                init_db(conn)
                conn.execute("UPDATE role_assignments SET status='PENDING', attempt_count=1 WHERE assignment_key='retry-key'")
                mark_assignment_started(conn, "retry-key", "run_2", "session")
                rows = conn.execute("SELECT hermes_run_id, attempt_number FROM agent_runs WHERE assignment_key='retry-key' ORDER BY id").fetchall()
        self.assertEqual([(row["hermes_run_id"], row["attempt_number"]) for row in rows], [("run_1", 1), ("run_2", 2)])

    def test_requeue_dry_run_and_update_preserve_historical_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orchestrator.sqlite"
            cfg = config(db_path=path)
            with connect(path) as conn:
                init_db(conn)
                work_item_id = upsert_work_item(conn, item(labels=("hermes:builder",)))
                ensure_assignment(conn, "blocked-key", work_item_id, "builder")
                mark_assignment_started(conn, "blocked-key", "run_1", "session")
                conn.execute("UPDATE agent_runs SET status='FAILED' WHERE assignment_key='blocked-key'")
                conn.execute("UPDATE role_assignments SET status='BLOCKED_CONFIG', blocked_reason='bad key', last_error_code='CONFIG_AUTH' WHERE assignment_key='blocked-key'")
            dry = orchestrator_requeue(cfg, statuses=["BLOCKED_CONFIG"], dry_run=True)
            self.assertEqual(dry["matched"], 1)
            self.assertEqual(dry["requeued"], 0)
            updated = orchestrator_requeue(cfg, statuses=["BLOCKED_CONFIG"])
            with connect(path) as conn:
                assignment = conn.execute("SELECT status, blocked_reason, last_error_code FROM role_assignments WHERE assignment_key='blocked-key'").fetchone()
                run_count = conn.execute("SELECT COUNT(*) AS count FROM agent_runs WHERE assignment_key='blocked-key' AND status='FAILED'").fetchone()
        self.assertEqual(updated, {"status": "OK", "matched": 1, "requeued": 1, "dry_run": False})
        self.assertEqual(dict(assignment), {"status": "PENDING", "blocked_reason": None, "last_error_code": None})
        self.assertEqual(run_count["count"], 1)


class LockTests(unittest.TestCase):
    def test_local_lock_returns_no_op_on_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "run_once.lock"
            with nonblocking_lock(lock_path):
                with self.assertRaises(LockNotAcquired):
                    with nonblocking_lock(lock_path):
                        pass


class HermesClientTests(unittest.TestCase):
    def test_client_sends_bearer_auth_and_idempotency_key(self) -> None:
        received = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                received["authorization"] = self.headers.get("Authorization")
                received["idempotency"] = self.headers.get("Idempotency-Key")
                received["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])).decode("utf-8"))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"id":"run_123"}')

            def log_message(self, *_args):
                return

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            client = HermesClient(config(hermes_url=f"http://127.0.0.1:{server.server_port}"))
            client.submit_run(model="hermes-builder", session_id="s", prompt="p", idempotency_key="key-1")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        self.assertEqual(received["authorization"], "Bearer secret")
        self.assertEqual(received["idempotency"], "key-1")
        self.assertEqual(received["body"]["model"], "hermes-builder")

    def test_get_run_raises_typed_exception_for_run_not_found(self) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":{"code":"run_not_found","message":"Run not found"}}')

            def log_message(self, *_args):
                return

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            client = HermesClient(config(hermes_url=f"http://127.0.0.1:{server.server_port}"))
            with self.assertRaises(HermesRunNotFound) as raised:
                client.get_run("run_missing")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        self.assertEqual(raised.exception.run_id, "run_missing")


class FinalResponseTests(unittest.TestCase):
    def final_payload(self, *, status="PR_READY_FOR_REVIEW", role="builder", key="key") -> dict:
        return {
            "output": json.dumps(
                {
                    "assignment_key": key,
                    "role": role,
                    "final_status": status,
                    "summary": "done",
                    "evidence": [],
                    "next_handoff": None,
                    "block_reason": None,
                }
            )
        }

    def test_valid_json_final_response_is_accepted(self) -> None:
        parsed = parse_final_response(self.final_payload(), expected_role="builder", expected_assignment_key="key")
        self.assertEqual(parsed.final_status, FinalStatus.PR_READY_FOR_REVIEW)

    def test_free_text_output_is_rejected(self) -> None:
        with self.assertRaises(FinalResponseError):
            parse_final_response({"output": "Final: PR_READY_FOR_REVIEW"}, expected_role="builder", expected_assignment_key="key")

    def test_wrong_assignment_key_is_rejected(self) -> None:
        with self.assertRaises(FinalResponseError):
            parse_final_response(self.final_payload(key="other"), expected_role="builder", expected_assignment_key="key")

    def test_wrong_role_is_rejected(self) -> None:
        with self.assertRaises(FinalResponseError):
            parse_final_response(self.final_payload(role="reviewer"), expected_role="builder", expected_assignment_key="key")

    def test_unknown_status_is_rejected(self) -> None:
        with self.assertRaises(FinalResponseError):
            parse_final_response(self.final_payload(status="BLOCKED_TOOL_UNAVAILABLE"), expected_role="builder", expected_assignment_key="key")

    def test_status_not_allowed_for_role_is_rejected(self) -> None:
        with self.assertRaises(FinalResponseError):
            parse_final_response(self.final_payload(status="BLOCKED", role="release"), expected_role="release", expected_assignment_key="key")

    def test_reviewer_blocked_is_accepted(self) -> None:
        parsed = parse_final_response(self.final_payload(status="BLOCKED", role="reviewer"), expected_role="reviewer", expected_assignment_key="key")
        self.assertEqual(parsed.final_status, FinalStatus.BLOCKED)

    def test_deterministic_repair_accepts_prose_before_json(self) -> None:
        payload = self.final_payload()
        payload["output"] = f"Completed.\n{payload['output']}"
        repaired = deterministic_repair_payload(payload, max_chars=200000)
        parsed = parse_final_response(repaired.payload, expected_role="builder", expected_assignment_key="key")
        self.assertTrue(repaired.repaired)
        self.assertEqual(parsed.final_status, FinalStatus.PR_READY_FOR_REVIEW)

    def test_deterministic_repair_accepts_prose_after_json(self) -> None:
        payload = self.final_payload()
        payload["output"] = f"{payload['output']}\nDone."
        repaired = deterministic_repair_payload(payload, max_chars=200000)
        parsed = parse_final_response(repaired.payload, expected_role="builder", expected_assignment_key="key")
        self.assertTrue(repaired.repaired)
        self.assertEqual(parsed.final_status, FinalStatus.PR_READY_FOR_REVIEW)

    def test_deterministic_repair_converts_evidence_strings_to_objects(self) -> None:
        payload = self.final_payload()
        data = json.loads(payload["output"])
        data["evidence"] = ["GitHub issue #123"]
        payload["output"] = json.dumps(data)
        repaired = deterministic_repair_payload(payload, max_chars=200000)
        parsed = parse_final_response(repaired.payload, expected_role="builder", expected_assignment_key="key")
        self.assertEqual(parsed.evidence, [{"source": "GitHub issue #123", "detail": "provided by agent as evidence text"}])

    def test_deterministic_repair_rejects_multiple_json_objects(self) -> None:
        payload = self.final_payload()
        payload["output"] = f"{payload['output']}\n{payload['output']}"
        repaired = deterministic_repair_payload(payload, max_chars=200000)
        self.assertFalse(repaired.repaired)
        self.assertIn("multiple top-level JSON objects found", "; ".join(repaired.diagnostics))

    def test_deterministic_repair_still_rejects_wrong_assignment_key_strictly(self) -> None:
        payload = self.final_payload(key="other")
        repaired = deterministic_repair_payload(payload, max_chars=200000)
        with self.assertRaises(FinalResponseError):
            parse_final_response(repaired.payload, expected_role="builder", expected_assignment_key="key")

    def test_release_blocked_no_action_is_accepted(self) -> None:
        parsed = parse_final_response(self.final_payload(status="BLOCKED_NO_ACTION", role="release"), expected_role="release", expected_assignment_key="key")
        self.assertEqual(parsed.final_status, FinalStatus.BLOCKED_NO_ACTION)


class WorkspaceArtifactTests(unittest.TestCase):
    def final_response(self, *, role="learning", status="PROPOSED_FOR_HUMAN_REVIEW", key="key", next_handoff=None):
        payload = {
            "output": json.dumps(
                {
                    "assignment_key": key,
                    "role": role,
                    "final_status": status,
                    "summary": "proposal ready",
                    "evidence": [{"source": "issue-123"}],
                    "next_handoff": next_handoff,
                    "block_reason": None,
                }
            )
        }
        return parse_final_response(payload, expected_role=role, expected_assignment_key=key)

    def test_proposed_for_human_review_appends_jsonl_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            safe_root = Path(tmp) / "opt-data"
            workspace = safe_root / "workspace"
            with patch.dict(os.environ, {"HERMES_WORKSPACE_DIR": str(workspace)}), patch("sdlc_orchestrator.workspace_artifacts.SAFE_ROOT", safe_root):
                recorded = maybe_record_self_evolution_result(item=item(), final_response=self.final_response())
            artifact = workspace / ARTIFACT_FILE_NAME
            lines = artifact.read_text(encoding="utf-8").splitlines()
        self.assertTrue(recorded)
        self.assertEqual(len(lines), 1)
        record = json.loads(lines[0])
        self.assertEqual(record["final_status"], "PROPOSED_FOR_HUMAN_REVIEW")
        self.assertEqual(record["repository_id"], "test-project/test-project")
        self.assertEqual(record["evidence"], [{"source": "issue-123"}])

    def test_non_learning_handoff_to_self_evolution_appends_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            safe_root = Path(tmp) / "opt-data"
            workspace = safe_root / "planner-workspace"
            final_response = self.final_response(
                role="planner",
                status="READY_FOR_BUILD",
                next_handoff={"target_role": "learning", "skill": "hermes-agent-self-evolution"},
            )
            with patch.dict(os.environ, {"HERMES_WORKSPACE_DIR": str(workspace)}), patch("sdlc_orchestrator.workspace_artifacts.SAFE_ROOT", safe_root):
                recorded = maybe_record_self_evolution_result(item=item(), final_response=final_response)
            artifact = workspace / ARTIFACT_FILE_NAME
            lines = artifact.read_text(encoding="utf-8").splitlines()
        self.assertTrue(recorded)
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["role"], "planner")

    def test_normal_planner_response_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            safe_root = Path(tmp) / "opt-data"
            workspace = safe_root / "workspace"
            final_response = self.final_response(role="planner", status="READY_FOR_BUILD")
            with patch.dict(os.environ, {"HERMES_WORKSPACE_DIR": str(workspace)}), patch("sdlc_orchestrator.workspace_artifacts.SAFE_ROOT", safe_root):
                recorded = maybe_record_self_evolution_result(item=item(), final_response=final_response)
        self.assertFalse(recorded)
        self.assertFalse((workspace / ARTIFACT_FILE_NAME).exists())

    def test_workspace_outside_safe_root_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            safe_root = Path(tmp) / "opt-data"
            outside = Path(tmp) / "outside"
            with self.assertLogs("sdlc_orchestrator.workspace_artifacts", level="WARNING"):
                with patch.dict(os.environ, {"HERMES_WORKSPACE_DIR": str(outside)}), patch("sdlc_orchestrator.workspace_artifacts.SAFE_ROOT", safe_root):
                    recorded = maybe_record_self_evolution_result(item=item(), final_response=self.final_response())
        self.assertFalse(recorded)
        self.assertFalse((outside / ARTIFACT_FILE_NAME).exists())


class FakeClient:
    def __init__(self, payloads: dict[str, dict]) -> None:
        self.payloads = payloads

    def get_run(self, run_id: str) -> dict:
        return self.payloads[run_id]

    def repair_final_response(self, **_kwargs) -> dict:
        raise AssertionError("unexpected repair call")


class FakeRepairClient(FakeClient):
    def __init__(self, payloads: dict[str, dict], repair_payload: dict) -> None:
        super().__init__(payloads)
        self.repair_payload = repair_payload
        self.repair_calls = []

    def repair_final_response(self, **kwargs) -> dict:
        self.repair_calls.append(kwargs)
        return self.repair_payload


class MissingThenCompletedClient:
    def __init__(self, completed_payload: dict) -> None:
        self.completed_payload = completed_payload

    def get_run(self, run_id: str) -> dict:
        if run_id == "run_missing":
            raise HermesRunNotFound(run_id, '{"error":{"code":"run_not_found"}}')
        return self.completed_payload


class FakeTransitionAdapter:
    def __init__(self) -> None:
        self.calls = []

    def apply_issue_transition(self, item, *, add_labels, remove_labels, comment, idempotency_key):
        self.calls.append(
            {
                "item": item,
                "add_labels": add_labels,
                "remove_labels": remove_labels,
                "comment": comment,
                "idempotency_key": idempotency_key,
            }
        )
        return ProviderTransitionResult(applied=True, details={"ok": True})


class ReconcilerTests(unittest.TestCase):
    def completed_payload(self, *, role: str, key: str, final_status: str, next_handoff=None) -> dict:
        return {
            "status": "completed",
            "output": json.dumps(
                {
                    "assignment_key": key,
                    "role": role,
                    "final_status": final_status,
                    "summary": "finished",
                    "evidence": [],
                    "next_handoff": next_handoff,
                    "block_reason": None,
                }
            ),
        }

    def completed_payload_with_evidence(self, *, role: str, key: str, final_status: str, evidence) -> dict:
        payload = self.completed_payload(role=role, key=key, final_status=final_status)
        data = json.loads(payload["output"])
        data["evidence"] = evidence
        payload["output"] = json.dumps(data)
        return payload

    def test_completed_run_records_transition_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orchestrator.sqlite"
            with connect(path) as conn:
                init_db(conn)
                work_item = item(labels=("hermes:planner",))
                work_item_id = upsert_work_item(conn, work_item)
                key = assignment_key(work_item, "planner")
                ensure_assignment(conn, key, work_item_id, "planner")
                mark_assignment_started(conn, key, "run_1", "session")
                summary = reconcile(conn, FakeClient({"run_1": self.completed_payload(role="planner", key=key, final_status="READY_FOR_BUILD")}), config(role="planner"))
                self.assertEqual(summary["completed"], 1)
                row = conn.execute("SELECT final_status FROM agent_runs WHERE assignment_key=?", (key,)).fetchone()
                transition = conn.execute("SELECT next_role, provider_applied FROM transitions WHERE assignment_key=?", (key,)).fetchone()
                self.assertEqual(row["final_status"], "READY_FOR_BUILD")
                self.assertEqual(transition["next_role"], "builder")
                self.assertEqual(transition["provider_applied"], 0)

    def test_artifact_write_failure_does_not_fail_reconcile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orchestrator.sqlite"
            safe_root = Path(tmp) / "opt-data"
            unsafe_workspace = Path(tmp) / "outside"
            with connect(path) as conn:
                init_db(conn)
                work_item = item(labels=("hermes:planner",))
                work_item_id = upsert_work_item(conn, work_item)
                key = assignment_key(work_item, "planner")
                ensure_assignment(conn, key, work_item_id, "planner")
                mark_assignment_started(conn, key, "run_1", "session")
                payload = self.completed_payload(
                    role="planner",
                    key=key,
                    final_status="READY_FOR_BUILD",
                    next_handoff={"target_role": "learning", "skill": "hermes-agent-self-evolution"},
                )
                with self.assertLogs("sdlc_orchestrator.workspace_artifacts", level="WARNING"):
                    with patch.dict(os.environ, {"HERMES_WORKSPACE_DIR": str(unsafe_workspace)}), patch("sdlc_orchestrator.workspace_artifacts.SAFE_ROOT", safe_root):
                        summary = reconcile(conn, FakeClient({"run_1": payload}), config(role="planner"))
                row = conn.execute("SELECT status FROM agent_runs WHERE assignment_key=?", (key,)).fetchone()
                transition = conn.execute("SELECT next_role FROM transitions WHERE assignment_key=?", (key,)).fetchone()
        self.assertEqual(summary["completed"], 1)
        self.assertEqual(row["status"], "COMPLETED")
        self.assertEqual(transition["next_role"], "builder")

    def test_missing_gateway_run_is_marked_lost_and_reconcile_continues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orchestrator.sqlite"
            adapter = FakeTransitionAdapter()
            with connect(path) as conn:
                init_db(conn)
                missing_item = item(labels=("hermes:planner",), body="missing")
                ok_item = item(labels=("hermes:planner",), body="ok")
                missing_id = upsert_work_item(conn, missing_item)
                missing_key = assignment_key(missing_item, "planner")
                ensure_assignment(conn, missing_key, missing_id, "planner")
                mark_assignment_started(conn, missing_key, "run_missing", "session-missing")
                ok_id = upsert_work_item(conn, ok_item)
                ok_key = assignment_key(ok_item, "planner")
                ensure_assignment(conn, ok_key, ok_id, "planner")
                mark_assignment_started(conn, ok_key, "run_ok", "session-ok")

                summary = reconcile(
                    conn,
                    MissingThenCompletedClient(self.completed_payload(role="planner", key=ok_key, final_status="READY_FOR_BUILD")),
                    config(role="planner", apply_transitions=True),
                    adapter,
                )

                missing_row = conn.execute("SELECT status, error FROM agent_runs WHERE assignment_key=?", (missing_key,)).fetchone()
                missing_assignment = conn.execute("SELECT status, next_retry_at FROM role_assignments WHERE assignment_key=?", (missing_key,)).fetchone()
                ok_row = conn.execute("SELECT status FROM agent_runs WHERE assignment_key=?", (ok_key,)).fetchone()
                transition = conn.execute("SELECT final_status FROM transitions WHERE assignment_key=?", (missing_key,)).fetchone()
                self.assertEqual(summary["lost"], 1)
                self.assertEqual(summary["requeued"], 1)
                self.assertEqual(summary["completed"], 1)
                self.assertEqual(missing_row["status"], "LOST")
                self.assertIn("disappeared", missing_row["error"])
                self.assertEqual(missing_assignment["status"], "PENDING")
                self.assertIsNotNone(missing_assignment["next_retry_at"])
                self.assertEqual(ok_row["status"], "COMPLETED")
                self.assertEqual(transition["final_status"], "LOST_REQUEUED")
                self.assertEqual(len(adapter.calls), 1)
                self.assertEqual(adapter.calls[0]["item"].body, "ok")

    def test_missing_gateway_run_at_max_attempts_is_failed_final(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orchestrator.sqlite"
            adapter = FakeTransitionAdapter()
            with connect(path) as conn:
                init_db(conn)
                work_item = item(labels=("hermes:planner",), body="missing")
                work_item_id = upsert_work_item(conn, work_item)
                key = assignment_key(work_item, "planner")
                ensure_assignment(conn, key, work_item_id, "planner")
                mark_assignment_started(conn, key, "run_missing", "session")
                summary = reconcile(conn, MissingThenCompletedClient({}), config(role="planner", apply_transitions=True, max_attempts_per_assignment=1), adapter)
                assignment = conn.execute("SELECT status FROM role_assignments WHERE assignment_key=?", (key,)).fetchone()
                transition = conn.execute("SELECT final_status FROM transitions WHERE assignment_key=?", (key,)).fetchone()
        self.assertEqual(summary["lost"], 1)
        self.assertEqual(summary["failed_final"], 1)
        self.assertEqual(assignment["status"], "FAILED_FINAL")
        self.assertEqual(transition["final_status"], "LOST")
        self.assertEqual(len(adapter.calls), 1)

    def test_failed_payload_invalid_api_key_blocks_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orchestrator.sqlite"
            adapter = FakeTransitionAdapter()
            with connect(path) as conn:
                init_db(conn)
                work_item = item(labels=("hermes:builder",))
                work_item_id = upsert_work_item(conn, work_item)
                key = assignment_key(work_item, "builder")
                ensure_assignment(conn, key, work_item_id, "builder")
                mark_assignment_started(conn, key, "run_1", "session")
                summary = reconcile(conn, FakeClient({"run_1": {"status": "failed", "error": {"message": "401 invalid_api_key"}}}), config(apply_transitions=True), adapter)
                assignment = conn.execute("SELECT status, blocked_reason, last_error_code FROM role_assignments WHERE assignment_key=?", (key,)).fetchone()
                transition = conn.execute("SELECT final_status FROM transitions WHERE assignment_key=?", (key,)).fetchone()
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["blocked_config"], 1)
        self.assertEqual(assignment["status"], "BLOCKED_CONFIG")
        self.assertEqual(assignment["last_error_code"], "CONFIG_AUTH")
        self.assertIn("invalid_api_key", assignment["blocked_reason"])
        self.assertEqual(transition["final_status"], "BLOCKED_CONFIG")
        self.assertEqual(len(adapter.calls), 1)

    def test_transient_failed_payload_requeues_until_attempts_exhausted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orchestrator.sqlite"
            adapter = FakeTransitionAdapter()
            with connect(path) as conn:
                init_db(conn)
                work_item = item(labels=("hermes:builder",))
                work_item_id = upsert_work_item(conn, work_item)
                key = assignment_key(work_item, "builder")
                ensure_assignment(conn, key, work_item_id, "builder")
                mark_assignment_started(conn, key, "run_1", "session")
                summary = reconcile(conn, FakeClient({"run_1": {"status": "failed", "error": "HTTP 503 temporarily unavailable"}}), config(apply_transitions=True), adapter)
                assignment = conn.execute("SELECT status, next_retry_at FROM role_assignments WHERE assignment_key=?", (key,)).fetchone()
                transition = conn.execute("SELECT final_status FROM transitions WHERE assignment_key=?", (key,)).fetchone()
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["requeued"], 1)
        self.assertEqual(assignment["status"], "PENDING")
        self.assertIsNotNone(assignment["next_retry_at"])
        self.assertEqual(transition["final_status"], "FAILED_REQUEUED")
        self.assertEqual(adapter.calls, [])

    def test_transient_failed_payload_at_max_attempts_is_failed_final(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orchestrator.sqlite"
            adapter = FakeTransitionAdapter()
            with connect(path) as conn:
                init_db(conn)
                work_item = item(labels=("hermes:builder",))
                work_item_id = upsert_work_item(conn, work_item)
                key = assignment_key(work_item, "builder")
                ensure_assignment(conn, key, work_item_id, "builder")
                mark_assignment_started(conn, key, "run_1", "session")
                summary = reconcile(conn, FakeClient({"run_1": {"status": "failed", "error": "HTTP 429 rate limit"}}), config(apply_transitions=True, max_attempts_per_assignment=1), adapter)
                assignment = conn.execute("SELECT status FROM role_assignments WHERE assignment_key=?", (key,)).fetchone()
                transition = conn.execute("SELECT final_status FROM transitions WHERE assignment_key=?", (key,)).fetchone()
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["failed_final"], 1)
        self.assertEqual(assignment["status"], "FAILED_FINAL")
        self.assertEqual(transition["final_status"], "FAILED_FINAL")
        self.assertEqual(len(adapter.calls), 1)

    def test_transition_adapter_receives_expected_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orchestrator.sqlite"
            adapter = FakeTransitionAdapter()
            with connect(path) as conn:
                init_db(conn)
                work_item = item(labels=("hermes:builder", "state:ready-for-build"))
                work_item_id = upsert_work_item(conn, work_item)
                key = assignment_key(work_item, "builder")
                ensure_assignment(conn, key, work_item_id, "builder")
                mark_assignment_started(conn, key, "run_1", "session")
                cfg = config(apply_transitions=True, transition_comment_only=False)
                reconcile(conn, FakeClient({"run_1": self.completed_payload(role="builder", key=key, final_status="PR_READY_FOR_REVIEW")}), cfg, adapter)
            self.assertEqual(adapter.calls[0]["add_labels"], {"state:review-needed", "hermes:reviewer"})
            self.assertEqual(adapter.calls[0]["remove_labels"], {"state:ready-for-build", "hermes:builder"})

    def test_active_run_times_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orchestrator.sqlite"
            with connect(path) as conn:
                init_db(conn)
                work_item = item(labels=("hermes:builder",))
                work_item_id = upsert_work_item(conn, work_item)
                key = assignment_key(work_item, "builder")
                ensure_assignment(conn, key, work_item_id, "builder")
                mark_assignment_started(conn, key, "run_1", "session")
                conn.execute("UPDATE agent_runs SET started_at='2000-01-01 00:00:00' WHERE assignment_key=?", (key,))
                summary = reconcile(conn, FakeClient({}), config(run_timeout_seconds=60))
                row = conn.execute("SELECT status, final_status FROM agent_runs WHERE assignment_key=?", (key,)).fetchone()
                transition = conn.execute("SELECT final_status, provider_applied FROM transitions WHERE assignment_key=?", (key,)).fetchone()
                self.assertEqual(summary["timeout"], 1)
                self.assertEqual(row["status"], "TIMEOUT")
                self.assertEqual(row["final_status"], "BLOCKED")
                self.assertEqual(transition["final_status"], "TIMEOUT")
                self.assertEqual(transition["provider_applied"], 0)

    def test_upstream_timeout_records_blocked_transition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orchestrator.sqlite"
            with connect(path) as conn:
                init_db(conn)
                work_item = item(labels=("hermes:builder",))
                work_item_id = upsert_work_item(conn, work_item)
                key = assignment_key(work_item, "builder")
                ensure_assignment(conn, key, work_item_id, "builder")
                mark_assignment_started(conn, key, "run_1", "session")
                summary = reconcile(conn, FakeClient({"run_1": {"status": "timeout"}}), config())
                row = conn.execute("SELECT status, final_status FROM agent_runs WHERE assignment_key=?", (key,)).fetchone()
                transition = conn.execute("SELECT final_status FROM transitions WHERE assignment_key=?", (key,)).fetchone()
                self.assertEqual(summary["timeout"], 1)
                self.assertEqual(row["status"], "TIMEOUT")
                self.assertEqual(row["final_status"], "BLOCKED")
                self.assertEqual(transition["final_status"], "TIMEOUT")

    def test_invalid_output_records_failure_transition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orchestrator.sqlite"
            adapter = FakeTransitionAdapter()
            with connect(path) as conn:
                init_db(conn)
                work_item = item(labels=("hermes:builder",))
                work_item_id = upsert_work_item(conn, work_item)
                key = assignment_key(work_item, "builder")
                ensure_assignment(conn, key, work_item_id, "builder")
                mark_assignment_started(conn, key, "run_1", "session")
                summary = reconcile(conn, FakeClient({"run_1": {"status": "completed", "output": "Final: PR_READY_FOR_REVIEW"}}), config(apply_transitions=True), adapter)
                transition = conn.execute("SELECT final_status FROM transitions WHERE assignment_key=?", (key,)).fetchone()
                self.assertEqual(summary["invalid_output"], 1)
                self.assertEqual(transition["final_status"], "INVALID_OUTPUT")
                self.assertIn("not valid JSON", adapter.calls[0]["comment"])

    def test_reconciler_completes_prose_wrapped_json_and_counts_repair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orchestrator.sqlite"
            with connect(path) as conn:
                init_db(conn)
                work_item = item(labels=("hermes:builder",))
                work_item_id = upsert_work_item(conn, work_item)
                key = assignment_key(work_item, "builder")
                ensure_assignment(conn, key, work_item_id, "builder")
                mark_assignment_started(conn, key, "run_1", "session")
                payload = self.completed_payload(role="builder", key=key, final_status="PR_READY_FOR_REVIEW")
                payload["output"] = f"Here is the final output:\n{payload['output']}"
                summary = reconcile(conn, FakeClient({"run_1": payload}), config())
                row = conn.execute("SELECT status, raw_status FROM agent_runs WHERE assignment_key=?", (key,)).fetchone()
        self.assertEqual(summary["completed"], 1)
        self.assertEqual(summary["repaired_output"], 1)
        self.assertEqual(row["status"], "COMPLETED")
        self.assertEqual(json.loads(row["raw_status"])["final_response_repair"]["method"], "deterministic")

    def test_reconciler_completes_string_evidence_and_stores_normalized_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orchestrator.sqlite"
            with connect(path) as conn:
                init_db(conn)
                work_item = item(labels=("hermes:builder",))
                work_item_id = upsert_work_item(conn, work_item)
                key = assignment_key(work_item, "builder")
                ensure_assignment(conn, key, work_item_id, "builder")
                mark_assignment_started(conn, key, "run_1", "session")
                payload = self.completed_payload_with_evidence(role="builder", key=key, final_status="PR_READY_FOR_REVIEW", evidence=["CI passed"])
                summary = reconcile(conn, FakeClient({"run_1": payload}), config())
                row = conn.execute("SELECT final_response_json FROM agent_runs WHERE assignment_key=?", (key,)).fetchone()
        self.assertEqual(summary["repaired_output"], 1)
        self.assertEqual(json.loads(row["final_response_json"])["evidence"], [{"source": "CI passed", "detail": "provided by agent as evidence text"}])

    def test_reconciler_calls_model_repair_after_deterministic_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orchestrator.sqlite"
            with connect(path) as conn:
                init_db(conn)
                work_item = item(labels=("hermes:builder",))
                work_item_id = upsert_work_item(conn, work_item)
                key = assignment_key(work_item, "builder")
                ensure_assignment(conn, key, work_item_id, "builder")
                mark_assignment_started(conn, key, "run_1", "session")
                bad_payload = {"status": "completed", "output": "not json"}
                repair_payload = self.completed_payload(role="builder", key=key, final_status="PR_READY_FOR_REVIEW")
                client = FakeRepairClient({"run_1": bad_payload}, repair_payload)
                summary = reconcile(conn, client, config())
                row = conn.execute("SELECT status, raw_status FROM agent_runs WHERE assignment_key=?", (key,)).fetchone()
        self.assertEqual(summary["completed"], 1)
        self.assertEqual(summary["model_repair_attempted"], 1)
        self.assertEqual(summary["repaired_output"], 1)
        self.assertEqual(row["status"], "COMPLETED")
        self.assertEqual(json.loads(row["raw_status"])["final_response_repair"]["method"], "model")
        self.assertEqual(client.repair_calls[0]["model"], "hermes-json-repair")

    def test_reconciler_leaves_unrepairable_output_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orchestrator.sqlite"
            adapter = FakeTransitionAdapter()
            with connect(path) as conn:
                init_db(conn)
                work_item = item(labels=("hermes:builder",))
                work_item_id = upsert_work_item(conn, work_item)
                key = assignment_key(work_item, "builder")
                ensure_assignment(conn, key, work_item_id, "builder")
                mark_assignment_started(conn, key, "run_1", "session")
                client = FakeRepairClient({"run_1": {"status": "completed", "output": "not json"}}, {"status": "completed", "output": "also not json"})
                summary = reconcile(conn, client, config(apply_transitions=True, transition_comment_only=False), adapter)
                assignment = conn.execute("SELECT status FROM role_assignments WHERE assignment_key=?", (key,)).fetchone()
        self.assertEqual(summary["invalid_output"], 1)
        self.assertEqual(summary["repair_failed"], 1)
        self.assertEqual(assignment["status"], "FAILED_FINAL")
        self.assertEqual(adapter.calls[0]["add_labels"], {"hermes:blocked"})

    def test_model_repair_disabled_makes_no_repair_client_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orchestrator.sqlite"
            with connect(path) as conn:
                init_db(conn)
                work_item = item(labels=("hermes:builder",))
                work_item_id = upsert_work_item(conn, work_item)
                key = assignment_key(work_item, "builder")
                ensure_assignment(conn, key, work_item_id, "builder")
                mark_assignment_started(conn, key, "run_1", "session")
                client = FakeRepairClient({"run_1": {"status": "completed", "output": "not json"}}, self.completed_payload(role="builder", key=key, final_status="PR_READY_FOR_REVIEW"))
                summary = reconcile(conn, client, config(final_response_model_repair_enabled=False))
        self.assertEqual(summary["invalid_output"], 1)
        self.assertEqual(summary["model_repair_attempted"], 0)
        self.assertEqual(client.repair_calls, [])

    def test_stale_completed_run_does_not_apply_normal_transition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orchestrator.sqlite"
            adapter = FakeTransitionAdapter()
            with connect(path) as conn:
                init_db(conn)
                original = item(labels=("hermes:builder",), body="old")
                work_item_id = upsert_work_item(conn, original)
                key = assignment_key(original, "builder")
                ensure_assignment(conn, key, work_item_id, "builder")
                mark_assignment_started(conn, key, "run_1", "session")
                upsert_work_item(conn, item(labels=("hermes:builder",), body="new"))
                reconcile(conn, FakeClient({"run_1": self.completed_payload(role="builder", key=key, final_status="PR_READY_FOR_REVIEW")}), config(apply_transitions=True, transition_comment_only=False), adapter)
                transition = conn.execute("SELECT final_status FROM transitions WHERE assignment_key=?", (key,)).fetchone()
                self.assertEqual(transition["final_status"], "STALE_OUTPUT")
                self.assertEqual(adapter.calls[0]["add_labels"], {"hermes:blocked"})

    def test_full_status_cycle_transition_targets(self) -> None:
        cases = [
            ("planner", "READY_FOR_BUILD", {"state:ready-for-build", "hermes:builder"}),
            ("builder", "PR_READY_FOR_REVIEW", {"state:review-needed", "hermes:reviewer"}),
            ("reviewer", "REQUEST_CHANGES", {"state:ready-for-build", "hermes:builder"}),
            ("reviewer", "APPROVE", {"state:ready-for-release", "hermes:release"}),
            ("release", "NO_ACTION", {"state:done"}),
            ("release", "BLOCKED_NO_ACTION", {"hermes:manual-only"}),
        ]
        for role, final_status, expected_labels in cases:
            with self.subTest(role=role, final_status=final_status):
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "orchestrator.sqlite"
                    adapter = FakeTransitionAdapter()
                    with connect(path) as conn:
                        init_db(conn)
                        work_item = item(labels=(f"hermes:{role}",))
                        work_item_id = upsert_work_item(conn, work_item)
                        key = assignment_key(work_item, role)
                        ensure_assignment(conn, key, work_item_id, role)
                        mark_assignment_started(conn, key, "run_1", "session")
                        reconcile(conn, FakeClient({"run_1": self.completed_payload(role=role, key=key, final_status=final_status)}), config(role=role, apply_transitions=True, transition_comment_only=False), adapter)
                    self.assertEqual(adapter.calls[0]["add_labels"], expected_labels)


class ProviderTests(unittest.TestCase):
    def test_github_normalizes_issue_and_excludes_pr_shaped_issue(self) -> None:
        issue = {
            "number": 5,
            "title": "Build",
            "body": "Do it",
            "html_url": "https://github.com/o/r/issues/5",
            "labels": [{"name": "Hermes:Builder"}],
            "assignees": [{"login": "hermes-builder"}],
            "updated_at": "2026-08-08T00:00:00Z",
        }
        normalized = normalize_github_issue(issue, "o/r")
        self.assertIsNotNone(normalized)
        self.assertEqual(normalized.labels, ("hermes:builder",))
        self.assertIsNone(normalize_github_issue({**issue, "pull_request": {}}, "o/r"))

    def test_gitlab_adapter_skips_cleanly_when_disabled(self) -> None:
        self.assertEqual(fetch_gitlab_issues(config(provider="gitlab", gitlab_token=None, gitlab_project=None)), [])

    def test_github_transition_treats_missing_label_as_removed(self) -> None:
        calls = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                calls.append(("GET", self.path))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"[]")

            def do_POST(self):  # noqa: N802
                calls.append(("POST", self.path))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")

            def do_DELETE(self):  # noqa: N802
                calls.append(("DELETE", self.path))
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"message":"Not Found"}')

            def log_message(self, *_args):
                return

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            adapter = GitHubTransitionAdapter(config(github_token="token", github_api_base_url=f"http://127.0.0.1:{server.server_port}"))
            result = adapter.apply_issue_transition(
                item(),
                add_labels=set(),
                remove_labels={"old-label"},
                comment="comment",
                idempotency_key="key",
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        self.assertTrue(result.applied)
        self.assertEqual(result.details["removed_labels"], [{"label": "old-label", "status": "already_absent"}])
        self.assertIn(("POST", "/repos/test-project/test-project/issues/123/comments"), calls)


if __name__ == "__main__":
    unittest.main()
