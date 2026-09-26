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
    # The local health endpoint checks configuration; this bounded inference
    # proves the operator-provisioned subscription is actually usable.
    "${compose[@]}" exec -T capability-gateway python - <<'PY'
import json
import os
from urllib.request import Request, urlopen

payload = {
    "model": "hermeteam-subscribed",
    "messages": [{"role": "user", "content": "Reply READY."}],
    "max_tokens": 32,
    "stream": False,
}
request = Request(
    "http://subscription-relay:8085/v1/chat/completions",
    data=json.dumps(payload).encode("utf-8"),
    headers={
        "Authorization": "Bearer " + os.environ["CAPABILITY_JUDGE_API_KEY"],
        "Content-Type": "application/json",
    },
)
with urlopen(request, timeout=90) as result:
    answer = json.loads(result.read(65536))
if not answer.get("choices"):
    raise SystemExit("Subscription model returned no completion choices")
print("Subscription inference PASS (subscription token was never sent to Builder)")
PY
    echo "SMB runtime PASS: subscription inference, dynamic authority, Safe Builder and dashboard healthy"
    exit 0
  fi
  sleep 2
done
echo "SMB runtime FAIL: health check not ready; inspect docker compose ps (not unfiltered logs)" >&2
exit 1
