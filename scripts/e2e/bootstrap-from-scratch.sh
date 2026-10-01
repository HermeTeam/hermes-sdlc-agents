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
require QWEN_API_BASE_URL
require E2E_SANDBOX_REPOSITORY_FULL_NAME
require E2E_GITHUB_APP_ID
require E2E_GITHUB_APP_INSTALLATION_ID
require E2E_GITHUB_APP_PRIVATE_KEY

for role in PLANNER PROJECT_MANAGER REVIEWER RELEASE INCIDENT LEARNING; do
  require "E2E_${role}_GITHUB_MCP_TOKEN"
done
for role in PLANNER PROJECT_MANAGER BUILDER REVIEWER RELEASE INCIDENT LEARNING; do
  require "E2E_ORCHESTRATOR_${role}_GITHUB_TOKEN"
done

if [[ ! "${E2E_SANDBOX_REPOSITORY_FULL_NAME}" =~ ^[^/]+/[^/]+$ ]]; then
  echo "E2E_SANDBOX_REPOSITORY_FULL_NAME must be owner/repository" >&2
  exit 2
fi

if [[ -n "${GITHUB_REPOSITORY:-}" && "${E2E_SANDBOX_REPOSITORY_FULL_NAME,,}" == "${GITHUB_REPOSITORY,,}" ]]; then
  echo "Refusing E2E mutations against the source repository; use a dedicated sandbox repository." >&2
  exit 2
fi

cd "$root"

compose=(
  docker compose
  -f compose.yaml
  -f compose.debug.yaml
  -f compose.capability-gateway.yaml
  -f compose.dynamic-authority.yaml
)

"${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
rm -f .env secrets/e2e-github-app-private-key.pem
rm -rf verification/reports
mkdir -p verification/reports

scripts/bootstrap.sh

python3 - "$root/.env" "$root/secrets/e2e-github-app-private-key.pem" <<'PY'
from pathlib import Path
import os
import secrets
import sys

path = Path(sys.argv[1])
private_key_path = Path(sys.argv[2])
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
qwen_base = os.environ["QWEN_API_BASE_URL"].strip()
if not qwen_base:
    raise SystemExit("QWEN_API_BASE_URL must not be empty")
repo = os.environ["E2E_SANDBOX_REPOSITORY_FULL_NAME"]
owner, name = repo.split("/", 1)
branch = os.environ.get("E2E_SANDBOX_DEFAULT_BRANCH") or "main"

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
    if role == "BUILDER":
        setv("BUILDER_GITHUB_MCP_TOKEN", "DYNAMIC_AUTHORITY_NO_PROVIDER_TOKEN")
    else:
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

# Keep unattended orchestration disabled until the downstream authority canaries pass.
setv("ORCHESTRATOR_ENABLED", "false")
setv("ORCHESTRATOR_APPLY_TRANSITIONS", "false")
setv("ORCHESTRATOR_TRANSITION_COMMENT_ONLY", "true")

# Preferred E2E topology: Builder -> Capability Gateway -> GitHub App -> GitHub MCP.
setv("CAPABILITY_ADMIN_KEY", secrets.token_hex(32))
setv("DASHBOARD_GOVERNANCE_KEY", secrets.token_hex(32))
setv("BUILDER_CAPABILITY_GATEWAY_KEY", secrets.token_hex(32))
setv("CAPABILITY_MAX_AUTO_RISK", "MEDIUM")
setv("CAPABILITY_JUDGE_BASE_URL", qwen_base)
setv("CAPABILITY_JUDGE_API_KEY", qwen_key)
setv("CAPABILITY_JUDGE_MODEL", "qwen3.7-max")
setv("GITHUB_APP_ID", os.environ["E2E_GITHUB_APP_ID"])
setv("GITHUB_APP_INSTALLATION_ID", os.environ["E2E_GITHUB_APP_INSTALLATION_ID"])
setv("GITHUB_APP_PRIVATE_KEY_FILE", "./secrets/e2e-github-app-private-key.pem")
setv("CAPABILITY_EXECUTION_GRANT_TTL_SECONDS", "60")
setv("CAPABILITY_PROVIDER_TOKEN_CACHE_SECONDS", "300")
setv("CAPABILITY_PROVIDER_TIMEOUT_SECONDS", "10")
setv("CAPABILITY_UPSTREAM_TIMEOUT_SECONDS", "180")

setv(
    "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD",
    os.environ.get("E2E_HERMES_DASHBOARD_PASSWORD") or secrets.token_hex(32),
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

private_key_path.write_text(os.environ["E2E_GITHUB_APP_PRIVATE_KEY"], encoding="utf-8")
private_key_path.chmod(0o600)
PY

python3 verification/validate.py
scripts/validate.sh
"${compose[@]}" config --quiet
python3 verification/qwen_probe.py

"${compose[@]}" up -d --build

for _ in $(seq 1 120); do
  if scripts/smoke-test.sh >/dev/null 2>&1; then
    scripts/smoke-test.sh
    break
  fi
  sleep 5
done

scripts/smoke-test.sh
"${compose[@]}" exec -T capability-gateway python -c \
  "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/health', timeout=3).read()"
python3 verification/hermes_canary.py

cat > verification/reports/stage-00-bootstrap.json <<EOF
{
  "stage": "00-bootstrap-from-scratch",
  "status": "PASS",
  "provider": "qwen-api-platform",
  "repository": "${E2E_SANDBOX_REPOSITORY_FULL_NAME}",
  "builder_authority_path": "capability-gateway-github-app",
  "orchestrator_enabled": false
}
EOF

echo "Stage 00 PASS: clean HermeTeam dynamic-authority deployment is healthy with Qwen."
