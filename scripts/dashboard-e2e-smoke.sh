#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$(realpath "${BASH_SOURCE[0]}")")/.." && pwd)"
project="hermes-dashboard-e2e-$RANDOM-$$"
port="$(python3 - <<'PY'
import socket
s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()
PY
)"
compose=(docker compose --project-directory "$root" -p "$project" -f "$root/dashboard/tests/e2e/compose.e2e.yaml")
skip() { printf 'SKIP: dashboard E2E: %s\n' "$1"; exit 0; }
command -v docker >/dev/null 2>&1 || skip "Docker CLI is unavailable"
docker compose version >/dev/null 2>&1 || skip "Docker Compose v2 is unavailable"
docker info >/dev/null 2>&1 || skip "Docker daemon is unavailable"
[[ -x /usr/bin/google-chrome || -x /usr/bin/google-chrome-stable || -x /snap/bin/chromium ]] || skip "Chromium executable is unavailable"
[[ -d "$root/dashboard/node_modules/@playwright/test" ]] || skip "Playwright dependency is not installed; run npm --prefix dashboard ci"
cleanup() { "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT INT TERM

export E2E_PROJECT="$project" DASHBOARD_E2E_PORT="$port" DASHBOARD_E2E_BASE_URL="http://127.0.0.1:$port"
export PLAYWRIGHT_CHROMIUM_EXECUTABLE="$(command -v google-chrome || command -v google-chrome-stable || command -v chromium-browser || command -v chromium)"
"${compose[@]}" up --build -d
for _ in $(seq 1 60); do curl --fail --silent --show-error --max-time 2 "$DASHBOARD_E2E_BASE_URL/health" >/dev/null && break; sleep 1; done
curl --fail --silent --show-error --max-time 2 "$DASHBOARD_E2E_BASE_URL/health" >/dev/null
overview="$(curl --fail --silent --show-error --max-time 5 "$DASHBOARD_E2E_BASE_URL/api/overview")"
python3 - "$overview" <<'PY'
import json, sys
x=json.loads(sys.argv[1]); assert len(x['roles']) == 7 and x['partial']
assert [r['role'] for r in x['roles']] == ['planner','project-manager','builder','reviewer','release','incident','learning']
assert all('t11-canary-secret' not in json.dumps(r) for r in x['roles'])
assert x['roles'][0]['agentState']=='WORKING' and x['roles'][1]['agentState']=='QUEUED'
assert x['roles'][2]['agentState']=='WAITING' and x['roles'][3]['agentState']=='BLOCKED'
assert x['roles'][5]['sourceError']['code']=='malformed_response' and x['roles'][6]['sourceError']['code']=='timeout'
PY
for path in / /health /api/overview /assets/does-not-exist.js; do curl --silent --show-error --max-time 3 -D /tmp/e2e-headers -o /tmp/e2e-body "$DASHBOARD_E2E_BASE_URL$path" >/dev/null || true; grep -qi '^content-security-policy:' /tmp/e2e-headers; grep -qi '^x-content-type-options: nosniff' /tmp/e2e-headers; ! grep -qi '^server:' /tmp/e2e-headers; ! grep -qi '^access-control-allow-origin:' /tmp/e2e-headers; done
[[ "$(curl --silent --output /dev/null --write-out '%{http_code}' -X POST "$DASHBOARD_E2E_BASE_URL/api/overview")" == 405 ]]
"${compose[@]}" stop hermes-builder >/dev/null
sleep 3
curl --fail --silent "$DASHBOARD_E2E_BASE_URL/api/overview" | python3 -c 'import json,sys; x=json.load(sys.stdin); r=next(r for r in x["roles"] if r["role"]=="builder"); assert r["container"]["state"]=="STOPPED" and r["agentState"]=="UNAVAILABLE"'
"${compose[@]}" start hermes-builder >/dev/null
sleep 3
curl --fail --silent "$DASHBOARD_E2E_BASE_URL/api/overview" | python3 -c 'import json,sys; x=json.load(sys.stdin); r=next(r for r in x["roles"] if r["role"]=="builder"); assert r["container"]["state"]=="RUNNING"'
"${compose[@]}" restart hermeteam-dashboard >/dev/null
for _ in $(seq 1 20); do curl --fail --silent --max-time 2 "$DASHBOARD_E2E_BASE_URL/health" >/dev/null && break; sleep 1; done
curl --fail --silent "$DASHBOARD_E2E_BASE_URL/api/overview" | python3 -c 'import json,sys; x=json.load(sys.stdin); assert len(x["roles"]) == 7 and x["roles"][0]["agentState"] == "WORKING"'
dashboard_id="$("${compose[@]}" ps -q hermeteam-dashboard)"
[[ "$(docker inspect "$dashboard_id" --format '{{json .Mounts}}')" == '[]' ]]
proxy_ip="$(docker inspect "$("${compose[@]}" ps -q docker-socket-proxy)" --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')"
probe="$project-probe"; docker run -d --rm --name "$probe" --network "hermes-dashboard-e2e-$project-control" --entrypoint sleep curlimages/curl:8.12.1 30 >/dev/null
trap 'docker rm -f "$probe" >/dev/null 2>&1 || true; cleanup' EXIT INT TERM
[[ "$(docker exec "$probe" curl --silent --output /dev/null --write-out '%{http_code}' -X POST "http://$proxy_ip:2375/containers/nope/start")" == 403 ]]
[[ "$(docker exec "$probe" curl --silent --output /dev/null --write-out '%{http_code}' "http://$proxy_ip:2375/images/json")" == 403 ]]
test "$(docker inspect "$dashboard_id" --format '{{json .NetworkSettings.Ports}}')" != '{}'
(cd "$root/dashboard" && npx playwright test --config playwright.config.ts)
echo "Dashboard E2E smoke passed: production image, restricted proxy, seven fixtures, API/security/restart, and browser desktop/mobile checks."
