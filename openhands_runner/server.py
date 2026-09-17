from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
from typing import Any

SOCKET_PATH = Path(os.environ.get("OPENHANDS_RUNNER_SOCKET", "/opt/data/workspace/.hermeteam-openhands/runner.sock"))
WORKSPACE_ROOT = Path("/opt/data/workspace")
MAX_REQUEST_BYTES = 20000
MAX_OUTPUT_CHARS = 20000


def bounded(value: str) -> str:
    return value if len(value) <= MAX_OUTPUT_CHARS else value[:MAX_OUTPUT_CHARS] + "\n...[truncated]"


def safe_workspace(relative: str) -> Path:
    root = WORKSPACE_ROOT.resolve()
    candidate = (root / (relative or ".")).resolve()
    candidate.relative_to(root)
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=check,
    )


def ensure_local_git(workspace: Path) -> None:
    if not (workspace / ".git").exists():
        git(["init", "--initial-branch=hermeteam-local"], workspace)
    remotes = git(["remote"], workspace).stdout.split()
    if remotes:
        raise ValueError("OpenHands workspace must not have a git remote configured")
    git(["add", "-A"], workspace)
    git(
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


def child_env(workspace: Path) -> dict[str, str]:
    model = os.environ.get("BUILDER_OPENHANDS_LLM_MODEL", "").strip()
    api_key = os.environ.get("BUILDER_OPENHANDS_LLM_API_KEY", "").strip()
    base_url = os.environ.get("BUILDER_OPENHANDS_LLM_BASE_URL", "").strip()
    if not model or not api_key:
        raise ValueError("OpenHands runner requires BUILDER_OPENHANDS_LLM_MODEL and BUILDER_OPENHANDS_LLM_API_KEY")

    home = workspace / ".hermeteam-openhands-home"
    home.mkdir(parents=True, exist_ok=True)
    info = workspace / ".git" / "info"
    info.mkdir(parents=True, exist_ok=True)
    exclude = info / "exclude"
    text = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if ".hermeteam-openhands-home/" not in text:
        exclude.write_text(text + "\n.hermeteam-openhands-home/\n", encoding="utf-8")

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


def run_task(request: dict[str, Any]) -> dict[str, Any]:
    task = str(request.get("task") or "").strip()
    if not task:
        raise ValueError("task is required")
    if len(task) > 12000:
        raise ValueError("task exceeds 12000 characters")
    timeout = min(max(int(request.get("timeout_seconds") or 900), 30), 1800)
    workspace = safe_workspace(str(request.get("workspace") or "."))
    ensure_local_git(workspace)
    binary = shutil.which("openhands")
    if binary is None:
        raise RuntimeError("openhands binary is not installed")

    proc = subprocess.run(
        [binary, "--headless", "--json", "--override-with-envs", "--exit-without-confirmation", "-t", task],
        cwd=workspace,
        env=child_env(workspace),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    remotes = git(["remote"], workspace).stdout.split()
    if remotes:
        for remote in remotes:
            git(["remote", "remove", remote], workspace, check=False)
        return {
            "success": False,
            "security_violation": "OpenHands attempted to configure a git remote; remotes were removed",
            "exit_code": proc.returncode,
        }
    return {
        "success": proc.returncode == 0,
        "exit_code": proc.returncode,
        "workspace": str(workspace),
        "changed": git(["status", "--porcelain=v1"], workspace).stdout.splitlines()[:200],
        "stdout": bounded(proc.stdout),
        "stderr": bounded(proc.stderr),
    }


def handle(conn: socket.socket) -> None:
    payload = bytearray()
    while len(payload) <= MAX_REQUEST_BYTES:
        chunk = conn.recv(4096)
        if not chunk:
            break
        payload.extend(chunk)
        if b"\n" in chunk:
            break
    try:
        if len(payload) > MAX_REQUEST_BYTES:
            raise ValueError("request too large")
        request = json.loads(bytes(payload).split(b"\n", 1)[0].decode("utf-8"))
        if not isinstance(request, dict):
            raise ValueError("request must be a JSON object")
        response = run_task(request)
    except subprocess.TimeoutExpired:
        response = {"success": False, "error": "OpenHands task timed out"}
    except Exception as exc:  # noqa: BLE001
        response = {"success": False, "error": str(exc)}
    conn.sendall((json.dumps(response, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))


def main() -> None:
    SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SOCKET_PATH.exists() or SOCKET_PATH.is_socket():
        SOCKET_PATH.unlink()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(SOCKET_PATH))
        os.chmod(SOCKET_PATH, 0o660)
        server.listen(4)
        while True:
            conn, _ = server.accept()
            with conn:
                handle(conn)


if __name__ == "__main__":
    main()
