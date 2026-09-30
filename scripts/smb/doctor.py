#!/usr/bin/env python3
"""Secret-safe preflight for the standalone SMB runtime."""
from __future__ import annotations

import sys
from pathlib import Path

from bootstrap import ROOT, TARGET, check_subscription, parse_env, private_file, settings

REQUIRED_KEYS = (
    "SMB_MODEL_RELAY_KEY",
    "SMB_BUILDER_GATEWAY_KEY",
    "SMB_CAPABILITY_ADMIN_KEY",
    "SMB_DASHBOARD_GOVERNANCE_KEY",
    "SMB_BUILDER_API_KEY",
)


def check() -> None:
    check_subscription()
    private_file(TARGET, "SMB runtime configuration")
    values = parse_env(TARGET)
    settings(values)
    missing = [key for key in REQUIRED_KEYS if len(values.get(key, "")) < 32]
    if missing:
        raise ValueError("missing or weak generated SMB keys: " + ", ".join(missing))
    if len({values[key] for key in REQUIRED_KEYS}) != len(REQUIRED_KEYS):
        raise ValueError("SMB role and authority keys must be independent")
    if "SMB_SUBSCRIPTION_TOKEN" in values or "OPENAI_API_KEY" in values:
        raise ValueError("external model credentials must never enter .env.smb")
    if values.get("ORCHESTRATOR_ENABLED", "false").lower() != "false":
        raise ValueError("unattended orchestration is disabled in SMB Phase 1")
    print("SMB preflight PASS: subscription provisioned; target, image and authority keys valid")


def main() -> int:
    try:
        check()
    except (ValueError, OSError) as exc:
        print(f"SMB preflight FAIL: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
