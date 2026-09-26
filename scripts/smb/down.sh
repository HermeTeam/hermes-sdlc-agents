#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"
docker compose --env-file .env.smb -f compose.smb.yaml down
echo "SMB runtime stopped. Persistent state and subscription/GitHub secrets retained."
