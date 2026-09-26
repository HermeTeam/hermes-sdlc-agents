#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"
compose=(docker compose --env-file .env.smb -f compose.smb.yaml)
for attempt in $(seq 1 90); do
  if "${compose[@]}" exec -T subscription-relay python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8085/health', timeout=2).read()" >/dev/null 2>&1 \
     && "${compose[@]}" exec -T capability-gateway python -c "import json,urllib.request; a=json.load(urllib.request.urlopen('http://127.0.0.1:8787/health', timeout=2)); assert a['execution_mode']=='dynamic'" >/dev/null 2>&1 \
     && "${compose[@]}" exec -T hermes-builder curl -fsS http://127.0.0.1:8642/health >/dev/null 2>&1 \
     && curl -fsS "http://127.0.0.1:${SMB_DASHBOARD_PORT:-9130}/health" >/dev/null 2>&1; then
    echo "SMB runtime PASS: subscribed model relay, dynamic authority, Safe Builder and dashboard healthy"
    exit 0
  fi
  sleep 2
done
echo "SMB runtime FAIL: health check not ready; inspect docker compose ps (not unfiltered logs)" >&2
exit 1
