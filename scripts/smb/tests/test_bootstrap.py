from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("smb_bootstrap", ROOT / "scripts/smb/bootstrap.py")
assert SPEC and SPEC.loader
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


class SmbBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        secrets = root / "secrets"
        secrets.mkdir()
        self.target = root / ".env.smb"
        self.subscription = secrets / "smb-subscription.env"
        self.token = secrets / "smb-subscription.token"
        self.github = secrets / "smb-github-app.pem"
        for path, contents in (
            (self.subscription, "SMB_SUBSCRIPTION_BASE_URL=https://subscription.example.org/v1\nSMB_SUBSCRIPTION_MODEL=fixed-plan-model\n"),
            (self.token, "operator-supplied-secret-123456789"),
            (self.github, "-----BEGIN PRIVATE KEY-----\nfake-in-tests\n-----END PRIVATE KEY-----\n"),
        ):
            path.write_text(contents, encoding="utf-8")
            path.chmod(0o600)
        for name, path in (
            ("TARGET", self.target),
            ("SUBSCRIPTION", self.subscription),
            ("TOKEN", self.token),
            ("GITHUB_KEY", self.github),
        ):
            patcher = patch.object(bootstrap, name, path)
            patcher.start()
            self.addCleanup(patcher.stop)

    def source(self) -> dict[str, str]:
        return {
            "SMB_GITHUB_REPOSITORY_FULL_NAME": "test-org/app",
            "SMB_GITHUB_DEFAULT_BRANCH": "main",
            "SMB_GITHUB_APP_ID": "12345",
            "SMB_GITHUB_APP_INSTALLATION_ID": "56789",
            "SMB_HERMES_BASE_IMAGE": "registry.example/hermes@sha256:" + "a" * 64,
        }

    def test_creates_one_small_config_without_upstream_credentials_or_provider_picker(self) -> None:
        self.assertTrue(bootstrap.create(self.source()))
        content = self.target.read_text(encoding="utf-8")
        self.assertIn("SMB_GITHUB_REPOSITORY_FULL_NAME=test-org/app", content)
        self.assertNotIn("SMB_SUBSCRIPTION_BASE_URL=", content)
        self.assertNotIn("SMB_SUBSCRIPTION_MODEL=", content)
        self.assertNotIn("SMB_SUBSCRIPTION_TOKEN=", content)
        self.assertNotIn("OPENAI_API_KEY=", content)
        self.assertEqual(self.target.stat().st_mode & 0o077, 0)

    def test_idempotent_repeated_bootstrap_preserves_keys(self) -> None:
        bootstrap.create(self.source())
        before = self.target.read_bytes()
        self.assertFalse(bootstrap.create(self.source()))
        self.assertEqual(self.target.read_bytes(), before)

    def test_refuses_mutable_builder_image(self) -> None:
        source = self.source()
        source["SMB_HERMES_BASE_IMAGE"] = "nousresearch/hermes-agent:latest"
        with self.assertRaisesRegex(ValueError, "immutable sha256"):
            bootstrap.settings(source)

    def test_refuses_source_repository_as_default_sandbox(self) -> None:
        source = self.source()
        source["SMB_GITHUB_REPOSITORY_FULL_NAME"] = "HermeTeam/hermes-sdlc-agents"
        with self.assertRaisesRegex(ValueError, "separate test repository"):
            bootstrap.settings(source)

    def test_refuses_world_readable_subscription_secret(self) -> None:
        self.token.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "owner-only"):
            bootstrap.check_subscription()

    def test_refuses_unfilled_subscription_bundle_template(self) -> None:
        self.subscription.write_text(
            "SMB_SUBSCRIPTION_BASE_URL=https://SUBSCRIPTION_ENDPOINT_FROM_HERMETEAM/v1\\n"
            "SMB_SUBSCRIPTION_MODEL=SUBSCRIPTION_ASSIGNED_MODEL\\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "valid HTTPS subscription"):
            bootstrap.check_subscription()

    def test_refuses_missing_subscription_provisioning(self) -> None:
        self.subscription.unlink()
        with self.assertRaisesRegex(ValueError, "missing or unsafe"):
            bootstrap.check_subscription()


if __name__ == "__main__":
    unittest.main()
