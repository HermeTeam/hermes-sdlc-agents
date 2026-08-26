#!/usr/bin/env sh
set -eu

DATA_DIR="${ORCHESTRATOR_DATA_DIR:-/opt/data/sdlc-orchestrator}"
ENV_FILE="${ORCHESTRATOR_ENV_FILE:-${DATA_DIR}/orchestrator.env}"
CRONTAB_FILE="${DATA_DIR}/crontab"
LOG_FILE="${ORCHESTRATOR_LOG_FILE:-${DATA_DIR}/orchestrator.log}"
RUN_ONCE="/opt/hermes-sdlc-orchestrator/bin/orchestrator-run-once.sh"
SCHEDULE="${ORCHESTRATOR_CRON_SCHEDULE:-*/5 * * * *}"
STARTUP_RUN_ENABLED="${ORCHESTRATOR_STARTUP_RUN_ENABLED:-true}"
STARTUP_HEALTH_URL="${ORCHESTRATOR_STARTUP_HEALTH_URL:-${ORCHESTRATOR_HERMES_URL:-http://127.0.0.1:8642}/health}"
STARTUP_WAIT_SECONDS="${ORCHESTRATOR_STARTUP_WAIT_SECONDS:-60}"
STARTUP_WAIT_INTERVAL_SECONDS="${ORCHESTRATOR_STARTUP_WAIT_INTERVAL_SECONDS:-2}"

apply_default_env() {
  name="$1"
  default_name="HERMES_DEFAULT_${name}"
  current_value="$(printenv "$name" 2>/dev/null || true)"
  default_value="$(printenv "$default_name" 2>/dev/null || true)"
  if [ -z "${current_value}" ] && [ -n "${default_value}" ]; then
    export "${name}=${default_value}"
  fi
}

for key in \
  HERMES_MODEL_ID \
  HERMES_MODEL_BASE_URL \
  HERMES_MODEL_OPENAI_API_KEY \
  HERMES_JSON_REPAIR_MODEL_ID \
  HERMES_JSON_REPAIR_MODEL_BASE_URL \
  HERMES_JSON_REPAIR_OPENAI_API_KEY \
  API_SERVER_KEY \
  API_SERVER_MODEL_NAME \
  ORCHESTRATOR_GITHUB_TOKEN \
  ORCHESTRATOR_GITLAB_TOKEN \
  BRAVE_API_KEY \
  CONTEXT7_DEFAULT_MINIMUM_TOKENS \
  MDB_MCP_CONNECTION_STRING \
  POSTGRES_MCP_CONNECTION_STRING; do
  apply_default_env "${key}"
done

if [ -n "${HERMES_MODEL_OPENAI_API_KEY:-}" ]; then
  export OPENAI_API_KEY="${HERMES_MODEL_OPENAI_API_KEY}"
fi

mkdir -p "${DATA_DIR}"
export HERMES_WORKSPACE_DIR="${HERMES_WORKSPACE_DIR:-/opt/data/workspace}"
mkdir -p "${HERMES_WORKSPACE_DIR}"
touch "${LOG_FILE}"
chmod 0700 "${DATA_DIR}"
chmod 0700 "${HERMES_WORKSPACE_DIR}" || true

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
  ORCHESTRATOR_MAX_ATTEMPTS_PER_ASSIGNMENT \
  ORCHESTRATOR_RETRY_DELAY_SECONDS \
  ORCHESTRATOR_RETRY_LOST_RUNS \
  ORCHESTRATOR_RETRY_TRANSIENT_FAILURES \
  ORCHESTRATOR_FINAL_RESPONSE_REPAIR_ENABLED \
  ORCHESTRATOR_FINAL_RESPONSE_MODEL_REPAIR_ENABLED \
  ORCHESTRATOR_FINAL_RESPONSE_REPAIR_MODEL \
  ORCHESTRATOR_FINAL_RESPONSE_REPAIR_TIMEOUT_SECONDS \
  ORCHESTRATOR_FINAL_RESPONSE_REPAIR_MAX_CHARS \
  HERMES_WORKSPACE_DIR \
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
startup_run_pid=""
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

log_message() {
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" >>"${LOG_FILE}"
}

wait_for_gateway() {
  if ! command -v curl >/dev/null 2>&1; then
    log_message '{"status":"NO_OP","reason":"startup scan skipped; curl unavailable for gateway health check"}'
    return 1
  fi

  waited=0
  while [ "${waited}" -le "${STARTUP_WAIT_SECONDS}" ]; do
    if curl -fsS "${STARTUP_HEALTH_URL}" >/dev/null 2>&1; then
      return 0
    fi
    sleep "${STARTUP_WAIT_INTERVAL_SECONDS}"
    waited=$((waited + STARTUP_WAIT_INTERVAL_SECONDS))
  done

  log_message '{"status":"NO_OP","reason":"startup scan skipped; gateway health check did not become ready"}'
  return 1
}

run_startup_orchestrator_once() {
  if [ "${STARTUP_RUN_ENABLED}" != "true" ]; then
    return 0
  fi
  if [ "${ORCHESTRATOR_ENABLED:-false}" != "true" ]; then
    return 0
  fi
  if ! wait_for_gateway; then
    return 0
  fi
  if "${RUN_ONCE}" >>"${LOG_FILE}" 2>&1; then
    log_message '{"status":"OK","reason":"startup orchestrator run completed"}'
  else
    status="$?"
    log_message "{\"status\":\"ERROR\",\"reason\":\"startup orchestrator run failed\",\"exit_code\":${status}}"
  fi
}

dashboard_enabled() {
  case "${HERMES_DASHBOARD:-}" in
    1|true|TRUE|True|yes|YES|Yes) return 0 ;;
    *) return 1 ;;
  esac
}

start_dashboard() {
  if ! dashboard_enabled; then
    return 0
  fi

  dashboard_host="${HERMES_DASHBOARD_HOST:-0.0.0.0}"
  dashboard_port="${HERMES_DASHBOARD_PORT:-9119}"
  hermes dashboard --host "${dashboard_host}" --port "${dashboard_port}" --no-open &
  dashboard_pid="$!"
}

stop_children() {
  if [ -n "${dashboard_pid:-}" ]; then
    kill -TERM "${dashboard_pid}" 2>/dev/null || true
  fi
  if [ -n "${hermes_pid:-}" ]; then
    kill -TERM "${hermes_pid}" 2>/dev/null || true
  fi
  if [ -n "${startup_run_pid:-}" ]; then
    kill -TERM "${startup_run_pid}" 2>/dev/null || true
  fi
  if [ -n "${cron_pid:-}" ]; then
    kill -TERM "${cron_pid}" 2>/dev/null || true
  fi
}

trap 'stop_children; wait; exit 143' INT TERM

start_scheduler
start_dashboard
hermes gateway run &
hermes_pid="$!"
run_startup_orchestrator_once &
startup_run_pid="$!"
set +e
wait "${hermes_pid}"
status="$?"
set -e
stop_children
wait 2>/dev/null || true
exit "${status}"
