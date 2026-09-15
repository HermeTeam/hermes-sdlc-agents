from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from capability_gateway.github_app import GitHubAppTokenBroker


class FakeResponse:
    def __init__(self, body: dict[str, object]) -> None:
        self.body = json.dumps(body).encode()

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


class GitHubAppTokenBrokerTests(unittest.TestCase):
    def test_token_is_narrowed_to_repository_and_permissions_and_cached(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / "app.pem"
            key.write_text("test-key", encoding="utf-8")
            broker = GitHubAppTokenBroker(
                app_id="123",
                installation_id="456",
                private_key_path=key,
                api_base_url="https://api.github.test",
                cache_seconds=300,
                jwt_factory=lambda: "app-jwt",
            )
            seen: list[dict[str, object]] = []

            def fake_urlopen(request, timeout):
                self.assertEqual(
                    request.full_url,
                    "https://api.github.test/app/installations/456/access_tokens",
                )
                self.assertEqual(request.headers["Authorization"], "Bearer app-jwt")
                seen.append(json.loads(request.data))
                return FakeResponse(
                    {
                        "token": "ghs_scoped",
                        "expires_at": "2099-01-01T00:00:00Z",
                        "permissions": {"contents": "write"},
                    }
                )

            with patch("capability_gateway.github_app.urlopen", side_effect=fake_urlopen):
                first = broker.mint(
                    repository="HermeTeam/demo",
                    permissions={"contents": "write"},
                )
                second = broker.mint(
                    repository="HermeTeam/demo",
                    permissions={"contents": "write"},
                )

            self.assertEqual(first.token, "ghs_scoped")
            self.assertEqual(second.token, "ghs_scoped")
            self.assertEqual(
                seen,
                [{"repositories": ["demo"], "permissions": {"contents": "write"}}],
            )
            self.assertNotEqual(first.fingerprint, first.token)

    def test_different_permission_set_gets_distinct_provider_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / "app.pem"
            key.write_text("test-key", encoding="utf-8")
            broker = GitHubAppTokenBroker(
                app_id="123",
                installation_id="456",
                private_key_path=key,
                api_base_url="https://api.github.test",
                cache_seconds=300,
                jwt_factory=lambda: "app-jwt",
            )
            calls = 0

            def fake_urlopen(request, timeout):
                nonlocal calls
                calls += 1
                permissions = json.loads(request.data)["permissions"]
                return FakeResponse(
                    {
                        "token": f"ghs_{calls}",
                        "expires_at": "2099-01-01T00:00:00Z",
                        "permissions": permissions,
                    }
                )

            with patch("capability_gateway.github_app.urlopen", side_effect=fake_urlopen):
                read = broker.mint(
                    repository="HermeTeam/demo",
                    permissions={"contents": "read"},
                )
                write = broker.mint(
                    repository="HermeTeam/demo",
                    permissions={"contents": "write"},
                )

            self.assertEqual(read.token, "ghs_1")
            self.assertEqual(write.token, "ghs_2")
            self.assertEqual(calls, 2)


if __name__ == "__main__":
    unittest.main()
