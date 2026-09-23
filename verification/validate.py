#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MODEL_CONFIG = ROOT / "verification" / "config" / "models.qwen.yaml"
SCENARIO_DIR = ROOT / "verification" / "scenarios"


def fail(message: str) -> None:
    raise SystemExit(message)


def validate_models() -> None:
    data = yaml.safe_load(MODEL_CONFIG.read_text(encoding="utf-8"))
    if data["provider"]["name"] != "qwen-api-platform":
        fail("verification model provider must be qwen-api-platform")
    for section in ("runtime_roles", "verification_roles"):
        if not data.get(section):
            fail(f"{section} is empty")
        for role, model in data[section].items():
            if not str(model).startswith("qwen"):
                fail(f"{section}.{role} is not a Qwen model: {model}")
    policy = data.get("policy") or {}
    if policy.get("deterministic_oracle_precedes_llm_judge") is not True:
        fail("deterministic oracle must precede LLM judge")
    if policy.get("judge_may_not_override_hard_failure") is not True:
        fail("LLM judge must not override deterministic hard failures")


def validate_scenarios() -> None:
    seen: set[str] = set()
    count = 0
    for path in sorted(SCENARIO_DIR.rglob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for scenario in data.get("scenarios", []):
            count += 1
            sid = scenario.get("id")
            if not sid or sid in seen:
                fail(f"invalid or duplicate scenario id in {path}: {sid}")
            seen.add(sid)
            for key in ("priority", "class", "goal", "expected", "forbidden", "zero_tolerance"):
                if key not in scenario:
                    fail(f"{sid}: missing {key}")
            if scenario["priority"] == "P0" and scenario["zero_tolerance"] is not True:
                fail(f"{sid}: P0 scenario must be zero-tolerance")
    if count < 6:
        fail(f"expected at least 6 P0 scenarios, found {count}")


def validate_env_defaults() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    required = (
        "QWEN_API_BASE_URL=",
        "DASHSCOPE_API_KEY=",
        "HERMES_MODEL_ID=qwen3.7-plus",
        "PLANNER_HERMES_MODEL_ID=qwen3.7-max",
        "BUILDER_HERMES_MODEL_ID=qwen3.7-plus",
        "INCIDENT_HERMES_MODEL_ID=qwen3.5-flash",
    )
    for marker in required:
        if marker not in text:
            fail(f".env.example missing Qwen marker: {marker}")


def main() -> int:
    validate_models()
    validate_scenarios()
    validate_env_defaults()
    print("Verification contracts PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
