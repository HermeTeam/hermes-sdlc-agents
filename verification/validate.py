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


def parse_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def validate_env_defaults() -> None:
    model_data = yaml.safe_load(MODEL_CONFIG.read_text(encoding="utf-8"))
    runtime = model_data["runtime_roles"]
    root_env = parse_dotenv(ROOT / ".env.example")

    if "QWEN_API_BASE_URL" not in root_env or "DASHSCOPE_API_KEY" not in root_env:
        fail(".env.example must expose QWEN_API_BASE_URL and DASHSCOPE_API_KEY")
    if root_env.get("HERMES_MODEL_ID") != "qwen3.7-plus":
        fail(".env.example shared HERMES_MODEL_ID must be qwen3.7-plus")

    prefixes = {
        "planner": "PLANNER",
        "project-manager": "PROJECT_MANAGER",
        "builder": "BUILDER",
        "reviewer": "REVIEWER",
        "release": "RELEASE",
        "incident": "INCIDENT",
        "learning": "LEARNING",
    }
    for role, prefix in prefixes.items():
        expected = runtime[role]
        actual = root_env.get(f"{prefix}_HERMES_MODEL_ID")
        if actual != expected:
            fail(f".env.example {prefix}_HERMES_MODEL_ID={actual!r}, expected {expected!r}")

        role_env = parse_dotenv(ROOT / "secrets" / f"hermes-{role}.env.example")
        if role_env.get("HERMES_MODEL_ID") != expected:
            fail(
                f"secrets/hermes-{role}.env.example HERMES_MODEL_ID="
                f"{role_env.get('HERMES_MODEL_ID')!r}, expected {expected!r}"
            )

    if root_env.get("HERMES_JSON_REPAIR_MODEL_ID") != runtime["json-repair"]:
        fail("HERMES_JSON_REPAIR_MODEL_ID differs from Qwen model matrix")

    openhands = parse_dotenv(ROOT / "secrets" / "hermes-builder-openhands.env.example")
    expected_openhands = model_data["auxiliary"]["openhands_builder"]["model"]
    if openhands.get("BUILDER_OPENHANDS_LLM_MODEL") != expected_openhands:
        fail("OpenHands model differs from Qwen model matrix")
    if "dashscope" not in openhands.get("BUILDER_OPENHANDS_LLM_BASE_URL", ""):
        fail("OpenHands base URL is not a Qwen/DashScope compatible endpoint")


def main() -> int:
    validate_models()
    validate_scenarios()
    validate_env_defaults()
    print("Verification contracts PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
