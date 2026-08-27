#!/usr/bin/env bash
set -euo pipefail

bundle_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
project="hermes-proxy-smoke-$$"
network="${project}_hermes-control"
probe="${project}-probe"
proxy="hermes-docker-socket-proxy"

skip() {
  printf 'SKIP: docker socket proxy runtime smoke: %s\n' "$1"
  exit 0
}

command -v docker >/dev/null 2>&1 || skip "docker CLI is unavailable"
docker compose version >/dev/null 2>&1 || skip "Docker Compose v2 is unavailable"
docker info >/dev/null 2>&1 || skip "Docker daemon is unavailable"

cleanup() {
  docker rm -f "${probe}" >/dev/null 2>&1 || true
  docker compose --project-directory "${bundle_root}" -p "${project}" rm -sf docker-socket-proxy >/dev/null 2>&1 || true
  docker network rm "${network}" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

if ! docker compose --project-directory "${bundle_root}" -p "${project}" pull docker-socket-proxy >/dev/null 2>&1; then
  skip "pinned proxy image is not locally available and registry pull failed"
fi

docker compose --project-directory "${bundle_root}" -p "${project}" up -d --no-deps docker-socket-proxy >/dev/null

proxy_id="$(docker compose --project-directory "${bundle_root}" -p "${project}" ps -aq docker-socket-proxy)"
proxy_ip="$(docker inspect "${proxy_id}" --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')"
[[ -n "${proxy_ip}" ]] || { echo "FAIL: proxy has no isolated network address" >&2; exit 1; }

published="$(docker inspect "${proxy}" --format '{{json .NetworkSettings.Ports}}')"
[[ "${published}" == '{}' || "${published}" == '{"2375/tcp":null}' ]] || {
  printf 'FAIL: proxy publishes a host port: %s\n' "${published}" >&2
  exit 1
}

docker run -d --rm --name "${probe}" --network "${network}" --entrypoint sleep curlimages/curl:8.12.1 60 >/dev/null 2>&1 \
  || skip "curl probe image is unavailable"

request() {
  docker exec "${probe}" curl --connect-timeout 1 --max-time 2 --silent --show-error --output /tmp/body --write-out '%{http_code}' "$@"
}

for _ in $(seq 1 30); do
  code="$(request "http://${proxy_ip}:2375/containers/json?all=1" || true)"
  [[ "${code}" == "200" ]] && break
  sleep 0.2
done
[[ "${code:-}" == "200" ]] || { echo "FAIL: container list returned ${code:-no response}" >&2; exit 1; }

container_id="$(docker exec "${probe}" sh -c "sed -n 's/.*\"Id\":\"\([^\"]*\)\".*/\1/p' /tmp/body | head -n1")"
if [[ -n "${container_id}" ]]; then
  code="$(request "http://${proxy_ip}:2375/containers/${container_id}/json")"
  [[ "${code}" == "200" ]] || { echo "FAIL: container inspect returned ${code}" >&2; exit 1; }
else
  code="$(request "http://${proxy_ip}:2375/containers/hermes-proxy-deliberately-missing/json")"
  [[ "${code}" == "404" ]] || { echo "FAIL: authorized inspect semantics returned ${code}, expected 404" >&2; exit 1; }
fi

code="$(request --request POST "http://${proxy_ip}:2375/containers/hermes-proxy-deliberately-missing/start")"
[[ "${code}" == "403" ]] || { echo "FAIL: mutation route returned ${code}, expected 403" >&2; exit 1; }

for path in info events images/json volumes networks; do
  code="$(request "http://${proxy_ip}:2375/${path}")"
  [[ "${code}" == "403" ]] || { echo "FAIL: unrelated /${path} returned ${code}, expected 403" >&2; exit 1; }
done

echo "Docker socket proxy runtime smoke passed: list/inspect allowed; mutation and unrelated APIs denied; no host port."
