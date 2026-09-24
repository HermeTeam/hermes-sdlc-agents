from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "hermeteam_check_prerequisites", ROOT / "verification" / "check_prerequisites.py"
)
assert SPEC and SPEC.loader
check_prerequisites = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_prerequisites)


class PrerequisiteTests(unittest.TestCase):
    def good_env(self) -> dict[str, str]:
        env = {
            name: "unique-value-" + str(index)
            for index, name in enumerate(check_prerequisites.REQUIRED)
        }
        env.update(
            HERMETEAM_E2E_EPHEMERAL="1",
            GITHUB_REPOSITORY="HermeTeam/hermes-sdlc-agents",
            E2E_SANDBOX_REPOSITORY_FULL_NAME="HermeTeam/hermes-e2e-sandbox",
            QWEN_API_BASE_URL="https://maas.qwencloudapi.com/compatible-mode/v1",
        )
        return env

    def test_complete_distinct_ephemeral_credentials_pass(self) -> None:
        self.assertEqual(check_prerequisites.check(self.good_env()), [])

    def test_missing_multiple_secrets_are_reported_together(self) -> None:
        """Catches a slow one-secret-at-a-time failure loop."""
        env = self.good_env()
        del env["QWEN_API_KEY"]
        del env["E2E_HARNESS_GITHUB_TOKEN"]
        errors = check_prerequisites.check(env)
        self.assertIn("Missing QWEN_API_KEY", errors)
        self.assertIn("Missing E2E_HARNESS_GITHUB_TOKEN", errors)

    def test_source_repo_cannot_be_sandbox(self) -> None:
        """Catches an accidental live test against the source repository."""
        env = self.good_env()
        env["E2E_SANDBOX_REPOSITORY_FULL_NAME"] = env["GITHUB_REPOSITORY"]
        self.assertTrue(any("must differ" in x for x in check_prerequisites.check(env)))

    def test_qwen_token_plan_endpoint_is_accepted(self) -> None:
        env = self.good_env()
        env["QWEN_API_BASE_URL"] = (
            "https://token-plan.maas.qwencloudapi.com/compatible-mode/v1"
        )
        self.assertEqual(check_prerequisites.check(env), [])

    def test_invalid_qwen_endpoint_fails(self) -> None:
        env = self.good_env()
        env["QWEN_API_BASE_URL"] = "http://YOUR_API_ENDPOINT/compatible-mode/v1"
        self.assertTrue(any("QWEN_API_BASE_URL" in x for x in check_prerequisites.check(env)))

    def test_reusing_role_credentials_fails(self) -> None:
        env = self.good_env()
        env["E2E_REVIEWER_GITHUB_MCP_TOKEN"] = env["E2E_PLANNER_GITHUB_MCP_TOKEN"]
        self.assertTrue(any("Separate role credentials" in x for x in check_prerequisites.check(env)))


if __name__ == "__main__":
    unittest.main()
