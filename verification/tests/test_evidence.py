from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "hermeteam_build_evidence", ROOT / "verification" / "build_evidence.py"
)
assert SPEC and SPEC.loader
evidence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evidence)


class EvidenceGateTests(unittest.TestCase):
    """These tests catch fabricated green E2E evidence from missing/failed real stages."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.reports = self.root / "verification" / "reports"
        self.reports.mkdir(parents=True)
        config = self.root / "verification" / "config"
        config.mkdir()
        (config / "models.qwen.yaml").write_text("provider: qwen\n", encoding="utf-8")
        scenarios = self.root / "verification" / "scenarios" / "p0"
        scenarios.mkdir(parents=True)
        (scenarios / "core.yaml").write_text("scenarios: []\n", encoding="utf-8")

        self.write_json(
            "stage-00-bootstrap.json",
            {"status": "PASS", "provider": "qwen-api-platform", "repository": "test-org/disposable"},
        )
        self.write_json(
            "hermes-qwen-readiness.json",
            {role: "PASS" for role in evidence.REQUIRED_ROLES},
        )
        self.write_json(
            "live-authority-canaries.json",
            {
                "status": "PASS",
                "safe_qwen_builder": {"status": "PASS", "default_branch_unchanged": True},
                "protected_path": {"status": "PASS", "provider_branch_absent": True},
                "emergency_stop": {"status": "PASS"},
                "one_shot_and_args": {"status": "PASS"},
            },
        )
        for gate in evidence.REQUIRED_GATES:
            (self.reports / (gate + ".passed")).write_text("PASS\n", encoding="utf-8")

    def write_json(self, filename: str, value: dict) -> None:
        (self.reports / filename).write_text(json.dumps(value), encoding="utf-8")

    def build(self) -> dict:
        with patch.object(evidence, "ROOT", self.root):
            return evidence.build()

    def test_complete_independent_evidence_can_pass(self) -> None:
        result = self.build()
        self.assertEqual(result["stage00"]["status"], "PASS")
        self.assertTrue(all(v == "PASS" for v in result["gates"].values()))

    def test_missing_stage_zero_cannot_be_reported_as_pass(self) -> None:
        (self.reports / "stage-00-bootstrap.json").unlink()
        with self.assertRaisesRegex(RuntimeError, "Missing required E2E evidence"):
            self.build()

    def test_missing_role_readiness_cannot_be_reported_as_pass(self) -> None:
        self.write_json("hermes-qwen-readiness.json", {"builder": "PASS"})
        with self.assertRaisesRegex(RuntimeError, "Hermes role planner"):
            self.build()

    def test_protected_path_provider_state_failure_blocks_evidence(self) -> None:
        report = json.loads((self.reports / "live-authority-canaries.json").read_text())
        report["protected_path"]["provider_branch_absent"] = False
        self.write_json("live-authority-canaries.json", report)
        with self.assertRaisesRegex(RuntimeError, "provider branch absence"):
            self.build()

    def test_missing_dashboard_gate_cannot_be_reported_as_pass(self) -> None:
        (self.reports / "02-dashboard-e2e.passed").unlink()
        with self.assertRaisesRegex(RuntimeError, "02-dashboard-e2e"):
            self.build()


if __name__ == "__main__":
    unittest.main()
