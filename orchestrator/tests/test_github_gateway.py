from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sdlc_orchestrator.config import Config, ConfigError
from sdlc_orchestrator.provider_github import fetch_issues, GitHubTransitionAdapter


class Response:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self): return self
    def __exit__(self, *args): return None
    def read(self, limit=2_000_001): return json.dumps({"data": self.payload}).encode()


def config(**overrides):
    values = dict(
        enabled=True, role="planner", provider="github", repository_id="HermeTeam/sandbox",
        hermes_url="http://127.0.0.1:8642", api_server_key="internal-hermes",
        db_path=Path("/opt/data/sdlc-orchestrator/test.sqlite"),
        lock_path=Path("/opt/data/sdlc-orchestrator/test.lock"),
        max_starts_per_tick=1, run_timeout_seconds=5400,
        github_auth_mode="gateway",
        github_gateway_key="role-internal-gateway-key-long-enough",
        github_gateway_url="http://capability-gateway:8787",
        github_token=None,
    )
    values.update(overrides)
    return Config(**values)


class OrchestratorGatewayClientTests(unittest.TestCase):
    def test_read_issues_without_provider_token(self):
        issue = {"number": 11, "title": "Plan", "body": "Scope", "labels": [], "assignees": []}
        with patch("sdlc_orchestrator.github_gateway.urlopen", return_value=Response([issue])) as sent:
            items = fetch_issues(config())
        self.assertEqual([item.external_id for item in items], ["11"])
        request = sent.call_args.args[0]
        self.assertEqual(request.full_url, "http://capability-gateway:8787/v1/orchestrator/github")
        self.assertEqual(json.loads(request.data)["op"], "list_issues")
        self.assertEqual(request.headers["X-hermeteam-orchestrator-role"], "hermes-planner")
        self.assertNotIn("github.com", request.full_url)

    def test_unauthenticated_gateway_configuration_does_not_fallback(self):
        with patch("sdlc_orchestrator.github_gateway.urlopen") as sent:
            with self.assertRaises(ConfigError):
                fetch_issues(config(github_gateway_key=None, github_token="a-standing-pat"))
            sent.assert_not_called()

    def test_orchestrator_transition_uses_typed_gateway_ops(self):
        cfg = config(role="incident")
        adapter = GitHubTransitionAdapter(cfg)
        with patch("sdlc_orchestrator.github_gateway.urlopen", return_value=Response([])) as sent:
            adapter._request("/repos/HermeTeam/sandbox/issues/22/comments", method="POST", body={"body": "Incident verified"})
        payload = json.loads(sent.call_args.args[0].data)
        self.assertEqual(payload["op"], "add_comment")
        self.assertEqual(payload["issue_number"], 22)
        self.assertEqual(payload["comment"], "Incident verified")

    def test_no_raw_github_paths_forwarded_to_gateway(self):
        adapter = GitHubTransitionAdapter(config())
        with self.assertRaises(ConfigError):
            adapter._request("/repos/HermeTeam/sandbox/contents/secret", method="GET")
        with self.assertRaises(ConfigError):
            adapter._request("/repos/Other/sandbox/issues/22/comments", method="GET")

    def test_external_http_gateway_origin_rejected(self):
        with self.assertRaises(ConfigError):
            fetch_issues(config(github_gateway_url="http://evil.example:8787"))


if __name__ == "__main__":
    unittest.main()
