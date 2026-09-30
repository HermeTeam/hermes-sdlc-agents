from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


class SmbRuntimeContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.stack = yaml.safe_load((ROOT / "compose.smb.yaml").read_text(encoding="utf-8"))
        cls.services = cls.stack["services"]

    def test_small_independent_stack(self) -> None:
        self.assertEqual(set(self.services), {
            "subscription-relay", "capability-gateway", "hermes-builder",
            "hermeteam-dashboard", "docker-socket-proxy", "skills-superset-sync",
        })
        self.assertEqual(self.stack["name"], "hermeteam-smb")

    def test_builder_cannot_receive_github_app_key_or_provider_token(self) -> None:
        builder = self.services["hermes-builder"]
        self.assertEqual(builder["environment"]["GIT_PROVIDER_MCP_URL"], "http://capability-gateway:8787/mcp")
        self.assertFalse(builder.get("secrets"))
        self.assertNotIn("GITHUB_APP_PRIVATE_KEY_PATH", builder["environment"])
        self.assertNotIn("GIT_PROVIDER_MCP_TOKEN", builder.get("env_file", {}))
        self.assertNotIn("ORCHESTRATOR_GITHUB_TOKEN", builder["environment"])
        self.assertEqual(builder["environment"]["ORCHESTRATOR_ENABLED"], "false")

    def test_gateway_is_dynamic_and_github_key_is_gateway_only(self) -> None:
        gateway = self.services["capability-gateway"]
        self.assertEqual(gateway["environment"]["CAPABILITY_EXECUTION_MODE"], "dynamic")
        self.assertEqual(gateway["secrets"], ["smb_github_app_private_key"])
        self.assertFalse(gateway.get("ports"))
        self.assertEqual(self.services["subscription-relay"]["secrets"], ["smb_subscription_token"])
        self.assertNotIn("SMB_SUBSCRIPTION_TOKEN", str(self.services["hermes-builder"]))

    def test_no_provider_selection_or_upstream_token_in_agent_configuration(self) -> None:
        builder = self.services["hermes-builder"]["environment"]
        self.assertEqual(builder["HERMES_DEFAULT_HERMES_MODEL_ID"], "hermeteam-subscribed")
        self.assertEqual(builder["HERMES_DEFAULT_HERMES_MODEL_BASE_URL"], "http://subscription-relay:8085/v1")
        self.assertNotIn("SMB_SUBSCRIPTION_BASE_URL", builder)
        self.assertNotIn("SMB_SUBSCRIPTION_MODEL", builder)
        self.assertNotIn("SMB_SUBSCRIPTION_TOKEN", builder)
        self.assertEqual(self.services["capability-gateway"]["environment"]["CAPABILITY_JUDGE_MODEL"], "hermeteam-subscribed")

    def test_dashboard_is_loopback_only_and_has_single_runtime_role(self) -> None:
        dashboard = self.services["hermeteam-dashboard"]
        self.assertTrue(all(str(p).startswith("127.0.0.1:") for p in dashboard["ports"]))
        self.assertEqual(dashboard["environment"]["HERMETEAM_RUNTIME_MODE"], "smb")

    def test_smb_profile_has_no_extra_agent_or_mcp_toolsets(self) -> None:
        config = yaml.safe_load(
            (ROOT / "profiles/smb-builder/config.yaml").read_text(encoding="utf-8")
        )
        self.assertEqual(config["plugins"]["enabled"], ["hermeteam-intent-action-gate"])
        self.assertEqual(config["toolsets"], [
            "file", "skills", "todo", "clarify", "mcp-repository"
        ])
        self.assertEqual(list(config["mcp_servers"]), ["repository"])
        self.assertFalse(config["lsp"]["enabled"])
        self.assertEqual(
            self.services["hermes-builder"]["build"]["dockerfile"], "Dockerfile.smb-builder"
        )
        self.assertIn(
            "./profiles/smb-builder:/etc/hermes:ro",
            self.services["hermes-builder"]["volumes"],
        )

    def test_only_selected_skills_are_mounted_read_only(self) -> None:
        builder = self.services["hermes-builder"]
        self.assertIn("smb-shared-skills:/opt/hermes-shared-skills:ro", builder["volumes"])
        self.assertIn("skills-superset-sync", builder["depends_on"])


if __name__ == "__main__":
    unittest.main()
