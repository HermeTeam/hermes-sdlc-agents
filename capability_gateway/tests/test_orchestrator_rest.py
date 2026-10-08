from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from capability_gateway.github_app import ProviderToken
from capability_gateway.governance import GovernanceStore
from capability_gateway.orchestrator_rest import OrchestratorGitHubFacade, OrchestratorAuthorityError


KEY = "orchestrator-builder-role-key-very-long"
OTHER = "orchestrator-planner-role-key-very-long"


class FakeBroker:
    def __init__(self) -> None:
        self.calls = []

    def mint(self, *, repository, permissions):
        self.calls.append((repository, permissions))
        return ProviderToken(
            token="github-app-token-internal-only", expires_at="2099-01-01T00:00:00Z",
            fingerprint="digest", repository=repository, permissions=permissions,
        )


class FakeResponse:
    status = 200

    def __enter__(self): return self
    def __exit__(self, *args): return None
    def read(self, _limit): return b'[]'


class OrchestratorFacadeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = GovernanceStore(Path(self.temp.name) / "test.sqlite")
        self.broker = FakeBroker()
        self.facade = OrchestratorGitHubFacade(
            store=self.store, broker=self.broker, repository="HermeTeam/sandbox",
            role_keys={"builder": KEY, "planner": OTHER},
        )
        self.headers = {
            "Authorization": "Bearer " + KEY,
            "X-HermeTeam-Orchestrator-Role": "hermes-builder",
        }

    def test_read_is_scoped_and_token_is_never_returned(self):
        with patch("capability_gateway.orchestrator_rest.urlopen", return_value=FakeResponse()) as send:
            result = self.facade.execute(
                headers=self.headers,
                request={"op": "list_issues", "repository": "HermeTeam/sandbox"},
            )
        self.assertEqual(result, {"data": []})
        self.assertEqual(self.broker.calls, [("HermeTeam/sandbox", {"issues": "read"})])
        self.assertNotIn("github-app-token", json.dumps(result))
        self.assertIn("/repos/HermeTeam/sandbox/issues", send.call_args.args[0].full_url)

    def test_write_requires_exact_human_grant_before_mint(self):
        request = {"op": "add_comment", "repository": "HermeTeam/sandbox",
                   "issue_number": 8, "comment": "Verified"}
        with self.assertRaises(OrchestratorAuthorityError) as raised:
            self.facade.execute(headers=self.headers, request=request)
        self.assertEqual(raised.exception.code, "approval_required")
        self.assertEqual(self.broker.calls, [])
        approvals = self.store.snapshot().pending_approvals
        self.assertEqual(len(approvals), 1)
        self.store.grant_once(
            approvals[0].request_id, approvals[0].tool_id, execution_ttl_seconds=60,
        )
        with patch("capability_gateway.orchestrator_rest.urlopen", return_value=FakeResponse()):
            self.facade.execute(headers=self.headers, request=request)
        self.assertEqual(self.broker.calls, [("HermeTeam/sandbox", {"issues": "write"})])
        with self.assertRaises(OrchestratorAuthorityError) as replay:
            self.facade.execute(headers=self.headers, request=request)
        self.assertEqual(replay.exception.code, "approval_required")

    def test_role_spoofing_and_cross_repo_denied_without_mint(self):
        wrong = dict(self.headers, **{"X-HermeTeam-Orchestrator-Role": "hermes-planner"})
        with self.assertRaises(OrchestratorAuthorityError):
            self.facade.execute(headers=wrong, request={"op": "list_issues", "repository": "HermeTeam/sandbox"})
        with self.assertRaises(OrchestratorAuthorityError):
            self.facade.execute(headers=self.headers, request={"op": "list_issues", "repository": "Other/repo"})
        self.assertEqual(self.broker.calls, [])

    def test_emergency_stop_prevents_provider_token(self):
        self.store.set_emergency_stop(True)
        with self.assertRaises(OrchestratorAuthorityError) as denied:
            self.facade.execute(headers=self.headers, request={"op": "list_issues", "repository": "HermeTeam/sandbox"})
        self.assertEqual(denied.exception.code, "emergency_stop")
        self.assertEqual(self.broker.calls, [])

    def test_rejects_arbitrary_operation_and_unbounded_input(self):
        invalid = [
            {"op": "arbitrary_request", "repository": "HermeTeam/sandbox"},
            {"op": "add_comment", "repository": "HermeTeam/sandbox", "issue_number": True, "comment": "x"},
            {"op": "add_comment", "repository": "HermeTeam/sandbox", "issue_number": 1, "comment": "x" * 11000},
            {"op": "remove_label", "repository": "HermeTeam/sandbox", "issue_number": 1, "label": "../admin"},
        ]
        for case in invalid:
            with self.subTest(case=case["op"]):
                with self.assertRaises(OrchestratorAuthorityError):
                    self.facade.execute(headers=self.headers, request=case)
        self.assertEqual(self.broker.calls, [])


if __name__ == "__main__":
    unittest.main()
