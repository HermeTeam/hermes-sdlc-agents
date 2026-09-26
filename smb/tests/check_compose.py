#!/usr/bin/env python3
"""CI-only Compose rendering probe; no real subscription or GitHub credentials."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
subscription = ROOT / "runtime/smb/subscription.json"
installation = ROOT / "runtime/smb/installation.json"
key = ROOT / "secrets/smb/github-app.pem"
env_file = ROOT / ".env.smb"

def main() -> int:
    subscription.parent.mkdir(parents=True, exist_ok=True)
    key.parent.mkdir(parents=True, exist_ok=True)
    if any(path.exists() for path in (subscription, installation, key, env_file)):
        raise RuntimeError("CI probe refuses to overwrite any existing SMB enrollment")
    fixtures = (
        (subscription, json.dumps({
            "schema_version": 1,
            "status": "active",
            "llm_base_url": "https://subscription.test.invalid/v1",
            "model_id": "ci-model",
            "access_token": "fake-ci-tenant-access-token-not-live",
        })),
        (installation, json.dumps({
            "schema_version": 1,
            "repository": "ci-org/ci-sandbox",
            "default_branch": "main",
            "app_id": 1234,
            "installation_id": 2345,
        })),
        (key, "-----BEGIN RSA PRIVATE KEY-----\nci fixture\n-----END RSA PRIVATE KEY-----\n"),
    )
    try:
        for path, value in fixtures:
            path.write_text(value, encoding="utf-8")
            path.chmod(0o600)
        subprocess.run(["python3", "scripts/smb-quickstart.py", "check"], cwd=ROOT, check=True)
        subprocess.run(
            ["docker", "compose", "--env-file", ".env.smb", "-f", "compose.smb.yaml",
             "config", "--services"],
            cwd=ROOT, check=True, text=True, capture_output=True
        )
        output = subprocess.run(
            ["docker", "compose", "--env-file", ".env.smb", "-f", "compose.smb.yaml",
             "config", "--services"],
            cwd=ROOT, check=True, text=True, capture_output=True
        ).stdout.splitlines()
        expected = {"docker-socket-proxy", "skills-superset-sync",
                    "hermes-builder", "capability-gateway", "hermeteam-dashboard"}
        if set(output) != expected:
            raise AssertionError(f"Unexpected SMB services: {set(output) ^ expected}")
        print("SMB Compose PASS: exactly five services; no secrets output")
    finally:
        for path in (env_file, *[path for path, _ in fixtures]):
            path.unlink(missing_ok=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
