#!/usr/bin/env bash
set -euo pipefail

bundle_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v hermes >/dev/null 2>&1; then
  echo "hermes CLI is required" >&2
  exit 1
fi

roles=(
  hermes-planner
  hermes-builder
  hermes-reviewer
  hermes-release
  hermes-incident
  hermes-learning
)

for role in "${roles[@]}"; do
  hermes profile install "${bundle_root}/profiles/${role}" --alias --yes
done

echo "Profiles installed. Fill each generated profile .env before first use."
echo "For hard isolation and enforceable roles, use compose.yaml instead of co-locating profiles."
