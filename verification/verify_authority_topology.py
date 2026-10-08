#!/usr/bin/env python3
"""Check effective Compose service identities without printing secrets.

Stage 00 must prove that all seven AI containers and their role-local
orchestrators are wired only to the internal Gateway, not to GitHub provider
credentials, BEFORE starting any provider-state canary.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
ROLES = {
    "planner": "PLANNER",
    "project-manager": "PROJECT_MANAGER",
    "builder": "BUILDER",
    "reviewer": "REVIEWER",
    "release": "RELEASE",
    "incident": "INCIDENT",
    "learning": "LEARNING",
}
COMPOSE_FILES = (
    "compose.yaml",
    "compose.debug.yaml",
    "compose.capability-gateway.yaml",
    "compose.dynamic-authority.yaml",
)


def read_env() -> dict[str, str]:
    values = {}
    for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if raw and not raw.lstrip().startswith("#") and "=" in raw:
            key, value = raw.split("=", 1)
            values[key] = value
    return values


def check_topology(services: Mapping[str, Any], configured: Mapping[str, str]) -> dict:
    gateway = services.get("capability-gateway")
    if not isinstance(gateway, dict):
        raise RuntimeError("Capability Gateway missing from effective Compose")
    gateway_env = gateway.get("environment") or {}
    if not gateway_env.get("GITHUB_APP_ID") or gateway_env.get("CAPABILITY_EXECUTION_MODE") != "dynamic":
        raise RuntimeError("Gateway is not configured for dynamic GitHub App authority")

    role_keys: list[str] = []
    orchestrator_keys: list[str] = []
    for role, prefix in ROLES.items():
        service = services.get("hermes-" + role)
        if not isinstance(service, dict):
            raise RuntimeError(f"Missing role service: {role}")
        env = service.get("environment") or {}
        mcp_key = (
            configured["BUILDER_CAPABILITY_GATEWAY_KEY"] if role == "builder"
            else configured["CAPABILITY_" + prefix + "_GATEWAY_KEY"]
        )
        orch_key = configured["ORCHESTRATOR_" + prefix + "_GATEWAY_KEY"]
        if env.get("GIT_PROVIDER_MCP_URL") != "http://capability-gateway:8787/mcp":
            raise RuntimeError(f"{role}: bypasses Gateway MCP")
        if env.get("GIT_PROVIDER_MCP_TOKEN") != mcp_key:
            raise RuntimeError(f"{role}: MCP credential does not match internal identity")
        if env.get("HERMES_DEFAULT_ORCHESTRATOR_GITHUB_AUTH_MODE") != "gateway":
            raise RuntimeError(f"{role}: orchestrator is not in mandatory Gateway mode")
        if env.get("HERMES_DEFAULT_ORCHESTRATOR_GITHUB_GATEWAY_URL") != "http://capability-gateway:8787":
            raise RuntimeError(f"{role}: orchestrator uses wrong Gateway endpoint")
        if env.get("HERMES_DEFAULT_ORCHESTRATOR_GITHUB_GATEWAY_KEY") != orch_key:
            raise RuntimeError(f"{role}: orchestrator is missing its internal identity")
        if env.get("HERMES_DEFAULT_ORCHESTRATOR_GITHUB_TOKEN") or env.get("ORCHESTRATOR_GITHUB_TOKEN"):
            raise RuntimeError(f"{role}: an orchestrator provider token remains exposed")
        for forbidden in ("GITHUB_APP_PRIVATE_KEY", "GITHUB_APP_ID", "GITHUB_APP_INSTALLATION_ID"):
            if env.get(forbidden):
                raise RuntimeError(f"{role}: GitHub App material leaked into role environment")
        if gateway_env.get("ORCHESTRATOR_" + prefix + "_GATEWAY_KEY") != orch_key:
            raise RuntimeError(f"{role}: gateway orchestrator identity mismatch")
        if role != "builder" and gateway_env.get("CAPABILITY_" + prefix + "_GATEWAY_KEY") != mcp_key:
            raise RuntimeError(f"{role}: gateway agent identity mismatch")
        role_keys.append(mcp_key)
        orchestrator_keys.append(orch_key)

    all_keys = role_keys + orchestrator_keys
    if len(set(all_keys)) != len(all_keys) or any(len(key) < 24 for key in all_keys):
        raise RuntimeError("Gateway service identities must be distinct and strong")
    return {
        "status": "PASS",
        "roles_verified": list(ROLES),
        "role_local_orchestrators_verified": list(ROLES),
        "provider_tokens_exposed_to_roles": False,
        "gateway_only": True,
    }


def main() -> int:
    command = ["docker", "compose"]
    for file in COMPOSE_FILES:
        command.extend(("-f", file))
    command.extend(("config", "--format", "json"))
    result = subprocess.run(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, text=True)
    rendered = json.loads(result.stdout)
    report = check_topology(rendered["services"], read_env())
    folder = ROOT / "verification" / "reports"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "authority-topology.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("Effective Compose topology PASS: 7 AI roles and 7 orchestrators have no GitHub provider tokens")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
