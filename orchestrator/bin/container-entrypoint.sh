#!/usr/bin/env sh
set -eu

orchestrator_dir=/opt/data/sdlc-orchestrator
env_file="${orchestrator_dir}/orchestrator.env"
cron_file="${orchestrator_dir}/crontab"
log_file="${ORCHESTRATOR_LOG_PATH:-${orchestrator_dir}/orchestrator.log}"

mkdir -p "${orchestrator_dir}"
umask 077
: > "${env_file}"

write_env() {
  name="$1"
  value="${2:-}"
  printf '%s=%s\n' "${name}" "$(printf '%s' "${value}" | sed "s/'/'\\''/g; s/.*/'&'/")" >> "${env_file}"
}

write_env API_SERVER_KEY "${API_SERVER_KEY:-}"
write_env ORCHESTRATOR_ENABLED "${ORCHESTRATOR_ENABLED:-false}"
write_env ORCHESTRATOR_ROLE "${ORCHESTRATOR_ROLE:-}"
write_env ORCHESTRATOR_PROVIDER "${ORCHESTRATOR_PROVIDER:-${REPOSITORY_PROVIDER:-github}}"
write_env ORCHESTRATOR_DB_PATH "${ORCHESTRATOR_DB_PATH:-/opt/data/sdlc-orchestrator/orchestrator.sqlite}"
write_env ORCHESTRATOR_LOCK_PATH "${ORCHESTRATOR_LOCK_PATH:-/opt/data/sdlc-orchestrator/run_once.lock}"
write_env ORCHESTRATOR_HERMES_URL "${ORCHESTRATOR_HERMES_URL:-http://127.0.0.1:8642}"
write_env ORCHESTRATOR_MAX_STARTS_PER_TICK "${ORCHESTRATOR_MAX_STARTS_PER_TICK:-1}"
write_env ORCHESTRATOR_RUN_TIMEOUT_SECONDS "${ORCHESTRATOR_RUN_TIMEOUT_SECONDS:-5400}"
write_env ORCHESTRATOR_GITHUB_TOKEN "${ORCHESTRATOR_GITHUB_TOKEN:-}"
write_env ORCHESTRATOR_GITLAB_TOKEN "${ORCHESTRATOR_GITLAB_TOKEN:-}"
write_env REPOSITORY_ID "${REPOSITORY_ID:-}"
write_env GITHUB_API_BASE_URL "${GITHUB_API_BASE_URL:-https://api.github.com}"
write_env GITHUB_REPOSITORY_FULL_NAME "${GITHUB_REPOSITORY_FULL_NAME:-}"
write_env GITLAB_API_BASE_URL "${GITLAB_API_BASE_URL:-https://gitlab.com/api/v4}"
write_env GITLAB_PROJECT_ID "${GITLAB_PROJECT_ID:-}"
write_env PYTHONPATH "${PYTHONPATH:-/opt/hermes-sdlc-orchestrator}"

chmod 0600 "${env_file}"
schedule="${ORCHESTRATOR_CRON_SCHEDULE:-*/5 * * * *}"
printf '%s %s\n' "${schedule}" "/opt/hermes-sdlc-orchestrator/bin/orchestrator-run-once.sh >> '${log_file}' 2>&1" > "${cron_file}"

supercronic "${cron_file}" &
cron_pid="$!"
hermes_pid=""

term() {
  if [ -n "${hermes_pid}" ]; then kill -TERM "${hermes_pid}" 2>/dev/null || true; fi
  kill -TERM "${cron_pid}" 2>/dev/null || true
}
trap term INT TERM

hermes gateway run &
hermes_pid="$!"
wait "${hermes_pid}"
status="$?"
kill -TERM "${cron_pid}" 2>/dev/null || true
wait "${cron_pid}" 2>/dev/null || true
exit "${status}"
