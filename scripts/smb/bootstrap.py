#!/usr/bin/env python3
"""Idempotent Phase-1 SMB configuration: subscription is already provisioned.

This is intentionally not a provider picker or GitHub App registration wizard.
A HermeTeam subscription provisioner supplies the model endpoint, model and
upstream token before this command; the customer supplies only GitHub binding.
"""
from __future__ import annotations

import os
import re
import secrets
import stat
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / ".env.smb"
SUBSCRIPTION = ROOT / "secrets" / "smb-subscription.env"
TOKEN = ROOT / "secrets" / "smb-subscription.token"
GITHUB_KEY = ROOT / "secrets" / "smb-github-app.pem"
REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
DIGEST_RE = re.compile(r"[a-zA-Z0-9./:_-]+@sha256:[0-9a-f]{64}")
BRANCH_RE = re.compile(r"[A-Za-z0-9._/-]+")


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("subscription provisioning file has invalid format")
        key, value = line.split("=", 1)
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", key) or key in values:
            raise ValueError("subscription provisioning file has invalid keys")
        values[key] = value
    return values


def private_file(path: Path, description: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"missing or unsafe {description}: {path.name}")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError(f"{description} must be owner-only (chmod 600): {path.name}")


def check_subscription() -> None:
    private_file(SUBSCRIPTION, "operator-provisioned subscription configuration")
    private_file(TOKEN, "operator-provisioned subscription token")
    private_file(GITHUB_KEY, "GitHub App private key")
    config = parse_env(SUBSCRIPTION)
    subscription_url = config.get("SMB_SUBSCRIPTION_BASE_URL", "")
    url = urlsplit(subscription_url)
    if (
        url.scheme != "https"
        or not url.hostname
        or not url.path.rstrip("/").endswith("/v1")
        or url.username
        or url.password
        or url.query
        or url.fragment
        or "SUBSCRIPTION_ENDPOINT_FROM_HERMETEAM" in subscription_url.upper()
        or "CHANGE_ME" in subscription_url.upper()
    ):
        raise ValueError("HermeTeam must provision a valid HTTPS subscription /v1 endpoint")
    model = config.get("SMB_SUBSCRIPTION_MODEL", "")
    if (
        not model
        or model.startswith("SUBSCRIPTION_")
        or model.startswith("CHANGE_ME")
        or any(ord(char) < 33 for char in model)
        or len(model) > 150
    ):
        raise ValueError("HermeTeam must provision a subscription model")
    if len(TOKEN.read_text(encoding="utf-8").strip()) < 16:
        raise ValueError("HermeTeam subscription token missing or invalid")
    if "-----BEGIN" not in GITHUB_KEY.read_text(encoding="utf-8")[:100]:
        raise ValueError("invalid GitHub App private key file")


def settings(source: dict[str, str]) -> dict[str, str]:
    repo = source.get("SMB_GITHUB_REPOSITORY_FULL_NAME", "").strip()
    if not REPO_RE.fullmatch(repo):
        raise ValueError("SMB_GITHUB_REPOSITORY_FULL_NAME must be owner/repo")
    if repo.lower() == "hermeteam/hermes-sdlc-agents":
        raise ValueError("use a separate test repository for the first canary, not the HermeTeam source")
    branch = source.get("SMB_GITHUB_DEFAULT_BRANCH", "main")
    if (
        not BRANCH_RE.fullmatch(branch)
        or ".." in branch
        or branch.startswith("/")
        or branch.endswith("/")
    ):
        raise ValueError("SMB_GITHUB_DEFAULT_BRANCH must be a safe branch name")
    for name in ("SMB_GITHUB_APP_ID", "SMB_GITHUB_APP_INSTALLATION_ID"):
        if not re.fullmatch(r"[0-9]{1,20}", source.get(name, "")):
            raise ValueError(f"{name} is a required numeric GitHub App identifier")
    image = source.get("SMB_HERMES_BASE_IMAGE", "")
    if not DIGEST_RE.fullmatch(image):
        raise ValueError("SMB_HERMES_BASE_IMAGE must be pinned to an immutable sha256 digest")
    owner, name = repo.split("/", 1)
    return {
        "SMB_GITHUB_REPOSITORY_FULL_NAME": repo,
        "SMB_GITHUB_OWNER": owner,
        "SMB_GITHUB_REPOSITORY": name,
        "SMB_GITHUB_DEFAULT_BRANCH": branch,
        "SMB_GITHUB_APP_ID": source["SMB_GITHUB_APP_ID"],
        "SMB_GITHUB_APP_INSTALLATION_ID": source["SMB_GITHUB_APP_INSTALLATION_ID"],
        "SMB_HERMES_BASE_IMAGE": image,
    }


def create(source: dict[str, str]) -> bool:
    check_subscription()
    if TARGET.exists():
        private_file(TARGET, "existing SMB configuration")
        print("Existing .env.smb preserved; use scripts/smb/doctor.py to validate it")
        return False

    values = settings(source)
    for name in (
        "SMB_MODEL_RELAY_KEY",
        "SMB_BUILDER_GATEWAY_KEY",
        "SMB_CAPABILITY_ADMIN_KEY",
        "SMB_DASHBOARD_GOVERNANCE_KEY",
        "SMB_BUILDER_API_KEY",
    ):
        values[name] = secrets.token_hex(32)
    fd = os.open(TARGET, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        for key, value in values.items():
            output.write(f"{key}={value}\n")
    print("SMB runtime configuration created. Subscription/model selection remains operator-owned.")
    return True


def main() -> int:
    try:
        create(dict(os.environ))
    except (ValueError, OSError) as exc:
        print(f"SMB preflight failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
