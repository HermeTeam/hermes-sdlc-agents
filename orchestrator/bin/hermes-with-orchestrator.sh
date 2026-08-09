#!/usr/bin/env sh
set -eu

DATA_DIR="${ORCHESTRATOR_DATA_DIR:-/opt/data/sdlc-orchestrator}"
ENV_FILE="${ORCHESTRATOR_ENV_FILE:-${DATA_DIR}/orchestrator.env}"
CRONTAB_FILE="${DATA_DIR}/crontab"
LOG_FILE="${ORCHESTRATOR_LOG_FILE:-${DATA_DIR}/orchestrator.log}"
RUN_ONCE="/opt/hermes-sdlc-orchestrator/bin/orchestrator-run-once.sh"
SCHEDULE="${ORCHESTRATOR_CRON_SCHEDULE:-*/5 * * * *}"

mkdir -p "${DATA_DIR}"
touch "${LOG_FILE}"
chmod 0700 "${DATA_DIR}"

write_env_var() {
  name="$1"
  value="$(printenv "$name" 2>/dev/null || true)"
  escaped="$(printf '%s' "${value}" | sed "s/'/'\\''/g")"
  printf "export %s='%s'\n" "${name}" "${escaped}" >>"${ENV_FILE}.tmp"
}

rm -f "${ENV_FILE}.tmp"
for key in \
  API_SERVER_KEY \
  ORCHESTRATOR_ENABLED \
  ORCHESTRATOR_ROLE \
  ORCHESTRATOR_PROVIDER \
  ORCHESTRATOR_DB_PATH \
  ORCHESTRATOR_LOCK_PATH \
  ORCHESTRATOR_HERMES_URL \
  ORCHESTRATOR_MAX_STARTS_PER_TICK \
  ORCHESTRATOR_RUN_TIMEOUT_SECONDS \
  ORCHESTRATOR_GITHUB_TOKEN \
  ORCHESTRATOR_GITLAB_TOKEN \
  REPOSITORY_ID \
  REPOSITORY_PROVIDER \
  GITHUB_API_BASE_URL \
  GITHUB_REPOSITORY_FULL_NAME \
  GITLAB_API_BASE_URL \
  GITLAB_PROJECT \
  PYTHONPATH
do
  write_env_var "${key}"
done
install -m 0600 "${ENV_FILE}.tmp" "${ENV_FILE}"
rm -f "${ENV_FILE}.tmp"

printf '%s %s\n' "${SCHEDULE}" "${RUN_ONCE}" >"${CRONTAB_FILE}"

cron_pid=""
start_scheduler() {
  if command -v supercronic >/dev/null 2>&1; then
    supercronic -passthrough-logs "${CRONTAB_FILE}" >>"${LOG_FILE}" 2>&1 &
    cron_pid="$!"
  elif command -v crond >/dev/null 2>&1; then
    cron_dir="${DATA_DIR}/cron"
    mkdir -p "${cron_dir}"
    cp "${CRONTAB_FILE}" "${cron_dir}/root"
    crond -f -l 8 -c "${cron_dir}" >>"${LOG_FILE}" 2>&1 &
    cron_pid="$!"
  else
    interval="${ORCHESTRATOR_FALLBACK_INTERVAL_SECONDS:-300}"
    while true; do "${RUN_ONCE}"; sleep "${interval}"; done >>"${LOG_FILE}" 2>&1 &
    cron_pid="$!"
  fi
}

stop_children() {
  if [ -n "${hermes_pid:-}" ]; then
    kill -TERM "${hermes_pid}" 2>/dev/null || true
  fi
  if [ -n "${cron_pid}" ]; then
    kill -TERM "${cron_pid}" 2>/dev/null || true
  fi
}

trap 'stop_children; wait; exit 143' INT TERM

start_scheduler
hermes gateway run &
hermes_pid="$!"
set +e
wait "${hermes_pid}"
status="$?"
set -e
if [ -n "${cron_pid}" ]; then
  kill -TERM "${cron_pid}" 2>/dev/null || true
  wait "${cron_pid}" 2>/dev/null || true
fi
exit "${status}"
