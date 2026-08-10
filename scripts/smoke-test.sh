#!/usr/bin/env bash
set -euo pipefail

bundle_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
set -a
source "${bundle_root}/.env"
set +a

roles=(planner project-manager builder reviewer release incident learning)
ports=(
  "${PLANNER_API_PORT:-18642}"
  "${PROJECT_MANAGER_API_PORT:-18648}"
  "${BUILDER_API_PORT:-18643}"
  "${REVIEWER_API_PORT:-18644}"
  "${RELEASE_API_PORT:-18645}"
  "${INCIDENT_API_PORT:-18646}"
  "${LEARNING_API_PORT:-18647}"
)

for index in "${!roles[@]}"; do
  role="${roles[$index]}"
  port="${ports[$index]}"
  curl --fail --silent --show-error "http://127.0.0.1:${port}/health" >/dev/null
  echo "hermes-${role}: live on 127.0.0.1:${port}"
done

echo "Liveness smoke test passed. Run an authenticated canary task per role before enabling automation."
