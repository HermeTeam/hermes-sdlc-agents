from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sdlc_orchestrator.assignment import matches_role
from sdlc_orchestrator.config import Config, ConfigError
from sdlc_orchestrator.db import connect, ensure_assignment, init_db, pending_assignments, upsert_work_item
from sdlc_orchestrator.hermes_client import HermesClient
from sdlc_orchestrator.locking import LockNotAcquired, nonblocking_lock
from sdlc_orchestrator.provider_base import WorkItem
from sdlc_orchestrator.provider_github import normalize_issue as normalize_github_issue
from sdlc_orchestrator.provider_gitlab import fetch_issues as fetch_gitlab_issues
from sdlc_orchestrator.reconciler import extract_final_status


def item(labels=(), assignees=()) -> WorkItem:
    return WorkItem(
        provider="github",
        repository_id="test-project/test-project",
        kind="issue",
        external_id="123",
        title="Title",
        body="Body",
        body_hash="hash",
        url="https://github.com/test-project/test-project/issues/123",
        labels=tuple(labels),
        assignees=tuple(assignees),
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
                self.assertTrue(ensure_assignment(conn, "github:test:issue:123:builder:v1", work_item_id, "builder"))
                self.assertFalse(ensure_assignment(conn, "github:test:issue:123:builder:v1", work_item_id, "builder"))
                self.assertEqual(len(pending_assignments(conn, 10)), 1)


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


class ReconcilerTests(unittest.TestCase):
    def test_extract_final_status_from_completed_output(self) -> None:
        self.assertEqual(extract_final_status({"output": "Final: PR_READY_FOR_REVIEW"}), "PR_READY_FOR_REVIEW")

    def test_invalid_output_has_no_final_status(self) -> None:
        self.assertIsNone(extract_final_status({"output": "I did some work"}))


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


if __name__ == "__main__":
    unittest.main()
