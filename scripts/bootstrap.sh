#!/usr/bin/env bash
set -euo pipefail

bundle_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -f "${bundle_root}/.env" ]]; then
  install -m 0600 "${bundle_root}/.env.example" "${bundle_root}/.env"
  echo "Created ${bundle_root}/.env; pin HERMES_IMAGE before startup."
fi

for example in "${bundle_root}"/secrets/*.env.example; do
  target="${example%.example}"
  if [[ ! -f "${target}" ]]; then
    install -m 0600 "${example}" "${target}"
    if command -v openssl >/dev/null 2>&1; then
      api_key="$(openssl rand -hex 32)"
      sed -i.bak "s/^API_SERVER_KEY=.*/API_SERVER_KEY=${api_key}/" "${target}"
      rm -f "${target}.bak"
    fi
    echo "Created ${target}; replace every remaining CHANGE_ME value."
  fi
done

echo "Bootstrap complete. Next: edit .env and secrets/*.env, then run scripts/validate.sh."
