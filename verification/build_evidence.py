#!/usr/bin/env python3
"""Build fail-closed, sanitized E2E evidence from independently generated reports."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_ROLES = (
    "planner",
    "project-manager",
    "builder",
    "reviewer",
    "release",
    "incident",
    "learning",
)
REQUIRED_CANARIES = (
    "safe_qwen_builder",
    "protected_path",
    "emergency_stop",
    "one_shot_and_args",
)
REQUIRED_GATES = (
    "01-deterministic",
    "02-dashboard-e2e",
    "03-live-authority",
    "04-p0-contracts",
    "05-qwen-adversary",
    "06-qwen-probe",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def required_json(path: Path) -> dict:
    if not path.is_file():
        raise RuntimeError(f"Missing required E2E evidence: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"Invalid E2E evidence object: {path.name}")
    return value


def require_pass(value: dict, label: str) -> None:
    if value.get("status") != "PASS":
        raise RuntimeError(f"{label}: expected PASS, got {value.get('status')!r}")


def build() -> dict:
    reports = ROOT / "verification" / "reports"
    stage00 = required_json(reports / "stage-00-bootstrap.json")
    require_pass(stage00, "Stage 00")
    if stage00.get("provider") != "qwen-api-platform":
        raise RuntimeError("Stage 00 did not verify the Qwen API Platform provider")
    if not stage00.get("repository"):
        raise RuntimeError("Stage 00 has no sandbox repository evidence")

    readiness = required_json(reports / "hermes-qwen-readiness.json")
    for role in REQUIRED_ROLES:
        if readiness.get(role) != "PASS":
            raise RuntimeError(f"Hermes role {role}: readiness evidence is not PASS")

    live_authority = required_json(reports / "live-authority-canaries.json")
    require_pass(live_authority, "live authority suite")
    for scenario in REQUIRED_CANARIES:
        item = live_authority.get(scenario)
        if not isinstance(item, dict):
            raise RuntimeError(f"Missing live provider-state canary: {scenario}")
        require_pass(item, f"live canary {scenario}")

    if live_authority["safe_qwen_builder"].get("default_branch_unchanged") is not True:
        raise RuntimeError("Builder canary lacks unchanged-default-branch evidence")
    if live_authority["protected_path"].get("provider_branch_absent") is not True:
        raise RuntimeError("Protected-path canary lacks provider branch absence evidence")

    gates: dict[str, str] = {}
    for name in REQUIRED_GATES:
        marker = reports / (name + ".passed")
        if not marker.is_file() or marker.read_text(encoding="utf-8").strip() != "PASS":
            raise RuntimeError(f"Missing or failed independent E2E gate: {name}")
        gates[name] = "PASS"

    return {
        "schema_version": 1,
        "repository_sha": os.getenv("GITHUB_SHA", "local"),
        "model_matrix_sha256": sha256(ROOT / "verification/config/models.qwen.yaml"),
        "p0_scenarios_sha256": sha256(ROOT / "verification/scenarios/p0/core.yaml"),
        "stage00": stage00,
        "hermes_role_readiness": readiness,
        "live_authority_canaries": live_authority,
        "gates": gates,
        "hard_failures": [],
        "evidence_policy": {
            "raw_container_logs_uploaded": False,
            "deterministic_oracle_authoritative": True,
            "llm_judge_can_override_hard_failure": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = build()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote verified, sanitized E2E evidence: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
