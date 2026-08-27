#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
wrapper="${repo_root}/orchestrator/bin/hermes-with-orchestrator.sh"
system_python="$(command -v python3)"

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

assert_contains() {
  local needle="$1"
  local file="$2"
  grep -Fqx -- "${needle}" "${file}" >/dev/null || fail "missing ${needle} in ${file}"
}

assert_line_prefix() {
  local prefix="$1"
  local file="$2"
  grep -F -- "${prefix}" "${file}" >/dev/null || fail "missing prefix ${prefix} in ${file}"
}

assert_absent() {
  local needle="$1"
  local file="$2"
  if grep -Fqx -- "${needle}" "${file}" >/dev/null; then
    fail "unexpected ${needle} in ${file}"
  fi
}

wait_for_file() {
  local file="$1"
  local attempts=0
  until [[ -s "${file}" ]]; do
    ((attempts += 1))
    ((attempts < 100)) || fail "timed out waiting for ${file}"
    sleep 0.05
  done
}

assert_dead() {
  local pid="$1"
  local attempts=0
  while kill -0 "${pid}" 2>/dev/null; do
    ((attempts += 1))
    ((attempts < 100)) || fail "process ${pid} is still alive"
    sleep 0.05
  done
}

make_fake_bin() {
  local bin="$1"
  mkdir -p "${bin}"

  cat >"${bin}/python3" <<'SH'
#!/usr/bin/env sh
set -eu
if [ "$1" != "-m" ] || [ "$2" != "sdlc_orchestrator.status_server" ]; then
  printf 'unexpected python invocation: %s %s\n' "$1" "$2" >&2
  exit 97
fi
printf 'status-server %s %s\n' "${ORCHESTRATOR_STATUS_BIND:-<default>}" "${ORCHESTRATOR_STATUS_PORT:-<default>}" >>"${TEST_LOG}"
printf '%s\n' "$$" >"${STATUS_PID_FILE}"
if [ "${STATUS_SERVER_MODE:-run}" = "fail" ]; then
  exit 23
fi
trap 'printf "status-server-stopped\\n" >>"${TEST_LOG}"; exit 0' TERM INT EXIT
while :; do sleep 1; done
SH

  cat >"${bin}/supercronic" <<'SH'
#!/usr/bin/env sh
set -eu
printf 'cron %s %s\n' "$1" "$2" >>"${TEST_LOG}"
printf '%s\n' "$$" >"${CRON_PID_FILE}"
trap 'printf "cron-stopped\\n" >>"${TEST_LOG}"; exit 0' TERM INT EXIT
while :; do sleep 1; done
SH

  cat >"${bin}/hermes" <<'SH'
#!/usr/bin/env sh
set -eu
printf 'hermes %s %s\n' "$1" "$2" >>"${TEST_LOG}"
case "$1 $2" in
  'dashboard --host')
    printf '%s\n' "$$" >"${DASHBOARD_PID_FILE}"
    ;;
  'gateway run')
    printf '%s\n' "$$" >"${GATEWAY_PID_FILE}"
    ;;
  *)
    exit 98
    ;;
esac
trap 'printf "hermes-stopped %s %s\\n" "$1" "$2" >>"${TEST_LOG}"; exit 0' TERM INT EXIT
while :; do sleep 1; done
SH
  chmod +x "${bin}/python3" "${bin}/supercronic" "${bin}/hermes"
}

run_lifecycle_case() {
  local signal="$1"
  local temporary_directory
  temporary_directory="$(mktemp -d)"
  make_fake_bin "${temporary_directory}/bin"
  : >"${temporary_directory}/events.log"

  env \
    PATH="${temporary_directory}/bin:${PATH}" \
    TEST_LOG="${temporary_directory}/events.log" \
    STATUS_PID_FILE="${temporary_directory}/status.pid" \
    CRON_PID_FILE="${temporary_directory}/cron.pid" \
    DASHBOARD_PID_FILE="${temporary_directory}/dashboard.pid" \
    GATEWAY_PID_FILE="${temporary_directory}/gateway.pid" \
    ORCHESTRATOR_DATA_DIR="${temporary_directory}/data" \
    ORCHESTRATOR_LOG_FILE="${temporary_directory}/wrapper.log" \
    HERMES_WORKSPACE_DIR="${temporary_directory}/workspace" \
    ORCHESTRATOR_STATUS_BIND="127.0.0.1" \
    ORCHESTRATOR_STATUS_PORT="18650" \
    ORCHESTRATOR_STARTUP_RUN_ENABLED=false \
    HERMES_DASHBOARD=true \
    "${system_python}" -c '
import signal
import subprocess
import sys

signal.signal(signal.SIGINT, signal.SIG_DFL)
signal.signal(signal.SIGTERM, signal.SIG_DFL)
process = subprocess.Popen(sys.argv[1:])
print(process.pid, flush=True)
raise SystemExit(process.wait())
' sh "${wrapper}" >"${temporary_directory}/wrapper.pid" &
  local launcher_pid="$!"
  wait_for_file "${temporary_directory}/wrapper.pid"
  local wrapper_pid
  wrapper_pid="$(<"${temporary_directory}/wrapper.pid")"

  wait_for_file "${temporary_directory}/status.pid"
  wait_for_file "${temporary_directory}/cron.pid"
  wait_for_file "${temporary_directory}/dashboard.pid"
  wait_for_file "${temporary_directory}/gateway.pid"
  assert_contains 'status-server 127.0.0.1 18650' "${temporary_directory}/events.log"
  assert_line_prefix 'cron -passthrough-logs ' "${temporary_directory}/events.log"
  assert_line_prefix 'hermes dashboard --host' "${temporary_directory}/events.log"
  assert_contains 'hermes gateway run' "${temporary_directory}/events.log"
  assert_contains "export ORCHESTRATOR_STATUS_BIND='127.0.0.1'" "${temporary_directory}/data/orchestrator.env"
  assert_contains "export ORCHESTRATOR_STATUS_PORT='18650'" "${temporary_directory}/data/orchestrator.env"
  [[ "$(grep -Fc 'status-server 127.0.0.1 18650' "${temporary_directory}/events.log")" -eq 1 ]] || fail 'status server started more than once'

  kill "-${signal}" "${wrapper_pid}"
  set +e
  wait "${launcher_pid}"
  local status="$?"
  set -e
  [[ "${status}" -eq 143 ]] || fail "wrapper returned ${status} after ${signal}"
  assert_dead "$(<"${temporary_directory}/status.pid")"
  assert_dead "$(<"${temporary_directory}/cron.pid")"
  assert_dead "$(<"${temporary_directory}/dashboard.pid")"
  assert_dead "$(<"${temporary_directory}/gateway.pid")"
  assert_contains 'status-server-stopped' "${temporary_directory}/events.log"
  rm -rf "${temporary_directory}"
}

test_early_server_failure_is_fail_closed() {
  local temporary_directory
  temporary_directory="$(mktemp -d)"
  make_fake_bin "${temporary_directory}/bin"
  : >"${temporary_directory}/events.log"

  set +e
  env PATH="${temporary_directory}/bin:${PATH}" \
    TEST_LOG="${temporary_directory}/events.log" \
    STATUS_PID_FILE="${temporary_directory}/status.pid" \
    CRON_PID_FILE="${temporary_directory}/cron.pid" \
    DASHBOARD_PID_FILE="${temporary_directory}/dashboard.pid" \
    GATEWAY_PID_FILE="${temporary_directory}/gateway.pid" \
    ORCHESTRATOR_DATA_DIR="${temporary_directory}/data" \
    ORCHESTRATOR_LOG_FILE="${temporary_directory}/wrapper.log" \
    HERMES_WORKSPACE_DIR="${temporary_directory}/workspace" \
    STATUS_SERVER_MODE=fail \
    ORCHESTRATOR_STARTUP_RUN_ENABLED=false \
    sh "${wrapper}"
  local status="$?"
  set -e
  [[ "${status}" -eq 23 ]] || fail "fail-closed wrapper returned ${status}"
  assert_contains 'status-server <default> <default>' "${temporary_directory}/events.log"
  if grep -F -- 'cron -passthrough-logs ' "${temporary_directory}/events.log" >/dev/null; then
    fail 'cron started after status startup failure'
  fi
  if grep -F -- 'hermes dashboard --host' "${temporary_directory}/events.log" >/dev/null; then
    fail 'dashboard started after status startup failure'
  fi
  assert_absent 'hermes gateway run' "${temporary_directory}/events.log"
  [[ ! -e "${temporary_directory}/cron.pid" ]] || fail 'cron started after status startup failure'
  [[ ! -e "${temporary_directory}/gateway.pid" ]] || fail 'gateway started after status startup failure'
  rm -rf "${temporary_directory}"
}

sh -n "${wrapper}"
run_lifecycle_case TERM
run_lifecycle_case INT
test_early_server_failure_is_fail_closed
printf 'wrapper lifecycle tests passed\n'
