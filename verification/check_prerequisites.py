#!/usr/bin/env python3
"""Fail early on missing E2E credentials without logging their values."""
from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping
from urllib.parse import urlsplit

ROLE_TOKENS = (
    "E2E_PLANNER_GITHUB_MCP_TOKEN",
    "E2E_PROJECT_MANAGER_GITHUB_MCP_TOKEN",
    "E2E_REVIEWER_GITHUB_MCP_TOKEN",
    "E2E_RELEASE_GITHUB_MCP_TOKEN",
    "E2E_INCIDENT_GITHUB_MCP_TOKEN",
    "E2E_LEARNING_GITHUB_MCP_TOKEN",
)
ORCHESTRATOR_TOKENS = tuple(
    f"E2E_ORCHESTRATOR_{role}_GITHUB_TOKEN"
    for role in (
        "PLANNER",
        "PROJECT_MANAGER",
        "BUILDER",
        "REVIEWER",
        "RELEASE",
        "INCIDENT",
        "LEARNING",
    )
)
REQUIRED = (
    "QWEN_API_KEY",
    "QWEN_API_BASE_URL",
    "E2E_SANDBOX_REPOSITORY_FULL_NAME",
    "E2E_GITHUB_APP_ID",
    "E2E_GITHUB_APP_INSTALLATION_ID",
    "E2E_GITHUB_APP_PRIVATE_KEY",
    "E2E_HARNESS_GITHUB_TOKEN",
) + ROLE_TOKENS + ORCHESTRATOR_TOKENS


def check(env: Mapping[str, str]) -> list[str]:
    errors = [f"Missing {name}" for name in REQUIRED if not str(env.get(name) or "").strip()]
    if env.get("HERMETEAM_E2E_EPHEMERAL") != "1":
        errors.append("HERMETEAM_E2E_EPHEMERAL must be 1 on a disposable runner")

    repo = (env.get("E2E_SANDBOX_REPOSITORY_FULL_NAME") or "").strip()
    if repo:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            errors.append("E2E_SANDBOX_REPOSITORY_FULL_NAME must be owner/repo")
        if repo.casefold() == (env.get("GITHUB_REPOSITORY") or "").strip().casefold():
            errors.append("Sandbox repository must differ from the source repository")

    base_url = (env.get("QWEN_API_BASE_URL") or "").strip()
    if base_url:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not parsed.path.rstrip("/").endswith("/v1")
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or "YOUR_" in base_url
            or "CHANGE_ME" in base_url
        ):
            errors.append("QWEN_API_BASE_URL must be the actual HTTPS OpenAI-compatible /v1 URL from the Qwen API portal")

    present = [(name, env[name]) for name in ROLE_TOKENS + ORCHESTRATOR_TOKENS if env.get(name)]
    for index, (name, token) in enumerate(present):
        for other_name, other_token in present[:index]:
            if token == other_token:
                errors.append(f"Separate role credentials required: {other_name} and {name} must differ")

    return errors


def main() -> int:
    problems = check(os.environ)
    if problems:
        print("Full E2E prerequisites FAIL (variable names only):", file=sys.stderr)
        for problem in problems:
            print("- " + problem, file=sys.stderr)
        return 2
    print("Full E2E prerequisites PASS: sandbox variables and credential slots are set")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
