from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sdlc_orchestrator.assignment import assignment_key, matches_role
from sdlc_orchestrator.config import Config, ConfigError
from sdlc_orchestrator.cli import status as orchestrator_status
from sdlc_orchestrator.db import connect, ensure_assignment, init_db, mark_assignment_started, pending_assignments, upsert_work_item
from sdlc_orchestrator.final_response import FinalResponseError, parse_final_response
from sdlc_orchestrator.hermes_client import HermesClient
from sdlc_orchestrator.locking import LockNotAcquired, nonblocking_lock
from sdlc_orchestrator.provider_base import WorkItem
from sdlc_orchestrator.provider_github import GitHubTransitionAdapter, normalize_issue as normalize_github_issue
from sdlc_orchestrator.provider_gitlab import fetch_issues as fetch_gitlab_issues
from sdlc_orchestrator.reconciler import reconcile
from sdlc_orchestrator.statuses import FinalStatus
from sdlc_orchestrator.transitions import ProviderTransitionResult


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


class FilteringTests(unittest.TestCase):
    def test_role_filter_ignores_other_roles(self) -> None:
        self.assertFalse(matches_role(item(labels=("hermes:planner",)), config()))

    def test_terminal_labels_suppress_matching(self) -> None:
        self.assertFalse(matches_role(item(labels=("hermes:builder", "state:done")), config()))

    def test_role_assignee_matches(self) -> None:
        self.assertTrue(matches_role(item(assignees=("hermes-builder",)), config()))


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

    def test_release_blocked_no_action_is_accepted(self) -> None:
        parsed = parse_final_response(self.final_payload(status="BLOCKED_NO_ACTION", role="release"), expected_role="release", expected_assignment_key="key")
        self.assertEqual(parsed.final_status, FinalStatus.BLOCKED_NO_ACTION)


class FakeClient:
    def __init__(self, payloads: dict[str, dict]) -> None:
        self.payloads = payloads

    def get_run(self, run_id: str) -> dict:
        return self.payloads[run_id]


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
    def completed_payload(self, *, role: str, key: str, final_status: str) -> dict:
        return {
            "status": "completed",
            "output": json.dumps(
                {
                    "assignment_key": key,
                    "role": role,
                    "final_status": final_status,
                    "summary": "finished",
                    "evidence": [],
                    "next_handoff": None,
                    "block_reason": None,
                }
            ),
        }

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
