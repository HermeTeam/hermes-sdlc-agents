from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

PLUGIN_VERSION = "0.1.0"
WORKSPACE_ROOT = Path("/opt/data/workspace")
MAX_OUTPUT_CHARS = 20000


def _result(**payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _bounded(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + "\n...[truncated]"


def _safe_workspace(relative: str) -> Path:
    root = WORKSPACE_ROOT.resolve()
    candidate = (root / (relative or ".")).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("workspace must stay under /opt/data/workspace") from exc
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def _git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=check,
    )


def _ensure_local_git(workspace: Path) -> None:
    if not (workspace / ".git").exists():
        _git(["init", "--initial-branch=hermeteam-local"], workspace)
    remotes = _git(["remote"], workspace).stdout.split()
    if remotes:
        raise ValueError("OpenHands workspace must not have a git remote configured")
    # Snapshot the materialized provider state. This is local-only evidence;
    # provider writes still happen exclusively through the repository MCP/API.
    _git(["add", "-A"], workspace)
    _git(
        [
            "-c",
            "user.name=HermeTeam Builder",
            "-c",
            "user.email=builder@local.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "HermeTeam OpenHands baseline",
        ],
        workspace,
        check=False,
    )


def _openhands_env(workspace: Path) -> dict[str, str]:
    model = os.environ.get("BUILDER_OPENHANDS_LLM_MODEL", "").strip()
    api_key = os.environ.get("BUILDER_OPENHANDS_LLM_API_KEY", "").strip()
    base_url = os.environ.get("BUILDER_OPENHANDS_LLM_BASE_URL", "").strip()
    if not model:
        raise ValueError("BUILDER_OPENHANDS_LLM_MODEL is required")
    if not api_key:
        raise ValueError("BUILDER_OPENHANDS_LLM_API_KEY is required")

    home = workspace / ".hermeteam-openhands-home"
    home.mkdir(parents=True, exist_ok=True)
    git_info = workspace / ".git" / "info"
    git_info.mkdir(parents=True, exist_ok=True)
    exclude = git_info / "exclude"
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if ".hermeteam-openhands-home/" not in existing:
        exclude.write_text(existing + "\n.hermeteam-openhands-home/\n", encoding="utf-8")

    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(home),
        "USER": "hermeteam-openhands",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "OPENHANDS_SUPPRESS_BANNER": "1",
        "LLM_MODEL": model,
        "LLM_API_KEY": api_key,
    }
    if base_url:
        env["LLM_BASE_URL"] = base_url
    return env


def delegate(params: dict[str, Any], **kwargs: Any) -> str:
    del kwargs
    if os.environ.get("ORCHESTRATOR_ROLE", "").strip() != "builder":
        return _result(success=False, error="openhands_delegate is restricted to the builder role")
    if os.environ.get("BUILDER_OPENHANDS_ENABLED", "true").lower() not in {"1", "true", "yes", "on"}:
        return _result(success=False, error="OpenHands delegation is disabled")

    task = str(params.get("task") or "").strip()
    if not task:
        return _result(success=False, error="task is required")
    if len(task) > 12000:
        return _result(success=False, error="task exceeds 12000 characters")

    try:
        timeout = int(params.get("timeout_seconds") or 900)
    except (TypeError, ValueError):
        timeout = 900
    timeout = min(max(timeout, 30), 1800)

    binary = shutil.which("openhands")
    if binary is None:
        return _result(success=False, error="openhands binary is not installed")

    try:
        workspace = _safe_workspace(str(params.get("workspace") or "."))
        _ensure_local_git(workspace)
        env = _openhands_env(workspace)
        proc = subprocess.run(
            [
                binary,
                "--headless",
                "--json",
                "--override-with-envs",
                "--exit-without-confirmation",
                "-t",
                task,
            ],
            cwd=workspace,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        remotes = _git(["remote"], workspace).stdout.split()
        if remotes:
            for remote in remotes:
                _git(["remote", "remove", remote], workspace, check=False)
            return _result(
                success=False,
                security_violation="OpenHands attempted to configure a git remote; remotes were removed",
                exit_code=proc.returncode,
            )
        status = _git(["status", "--porcelain=v1"], workspace).stdout.splitlines()
        return _result(
            success=proc.returncode == 0,
            plugin_version=PLUGIN_VERSION,
            exit_code=proc.returncode,
            workspace=str(workspace),
            changed=status[:200],
            stdout=_bounded(proc.stdout),
            stderr=_bounded(proc.stderr),
        )
    except subprocess.TimeoutExpired:
        return _result(success=False, error=f"OpenHands exceeded timeout of {timeout}s")
    except Exception as exc:  # noqa: BLE001
        return _result(success=False, error=str(exc))


def register(ctx: Any) -> None:
    schema = {
        "name": "openhands_delegate",
        "description": (
            "Delegate a bounded coding/refactoring task to OpenHands in the local builder scratch workspace. "
            "The tool receives only dedicated LLM credentials, never Git/provider credentials. Provider writes "
            "must still be performed by Hermes through the repository MCP/API after reviewing the local changes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Concrete coding task for OpenHands."},
                "workspace": {
                    "type": "string",
                    "description": "Relative path below /opt/data/workspace; defaults to the workspace root.",
                    "default": ".",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "minimum": 30,
                    "maximum": 1800,
                    "default": 900,
                },
            },
            "required": ["task"],
        },
    }
    ctx.register_tool(
        name="openhands_delegate",
        toolset="hermeteam-openhands",
        schema=schema,
        handler=delegate,
        description=schema["description"],
        max_result_size_chars=50000,
    )
