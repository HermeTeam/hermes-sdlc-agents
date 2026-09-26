#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"
python3 scripts/smb/doctor.py
docker compose --env-file .env.smb -f compose.smb.yaml config --quiet
docker compose --env-file .env.smb -f compose.smb.yaml up -d --build
bash scripts/smb/smoke.sh
