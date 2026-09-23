#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$(realpath "${BASH_SOURCE[0]}")")/../.." && pwd)"

if [[ "${HERMETEAM_E2E_EPHEMERAL:-}" != "1" ]]; then
  echo "Refusing destructive from-scratch bootstrap outside an ephemeral E2E runner." >&2
  echo "Set HERMETEAM_E2E_EPHEMERAL=1 only in a disposable test environment." >&2
  exit 2
fi

require() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required E2E variable: $name" >&2
    exit 2
  fi
}

require QWEN_API_KEY
require E2E_SANDBOX_REPOSITORY_FULL_NAME

for role in PLANNER PROJECT_MANAGER BUILDER REVIEWER RELEASE INCIDENT LEARNING; do
  require "E2E_${role}_GITHUB_MCP_TOKEN"
  require "E2E_ORCHESTRATOR_${role}_GITHUB_TOKEN"
done

if [[ ! "${E2E_SANDBOX_REPOSITORY_FULL_NAME}" =~ ^[^/]+/[^/]+$ ]]; then
  echo "E2E_SANDBOX_REPOSITORY_FULL_NAME must be owner/repository" >&2
  exit 2
fi

cd "$root"

docker compose -f compose.yaml -f compose.debug.yaml down --volumes --remove-orphans >/dev/null 2>&1 || true
rm -f .env
rm -rf verification/reports
mkdir -p verification/reports

scripts/bootstrap.sh

python3 - "$root/.env" <<'PY'
from pathlib import Path
import os
import sys

path = Path(sys.argv[1])
original = path.read_text(encoding="utf-8").splitlines()
values = {}
order = []
for raw in original:
    if raw and not raw.lstrip().startswith("#") and "=" in raw:
        key, value = raw.split("=", 1)
        values[key] = value
        order.append(key)

def setv(key: str, value: str) -> None:
    values[key] = value
    if key not in order:
        order.append(key)

qwen_key = os.environ["QWEN_API_KEY"]
qwen_base = os.environ.get("QWEN_API_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
repo = os.environ["E2E_SANDBOX_REPOSITORY_FULL_NAME"]
owner, name = repo.split("/", 1)
branch = os.environ.get("E2E_SANDBOX_DEFAULT_BRANCH", "main")

setv("DASHSCOPE_API_KEY", qwen_key)
setv("OPENAI_API_KEY", qwen_key)
setv("HERMES_MODEL_OPENAI_API_KEY", qwen_key)
setv("QWEN_API_BASE_URL", qwen_base)
setv("HERMES_MODEL_BASE_URL", qwen_base)
setv("HERMES_MODEL_ID", "qwen3.7-plus")
setv("HERMES_JSON_REPAIR_MODEL_ID", "qwen3.5-flash")
setv("HERMES_JSON_REPAIR_MODEL_BASE_URL", qwen_base)
setv("HERMES_JSON_REPAIR_OPENAI_API_KEY", qwen_key)

role_models = {
    "PLANNER": "qwen3.7-max",
    "PROJECT_MANAGER": "qwen3.7-max",
    "BUILDER": "qwen3.7-plus",
    "REVIEWER": "qwen3.7-max",
    "RELEASE": "qwen3.7-plus",
    "INCIDENT": "qwen3.5-flash",
    "LEARNING": "qwen3.5-flash",
}
for role, model in role_models.items():
    setv(f"{role}_HERMES_MODEL_ID", model)
    setv(f"{role}_HERMES_MODEL_BASE_URL", qwen_base)
    setv(f"{role}_HERMES_MODEL_OPENAI_API_KEY", qwen_key)
    setv(f"{role}_GITHUB_MCP_TOKEN", os.environ[f"E2E_{role}_GITHUB_MCP_TOKEN"])
    setv(
        f"ORCHESTRATOR_{role}_GITHUB_TOKEN",
        os.environ[f"E2E_ORCHESTRATOR_{role}_GITHUB_TOKEN"],
    )

setv("REPOSITORY_ID", repo)
setv("REPOSITORY_PROVIDER", "github")
setv("REPOSITORY_ACCESS_MODE", "github-direct-api-mcp")
setv("REPOSITORY_DEFAULT_BRANCH", branch)
setv("REPOSITORY_CLONE_ALLOWED", "false")
setv("GITHUB_OWNER", owner)
setv("GITHUB_REPOSITORY", name)
setv("GITHUB_REPOSITORY_FULL_NAME", repo)
setv("GITHUB_REPOSITORY_HTML_URL", f"https://github.com/{repo}")
setv("GITHUB_REPOSITORY_API_URL", f"https://api.github.com/repos/{repo}")
setv("ORCHESTRATOR_ENABLED", "false")
setv("ORCHESTRATOR_APPLY_TRANSITIONS", "false")
setv("ORCHESTRATOR_TRANSITION_COMMENT_ONLY", "true")
setv(
    "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD",
    os.environ.get("E2E_HERMES_DASHBOARD_PASSWORD", "e2e-only-not-for-production"),
)

lines = []
seen = set()
for raw in original:
    if raw and not raw.lstrip().startswith("#") and "=" in raw:
        key = raw.split("=", 1)[0]
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"{key}={values[key]}")
    else:
        lines.append(raw)
for key in order:
    if key not in seen:
        lines.append(f"{key}={values[key]}")
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
path.chmod(0o600)
PY

python3 verification/validate.py
scripts/validate.sh
docker compose -f compose.yaml -f compose.debug.yaml config --quiet
python3 verification/qwen_probe.py

docker compose -f compose.yaml -f compose.debug.yaml up -d --build

for _ in $(seq 1 120); do
  if scripts/smoke-test.sh >/dev/null 2>&1; then
    scripts/smoke-test.sh
    break
  fi
  sleep 5
done

scripts/smoke-test.sh
python3 verification/hermes_canary.py

cat > verification/reports/stage-00-bootstrap.json <<EOF
{
  "stage": "00-bootstrap-from-scratch",
  "status": "PASS",
  "provider": "qwen-api-platform",
  "repository": "${E2E_SANDBOX_REPOSITORY_FULL_NAME}",
  "orchestrator_enabled": false
}
EOF

echo "Stage 00 PASS: HermeTeam configured and deployed from a clean ephemeral state with Qwen."
