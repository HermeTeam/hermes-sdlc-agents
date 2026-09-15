from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from capability_gateway.github_app import ProviderToken
from capability_gateway.governance import GovernanceStore
from capability_gateway.mcp_proxy import DynamicAuthorityProxy, MCPAuthorityBlocked
from capability_gateway.models import RiskCategory


KEY = "builder-gateway-key-that-is-long-enough"


class FakeBroker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def mint(self, *, repository: str, permissions: dict[str, str]) -> ProviderToken:
        self.calls.append((repository, dict(permissions)))
        return ProviderToken(
            token="provider-token-never-returned-to-agent",
            expires_at="2099-01-01T00:00:00Z",
            fingerprint="deadbeef",
            repository=repository,
            permissions=dict(permissions),
        )


class DynamicAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = GovernanceStore(Path(self.tmp.name) / "governance.sqlite3")
        self.broker = FakeBroker()
        self.proxy = DynamicAuthorityProxy(
            store=self.store,
            max_auto_category=RiskCategory.MEDIUM,
            token_broker=self.broker,  # type: ignore[arg-type]
            upstream_url="https://api.githubcopilot.com/mcp/",
            builder_key=KEY,
            configured_repository="HermeTeam/demo",
            default_branch="main",
            protected_patterns=(".github/workflows/**", "policies/**", "CODEOWNERS"),
            execution_grant_ttl_seconds=60,
        )
        self.headers = {
            "Authorization": f"Bearer {KEY}",
            "X-Hermes-Role": "hermes-builder",
            "Mcp-Session-Id": "session-123",
        }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @staticmethod
    def call(name: str, arguments: dict[str, object], request_id: int = 1) -> bytes:
        return json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
            separators=(",", ":"),
        ).encode()

    def test_low_risk_write_gets_minimal_provider_permission(self) -> None:
        permit = self.proxy.permit(
            headers=self.headers,
            body=self.call(
                "push_files",
                {
                    "owner": "HermeTeam",
                    "repo": "demo",
                    "branch": "agent/REQ-1-fix",
                    "files": [{"path": "src/app.py", "content": "print('ok')"}],
                },
            ),
        )
        self.assertEqual(permit.authority_source, "AUTO")
        self.assertEqual(permit.context.capability, "repository.files.modify")
        self.assertEqual(self.broker.calls[-1], ("HermeTeam/demo", {"contents": "write"}))

    def test_protected_path_is_denied_before_provider_token(self) -> None:
        with self.assertRaises(MCPAuthorityBlocked) as raised:
            self.proxy.permit(
                headers=self.headers,
                body=self.call(
                    "push_files",
                    {
                        "owner": "HermeTeam",
                        "repo": "demo",
                        "branch": "agent/REQ-1-fix",
                        "files": [
                            {
                                "path": ".github/workflows/deploy.yml",
                                "content": "name: deploy",
                            }
                        ],
                    },
                ),
            )
        self.assertEqual(raised.exception.code, "authority_denied")
        self.assertEqual(self.broker.calls, [])

    def test_high_risk_call_requires_exact_human_grant(self) -> None:
        body = self.call(
            "actions_run_trigger",
            {
                "owner": "HermeTeam",
                "repo": "demo",
                "workflow_id": "ci.yml",
                "ref": "agent/REQ-2-ci",
            },
        )
        with self.assertRaises(MCPAuthorityBlocked) as raised:
            self.proxy.permit(headers=self.headers, body=body)
        self.assertEqual(raised.exception.code, "approval_required")
        request_id = raised.exception.data["request_id"]
        tool_id = raised.exception.data["tool_id"]
        pending = self.store.snapshot().pending_approvals
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].repository, "HermeTeam/demo")
        self.assertEqual(pending[0].branch, "agent/REQ-2-ci")
        self.assertIsNotNone(pending[0].args_hash)
        self.assertEqual(self.broker.calls, [])

        self.store.grant_once(request_id, tool_id, execution_ttl_seconds=60)
        permit = self.proxy.permit(headers=self.headers, body=body)
        self.assertEqual(permit.authority_source, "HUMAN")
        self.assertEqual(self.broker.calls[-1], ("HermeTeam/demo", {"actions": "write"}))

        with self.assertRaises(MCPAuthorityBlocked) as consumed:
            self.proxy.permit(headers=self.headers, body=body)
        self.assertEqual(consumed.exception.code, "approval_required")

    def test_changed_arguments_cannot_reuse_human_grant(self) -> None:
        original = self.call(
            "actions_run_trigger",
            {
                "owner": "HermeTeam",
                "repo": "demo",
                "workflow_id": "ci.yml",
                "ref": "agent/REQ-3-ci",
            },
        )
        with self.assertRaises(MCPAuthorityBlocked) as raised:
            self.proxy.permit(headers=self.headers, body=original)
        self.store.grant_once(
            raised.exception.data["request_id"],
            raised.exception.data["tool_id"],
            execution_ttl_seconds=60,
        )

        mutated = self.call(
            "actions_run_trigger",
            {
                "owner": "HermeTeam",
                "repo": "demo",
                "workflow_id": "release.yml",
                "ref": "agent/REQ-3-ci",
            },
        )
        with self.assertRaises(MCPAuthorityBlocked) as changed:
            self.proxy.permit(headers=self.headers, body=mutated)
        self.assertEqual(changed.exception.code, "approval_required")
        self.assertNotEqual(
            raised.exception.data["request_id"],
            changed.exception.data["request_id"],
        )
        self.assertEqual(self.broker.calls, [])

    def test_emergency_stop_denies_before_provider_token(self) -> None:
        self.store.set_emergency_stop(True)
        with self.assertRaises(MCPAuthorityBlocked) as raised:
            self.proxy.permit(
                headers=self.headers,
                body=self.call(
                    "get_file_contents",
                    {"owner": "HermeTeam", "repo": "demo", "path": "README.md"},
                ),
            )
        self.assertEqual(raised.exception.code, "emergency_stop")
        self.assertEqual(self.broker.calls, [])

    def test_wrong_agent_key_is_denied(self) -> None:
        headers = dict(self.headers)
        headers["Authorization"] = "Bearer wrong-key"
        with self.assertRaises(MCPAuthorityBlocked) as raised:
            self.proxy.permit(
                headers=headers,
                body=self.call(
                    "get_file_contents",
                    {"owner": "HermeTeam", "repo": "demo", "path": "README.md"},
                ),
            )
        self.assertEqual(raised.exception.code, "unauthorized_agent")
        self.assertEqual(self.broker.calls, [])


if __name__ == "__main__":
    unittest.main()
