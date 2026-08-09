#!/usr/bin/env sh
set -eu

DATA_DIR="${ORCHESTRATOR_DATA_DIR:-/opt/data/sdlc-orchestrator}"
ENV_FILE="${ORCHESTRATOR_ENV_FILE:-${DATA_DIR}/orchestrator.env}"
LOG_FILE="${ORCHESTRATOR_LOG_FILE:-${DATA_DIR}/orchestrator.log}"

mkdir -p "${DATA_DIR}"

if [ -f "${ENV_FILE}" ]; then
  # shellcheck disable=SC1090
  . "${ENV_FILE}"
fi

if [ "${ORCHESTRATOR_ENABLED:-false}" != "true" ]; then
  message='{"status":"NO_OP","reason":"orchestrator disabled"}'
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${message}" >>"${LOG_FILE}"
  printf '%s\n' "${message}"
  exit 0
fi

export PYTHONPATH="${PYTHONPATH:-/opt/hermes-sdlc-orchestrator}"
output="$(python3 -m sdlc_orchestrator run-once 2>&1)" || status=$?
status="${status:-0}"
printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${output}" >>"${LOG_FILE}"
printf '%s\n' "${output}"
exit "${status}"
