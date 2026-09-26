from __future__ import annotations

import importlib.util
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("smb_quickstart", ROOT / "scripts" / "smb-quickstart.py")
assert spec and spec.loader
quickstart = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quickstart)


class SMBQuickstartTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "runtime/smb").mkdir(parents=True)
        (self.root / "secrets/smb").mkdir(parents=True)
        self.paths = {
            "ROOT": self.root,
            "SUBSCRIPTION": self.root / "runtime/smb/subscription.json",
            "INSTALLATION": self.root / "runtime/smb/installation.json",
            "APP_KEY": self.root / "secrets/smb/github-app.pem",
            "ENV_FILE": self.root / ".env.smb",
            "COMPOSE": self.root / "compose.smb.yaml",
        }
        self.patchers = [patch.object(quickstart, name, value) for name, value in self.paths.items()]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.write(
            self.paths["SUBSCRIPTION"],
            json.dumps({
                "schema_version": 1,
                "status": "active",
                "llm_base_url": "https://llm-gateway.example/compatible-mode/v1",
                "model_id": "subscription-model",
                "access_token": "tenant-access-token-not-vendor-secret-123",
            }),
        )
        self.write(
            self.paths["INSTALLATION"],
            json.dumps({
                "schema_version": 1,
                "repository": "acme/example-repository",
                "default_branch": "main",
                "app_id": 12345,
                "installation_id": 54321,
            }),
        )
        self.write(
            self.paths["APP_KEY"],
            "-----BEGIN RSA PRIVATE KEY-----\ntest fixture\n-----END RSA PRIVATE KEY-----\n",
        )

    def write(self, path: Path, value: str) -> None:
        path.write_text(value, encoding="utf-8")
        path.chmod(0o600)

    def test_init_uses_prebound_subscription_and_never_requests_provider_choice(self) -> None:
        quickstart.initialize()
        content = self.paths["ENV_FILE"].read_text(encoding="utf-8")
        self.assertIn("SMB_SUBSCRIPTION_MODEL_ID=subscription-model", content)
        self.assertIn("SMB_SUBSCRIPTION_LLM_BASE_URL=https://llm-gateway.example/compatible-mode/v1", content)
        self.assertIn("SMB_SUBSCRIPTION_JUDGE_BASE_URL=https://llm-gateway.example/compatible-mode", content)
        self.assertNotIn("QWEN_API_KEY", content)
        self.assertNotIn("DASHSCOPE_API_KEY", content)
        self.assertNotIn("BUILDER_GITHUB_MCP_TOKEN", content)
        self.assertEqual(stat.S_IMODE(self.paths["ENV_FILE"].stat().st_mode), 0o600)

    def test_init_preserves_generated_internal_keys(self) -> None:
        quickstart.initialize()
        first = dict(
            line.split("=", 1)
            for line in self.paths["ENV_FILE"].read_text(encoding="utf-8").splitlines()
        )
        quickstart.initialize()
        second = dict(
            line.split("=", 1)
            for line in self.paths["ENV_FILE"].read_text(encoding="utf-8").splitlines()
        )
        for key in quickstart.RUNTIME_KEYS:
            self.assertEqual(first[key], second[key])
            self.assertEqual(len(second[key]), 64)
        self.assertNotEqual(first["SMB_BUILDER_GATEWAY_KEY"], first["SMB_CAPABILITY_ADMIN_KEY"])

    def test_missing_subscription_refuses_to_generate_config(self) -> None:
        self.paths["SUBSCRIPTION"].unlink()
        with self.assertRaisesRegex(quickstart.SetupError, "Missing provisioned"):
            quickstart.initialize()
        self.assertFalse(self.paths["ENV_FILE"].exists())

    def test_non_private_subscription_is_rejected(self) -> None:
        self.paths["SUBSCRIPTION"].chmod(0o644)
        with self.assertRaisesRegex(quickstart.SetupError, "owner-only"):
            quickstart.initialize()

    def test_invalid_subscription_gateway_is_rejected(self) -> None:
        binding = json.loads(self.paths["SUBSCRIPTION"].read_text())
        binding["llm_base_url"] = "http://api.example/v1"
        self.write(self.paths["SUBSCRIPTION"], json.dumps(binding))
        with self.assertRaisesRegex(quickstart.SetupError, "HTTPS"):
            quickstart.initialize()

    def test_invalid_github_installation_does_not_create_config(self) -> None:
        binding = json.loads(self.paths["INSTALLATION"].read_text())
        binding["repository"] = "acme/repository/other"
        self.write(self.paths["INSTALLATION"], json.dumps(binding))
        with self.assertRaisesRegex(quickstart.SetupError, "owner/repository"):
            quickstart.initialize()
        self.assertFalse(self.paths["ENV_FILE"].exists())

    def test_untrusted_extra_subscription_provider_field_is_refused(self) -> None:
        binding = json.loads(self.paths["SUBSCRIPTION"].read_text())
        binding["provider"] = "customer-selected"
        self.write(self.paths["SUBSCRIPTION"], json.dumps(binding))
        with self.assertRaisesRegex(quickstart.SetupError, "managed HermeTeam contract"):
            quickstart.initialize()

    def test_standalone_compose_exposes_only_internal_mcp_credential(self) -> None:
        compose = (ROOT / "compose.smb.yaml").read_text(encoding="utf-8")
        self.assertIn("CAPABILITY_EXECUTION_MODE: dynamic", compose)
        self.assertIn("GIT_PROVIDER_MCP_URL: http://capability-gateway:8787/mcp", compose)
        self.assertIn('GIT_PROVIDER_MCP_TOKEN: "${SMB_BUILDER_GATEWAY_KEY:', compose)
        self.assertNotIn("BUILDER_GITHUB_MCP_TOKEN", compose)
        for role in ("hermes-planner:", "hermes-project-manager:", "hermes-reviewer:",
                     "hermes-release:", "hermes-incident:", "hermes-learning:"):
            self.assertNotIn(role, compose)
        self.assertIn('"127.0.0.1:${HERMETEAM_SMB_DASHBOARD_PORT:-9130}:8080"', compose)


    def test_skill_lock_is_pinned_and_builder_only_receives_scoped_skills(self) -> None:
        manifest = json.loads((ROOT / "smb/skills.lock.json").read_text(encoding="utf-8"))
        compose = (ROOT / "compose.smb.yaml").read_text(encoding="utf-8")
        self.assertEqual(manifest["schema_version"], 1)
        self.assertIn(manifest["commit"], compose)
        for skill in manifest["builder_skills"]:
            self.assertIn(skill, compose)
        self.assertIn("atomic-skills/devops-engineer", manifest["operator_skills"])
        self.assertNotIn("atomic-skills/devops-engineer", compose)
        self.assertNotIn("atomic-skills/architecture-designer", compose)
        self.assertIn("shared-skills:/opt/hermes-shared-skills:ro", compose)

    def test_smb_builder_profile_excludes_optional_mcp_and_openhands(self) -> None:
        profile = (ROOT / "profiles/hermes-builder-smb/config.yaml").read_text(encoding="utf-8")
        soul = (ROOT / "profiles/hermes-builder-smb/SOUL.md").read_text(encoding="utf-8")
        self.assertIn("mcp_servers:\\n  repository:", profile)
        for name in ("ddg-search:", "postgresql:", "chrome-devtools:", "openhands_delegate"):
            self.assertNotIn(name, profile)
        self.assertNotIn("openhands_delegate", soul)
        self.assertIn("подпиской HermeTeam", soul)


if __name__ == "__main__":
    unittest.main()
