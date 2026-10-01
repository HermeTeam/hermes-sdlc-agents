#!/usr/bin/env python3
from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]

ROLES = {
    "planner": (18642, "PLANNER_API_SERVER_KEY", "hermes-planner"),
    "project-manager": (18648, "PROJECT_MANAGER_API_SERVER_KEY", "hermes-project-manager"),
    "builder": (18643, "BUILDER_API_SERVER_KEY", "hermes-builder"),
    "reviewer": (18644, "REVIEWER_API_SERVER_KEY", "hermes-reviewer"),
    "release": (18645, "RELEASE_API_SERVER_KEY", "hermes-release"),
    "incident": (18646, "INCIDENT_API_SERVER_KEY", "hermes-incident"),
    "learning": (18647, "LEARNING_API_SERVER_KEY", "hermes-learning"),
}


def env_file() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def request_json(url: str, key: str, *, body: dict | None = None, timeout: int = 30) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = Request(
        url,
        data=data,
        method="GET" if body is None else "POST",
        headers={
            "Authorization": "Bearer " + key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(str(exc)) from exc


def main() -> int:
    env = env_file()
    report: dict[str, str] = {}
    for role, (default_port, key_name, model_name) in ROLES.items():
        port_key = role.upper().replace("-", "_") + "_API_PORT"
        port = int(env.get(port_key, default_port))
        key = env[key_name]
        base = f"http://127.0.0.1:{port}"
        payload = request_json(
            base + "/v1/runs",
            key,
            body={
                "model": model_name,
                "session_id": f"e2e-readiness-{role}",
                "input": (
                    "HermeTeam readiness canary. Do not use tools and do not mutate external state. "
                    "Return the role's normal final-response structure with a successful readiness result."
                ),
            },
        )
        run_id = str(payload.get("id") or payload.get("run_id") or "")
        if not run_id:
            raise RuntimeError(f"{role}: run id missing")
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            current = request_json(base + f"/v1/runs/{run_id}", key)
            status = str(current.get("status") or current.get("state") or "").lower()
            if status in {"completed", "succeeded", "success", "done"}:
                report[role] = "PASS"
                print(f"Hermes Qwen canary PASS: {role}")
                break
            if status in {"failed", "error", "cancelled", "canceled"}:
                raise RuntimeError(f"{role}: run failed with status {status}")
            time.sleep(2)
        else:
            raise TimeoutError(f"{role}: readiness run timed out")

    out = ROOT / "verification" / "reports"
    out.mkdir(parents=True, exist_ok=True)
    (out / "hermes-qwen-readiness.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
