#!/usr/bin/env python3
"""HermeTeam SMB runtime: consume subscription binding, never select a model provider."""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SUBSCRIPTION = ROOT / "runtime/smb/subscription.json"
INSTALLATION = ROOT / "runtime/smb/installation.json"
APP_KEY = ROOT / "secrets/smb/github-app.pem"
ENV_FILE = ROOT / ".env.smb"
COMPOSE = ROOT / "compose.smb.yaml"
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
RUNTIME_KEYS = ("SMB_BUILDER_API_KEY", "SMB_BUILDER_GATEWAY_KEY",
                "SMB_CAPABILITY_ADMIN_KEY", "SMB_DASHBOARD_GOVERNANCE_KEY")


class SetupError(ValueError):
    pass


def private_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise SetupError(f"Missing provisioned private file: {path.relative_to(ROOT)}")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise SetupError(f"Private file must be owner-only (chmod 600): {path.relative_to(ROOT)}")
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise SetupError(f"Invalid provisioned JSON: {path.relative_to(ROOT)}") from exc
    if not isinstance(result, dict):
        raise SetupError(f"Invalid provisioned object: {path.relative_to(ROOT)}")
    return result


def read_subscription() -> dict[str, str]:
    binding = private_json(SUBSCRIPTION)
    if set(binding) != {"schema_version", "status", "llm_base_url", "model_id", "access_token"}:
        raise SetupError("Subscription binding does not match the managed HermeTeam contract")
    if binding["schema_version"] != 1 or binding["status"] != "active":
        raise SetupError("HermeTeam subscription is not active")
    base = binding["llm_base_url"]
    if not isinstance(base, str):
        raise SetupError("Invalid subscription gateway URL")
    parsed = urlsplit(base)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or not parsed.path.rstrip("/").endswith("/v1")):
        raise SetupError("Subscription gateway URL must be a credential-free HTTPS /v1 endpoint")
    if not isinstance(binding["model_id"], str) or not re.fullmatch(r"[a-zA-Z0-9_.:/-]{1,120}", binding["model_id"]):
        raise SetupError("Subscription did not assign a valid model ID")
    token = binding["access_token"]
    if not isinstance(token, str) or len(token) < 24 or any(c.isspace() for c in token):
        raise SetupError("Subscription access token is missing or malformed")
    return {
        "SMB_SUBSCRIPTION_LLM_BASE_URL": base.rstrip("/"),
        # Existing Gateway judge appends /v1/chat/completions itself.
        "SMB_SUBSCRIPTION_JUDGE_BASE_URL": base.rstrip("/")[:-3],
        "SMB_SUBSCRIPTION_MODEL_ID": binding["model_id"],
        "SMB_SUBSCRIPTION_ACCESS_TOKEN": token,
    }


def read_github() -> dict[str, str]:
    setting = private_json(INSTALLATION)
    if set(setting) != {"schema_version", "repository", "default_branch", "app_id", "installation_id"}:
        raise SetupError("GitHub App installation binding does not match the SMB contract")
    if setting["schema_version"] != 1:
        raise SetupError("Unsupported GitHub App installation binding")
    repository = setting["repository"]
    if not isinstance(repository, str) or not REPOSITORY.fullmatch(repository):
        raise SetupError("GitHub repository must be owner/repository")
    default_branch = setting["default_branch"]
    if not isinstance(default_branch, str) or not re.fullmatch(r"[A-Za-z0-9_./-]{1,100}", default_branch):
        raise SetupError("Invalid default branch")
    if any(part in ("", ".", "..") for part in default_branch.split("/")):
        raise SetupError("Unsafe default branch")
    if not all(isinstance(setting[name], int) and setting[name] > 0 for name in ("app_id", "installation_id")):
        raise SetupError("GitHub App and installation IDs must be positive integers")
    if APP_KEY.is_symlink() or not APP_KEY.is_file() or stat.S_IMODE(APP_KEY.stat().st_mode) & 0o077:
        raise SetupError("Provision a GitHub App private key at secrets/smb/github-app.pem (mode 600)")
    if "PRIVATE KEY" not in APP_KEY.read_text(encoding="utf-8"):
        raise SetupError("GitHub App private key does not look like a PEM file")
    owner, name = repository.split("/", 1)
    return {
        "SMB_GITHUB_APP_ID": str(setting["app_id"]),
        "SMB_GITHUB_APP_INSTALLATION_ID": str(setting["installation_id"]),
        "SMB_GITHUB_APP_PRIVATE_KEY_FILE": "./secrets/smb/github-app.pem",
        "SMB_GITHUB_REPOSITORY": repository,
        "SMB_GITHUB_DEFAULT_BRANCH": default_branch,
        "SMB_GITHUB_OWNER": owner,
        "SMB_GITHUB_NAME": name,
    }


def existing_internal_keys() -> dict[str, str]:
    if not ENV_FILE.exists():
        return {}
    if ENV_FILE.is_symlink() or stat.S_IMODE(ENV_FILE.stat().st_mode) & 0o077:
        raise SetupError("Existing .env.smb must be owner-only and not a symlink")
    values: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            name, value = line.split("=", 1)
            if name in RUNTIME_KEYS and re.fullmatch(r"[a-f0-9]{64}", value):
                values[name] = value
    return values


def write_private_env(values: dict[str, str]) -> None:
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".env.smb.", dir=ROOT, text=True)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as output:
            for key, value in values.items():
                if not re.fullmatch(r"[A-Z0-9_]+", key) or any(ch in value for ch in "\r\n\x00$"):
                    raise SetupError("Invalid subscription or installation binding value")
                output.write(f"{key}={value}\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, ENV_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def initialize() -> None:
    values = read_subscription()
    values.update(read_github())
    previous = existing_internal_keys()
    for key in RUNTIME_KEYS:
        values[key] = previous.get(key) or secrets.token_hex(32)
    write_private_env(values)
    print("SMB configuration ready: subscription model bound; GitHub App repository scoped; secrets not displayed.")



def probe_subscription() -> None:
    """Verify the exact subscription-assigned model; never probe a customer-selected provider."""
    binding = read_subscription()
    endpoint = binding["SMB_SUBSCRIPTION_LLM_BASE_URL"] + "/chat/completions"
    payload = json.dumps({
        "model": binding["SMB_SUBSCRIPTION_MODEL_ID"],
        "messages": [{"role": "user", "content": "HermeTeam startup readiness. Reply READY."}],
        "max_tokens": 128,
    }).encode("utf-8")
    request = Request(
        endpoint,
        data=payload,
        method="POST",
        headers={
            "Authorization": "Bearer " + binding["SMB_SUBSCRIPTION_ACCESS_TOKEN"],
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            body = json.loads(response.read(262144))
        choices = body.get("choices") if isinstance(body, dict) else None
        if not isinstance(choices, list) or not choices:
            raise SetupError("Subscription model readiness returned no choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict) or not isinstance(message.get("content"), str) or not message["content"].strip():
            raise SetupError("Subscription model readiness returned no response")
    except HTTPError as exc:
        raise SetupError(f"Subscription gateway rejected readiness request (HTTP {exc.code})") from exc
    except (URLError, TimeoutError, ValueError, TypeError) as exc:
        raise SetupError("Subscription gateway readiness request failed") from exc
    print("Subscription model readiness PASS (provider and credentials remain hidden).")


def run_compose(*arguments: str) -> None:
    subprocess.run(
        ["docker", "compose", "--env-file", str(ENV_FILE), "-f", str(COMPOSE), *arguments],
        cwd=ROOT,
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="HermeTeam Safe Builder: subscription-managed SMB runtime")
    parser.add_argument("command", choices=("init", "check", "probe", "up", "status", "down"))
    args = parser.parse_args()
    try:
        if args.command in ("init", "check", "probe", "up"):
            initialize()
        if args.command == "init":
            return 0
        if not ENV_FILE.is_file():
            raise SetupError("Run init after HermeTeam subscription and GitHub App enrollment")
        if args.command in ("check", "probe", "up"):
            run_compose("config", "--quiet")
            print("Compose validation PASS: only the SMB services are selected.")
        if args.command in ("probe", "up"):
            probe_subscription()
        if args.command == "up":
            run_compose("up", "-d", "--build", "--wait", "--wait-timeout", "360")
        if args.command == "status":
            run_compose("ps")
        if args.command == "down":
            # Never delete volumes automatically; preserve the evidence and grants.
            run_compose("down")
    except (SetupError, subprocess.CalledProcessError, OSError) as exc:
        # No exception containing a raw command or provisioned secret is printed.
        if isinstance(exc, SetupError):
            print(f"SMB setup blocked: {exc}", file=sys.stderr)
        else:
            print("SMB runtime command failed; inspect sanitized service status.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
