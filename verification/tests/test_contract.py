from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


class VerificationContractTests(unittest.TestCase):
    def test_all_configured_models_are_qwen(self) -> None:
        data = yaml.safe_load(
            (ROOT / "verification/config/models.qwen.yaml").read_text(encoding="utf-8")
        )
        models = list(data["runtime_roles"].values()) + list(data["verification_roles"].values())
        self.assertTrue(models)
        self.assertTrue(all(model.startswith("qwen") for model in models))

    def test_openhands_uses_qwen_via_litellm_openai_transport(self) -> None:
        data = yaml.safe_load(
            (ROOT / "verification/config/models.qwen.yaml").read_text(encoding="utf-8")
        )
        cfg = data["auxiliary"]["openhands_builder"]
        self.assertEqual(cfg["model"], "openai/qwen3.7-plus")
        self.assertEqual(cfg["api_model"], "qwen3.7-plus")

    def test_p0_scenarios_are_zero_tolerance(self) -> None:
        data = yaml.safe_load(
            (ROOT / "verification/scenarios/p0/core.yaml").read_text(encoding="utf-8")
        )
        self.assertGreaterEqual(len(data["scenarios"]), 6)
        for scenario in data["scenarios"]:
            self.assertEqual(scenario["priority"], "P0")
            self.assertTrue(scenario["zero_tolerance"])

    def test_bootstrap_requires_ephemeral_guard(self) -> None:
        text = (ROOT / "scripts/e2e/bootstrap-from-scratch.sh").read_text(encoding="utf-8")
        self.assertIn("HERMETEAM_E2E_EPHEMERAL", text)
        self.assertIn("down --volumes --remove-orphans", text)

    def test_harness_cleanup_token_is_not_persisted_by_bootstrap(self) -> None:
        text = (ROOT / "scripts/e2e/bootstrap-from-scratch.sh").read_text(encoding="utf-8")
        self.assertNotIn("E2E_HARNESS_GITHUB_TOKEN", text)

    def test_workflow_never_uploads_raw_container_logs(self) -> None:
        workflow = (ROOT / ".github/workflows/ai-e2e-qwen.yml").read_text(encoding="utf-8")
        self.assertNotIn("compose-logs.txt", workflow)
        self.assertNotIn(" logs --no-color", workflow)

    def test_dynamic_builder_does_not_require_a_provider_pat(self) -> None:
        bootstrap = (ROOT / "scripts/e2e/bootstrap-from-scratch.sh").read_text(encoding="utf-8")
        workflow = (ROOT / ".github/workflows/ai-e2e-qwen.yml").read_text(encoding="utf-8")
        self.assertNotIn("require \"E2E_BUILDER_GITHUB_MCP_TOKEN\"", bootstrap)
        self.assertNotIn("secrets.E2E_BUILDER_GITHUB_MCP_TOKEN", workflow)
        self.assertIn("DYNAMIC_AUTHORITY_NO_PROVIDER_TOKEN", bootstrap)

    def test_live_canary_targets_dynamic_authority_overlay(self) -> None:
        text = (ROOT / "verification/live_authority_canaries.py").read_text(encoding="utf-8")
        self.assertIn("compose.dynamic-authority.yaml", text)
        self.assertIn("authority_denied", text)
        self.assertIn("emergency_stop", text)
        self.assertIn("approval_required", text)

    def test_judge_cannot_override_deterministic_failure(self) -> None:
        data = yaml.safe_load(
            (ROOT / "verification/config/models.qwen.yaml").read_text(encoding="utf-8")
        )
        self.assertTrue(data["policy"]["deterministic_oracle_precedes_llm_judge"])
        self.assertTrue(data["policy"]["judge_may_not_override_hard_failure"])


if __name__ == "__main__":
    unittest.main()
