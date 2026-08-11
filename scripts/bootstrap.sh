#!/usr/bin/env bash
set -euo pipefail

bundle_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -f "${bundle_root}/.env" ]]; then
  install -m 0600 "${bundle_root}/.env.example" "${bundle_root}/.env"
  if command -v openssl >/dev/null 2>&1; then
    for key in \
      PLANNER_API_SERVER_KEY \
      PROJECT_MANAGER_API_SERVER_KEY \
      BUILDER_API_SERVER_KEY \
      REVIEWER_API_SERVER_KEY \
      RELEASE_API_SERVER_KEY \
      INCIDENT_API_SERVER_KEY \
      LEARNING_API_SERVER_KEY; do
      api_key="$(openssl rand -hex 32)"
      sed -i.bak "s/^${key}=CHANGE_ME_GENERATED_BY_BOOTSTRAP$/${key}=${api_key}/" "${bundle_root}/.env"
      rm -f "${bundle_root}/.env.bak"
    done
  fi
  echo "Created ${bundle_root}/.env; pin HERMES_IMAGE before startup."
fi

echo "Bootstrap complete. Next: edit .env for Compose defaults; optionally create secrets/hermes-<role>.env for per-container overrides; then run scripts/validate.sh."
