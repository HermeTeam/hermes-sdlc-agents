#!/usr/bin/env bash
# Offline Compose contract: dummy credentials only, no network or provider mutation.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"
for path in secrets/smb-subscription.env secrets/smb-subscription.token secrets/smb-github-app.pem; do
  if [[ -e "$path" ]]; then
    echo "Refusing to overwrite existing subscription/GitHub credentials in Compose test" >&2
    exit 2
  fi
done
tmp="$(mktemp -d)"
cleanup() {
  rm -f secrets/smb-subscription.env secrets/smb-subscription.token secrets/smb-github-app.pem
  rm -rf "$tmp"
}
trap cleanup EXIT
umask 077
printf '%s\n' 'SMB_SUBSCRIPTION_BASE_URL=https://subscription.example.org/v1' 'SMB_SUBSCRIPTION_MODEL=operator-fixed' > secrets/smb-subscription.env
printf '%s\n' 'test-only-fake-subscription-token-1234' > secrets/smb-subscription.token
printf '%s\n' '-----BEGIN PRIVATE KEY-----' 'test-only-not-a-real-private-key' '-----END PRIVATE KEY-----' > secrets/smb-github-app.pem
cat > "$tmp/env" <<'EOF'
SMB_GITHUB_REPOSITORY_FULL_NAME=test-org/smb-sandbox
SMB_GITHUB_OWNER=test-org
SMB_GITHUB_REPOSITORY=smb-sandbox
SMB_GITHUB_DEFAULT_BRANCH=main
SMB_GITHUB_APP_ID=1234
SMB_GITHUB_APP_INSTALLATION_ID=5678
SMB_HERMES_BASE_IMAGE=example.invalid/hermes@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
SMB_MODEL_RELAY_KEY=1111111111111111111111111111111111111111111111111111111111111111
SMB_BUILDER_GATEWAY_KEY=2222222222222222222222222222222222222222222222222222222222222222
SMB_CAPABILITY_ADMIN_KEY=3333333333333333333333333333333333333333333333333333333333333333
SMB_DASHBOARD_GOVERNANCE_KEY=4444444444444444444444444444444444444444444444444444444444444444
SMB_BUILDER_API_KEY=5555555555555555555555555555555555555555555555555555555555555555
EOF
docker compose --env-file "$tmp/env" -f compose.smb.yaml config --quiet
docker compose --env-file "$tmp/env" -f compose.smb.yaml config --format json | python3 -c '
import json, sys
stack = json.load(sys.stdin)
services = stack["services"]
assert len(services) == 6, "only six SMB infrastructure/runtime services are expected"
builder = services["hermes-builder"]
gateway = services["capability-gateway"]
relay = services["subscription-relay"]
assert builder["environment"]["GIT_PROVIDER_MCP_URL"] == "http://capability-gateway:8787/mcp"
assert builder["environment"]["ORCHESTRATOR_ENABLED"] == "false"
assert "GITHUB_APP_PRIVATE_KEY_PATH" not in builder["environment"]
assert "SMB_SUBSCRIPTION_TOKEN" not in builder["environment"]
assert gateway["environment"]["CAPABILITY_EXECUTION_MODE"] == "dynamic"
assert "smb_github_app_private_key" in gateway["secrets"][0]["source"]
assert "smb_subscription_token" in relay["secrets"][0]["source"]
assert len(services["hermeteam-dashboard"]["ports"]) == 1
assert services["hermeteam-dashboard"]["ports"][0]["host_ip"] == "127.0.0.1"
print("SMB Compose rendering and security contracts PASS")
'
