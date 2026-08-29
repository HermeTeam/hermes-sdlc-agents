# HermeTeam dashboard operations

This guide is for local operators and contributors running the simplified dashboard with Docker Compose. For the Russian guide, see [DASHBOARD_RU.md](DASHBOARD_RU.md).

## Purpose and MVP boundary

The dashboard is a current-state view of the seven Hermes role containers and their role-local orchestrator queues. It combines Docker container state with bounded queue snapshots and links to provider work items.

This MVP is strictly:

- local and single-host;
- read-only and stateless;
- unauthenticated;
- based on Docker Compose, the existing role-local SQLite queues, and five-second browser polling.

It has no dashboard database, history, audit trail, users, authentication, RBAC, control actions, transcript or log viewer, native Hermes dashboard proxy, WebSocket/SSE stream, or Kubernetes/multi-host dashboard deployment. Restarting the dashboard discards no owned state because it reads current facts again.

## Prerequisites

- Docker Engine with Docker Compose v2 and access to `/var/run/docker.sock` for the restricted proxy;
- the normal HermeTeam prerequisites and populated `.env` described in the project [README](../README.md#quick-start-with-docker-compose);
- Node.js 22.6 or later and npm only when running dashboard checks outside Docker;
- Python 3.11 or later and PyYAML when running repository validation.

Run commands below from the repository root.

## Start the dashboard

Bootstrap and validate the normal role configuration first:

```bash
scripts/bootstrap.sh
scripts/validate.sh
docker compose up --build -d
```

Open <http://127.0.0.1:9130>. The default Compose topology publishes only this central dashboard port, fixed to host loopback. The Docker socket proxy and role status endpoints stay on the private `hermes-control` network.

To select another local port, set `HERMETEAM_DASHBOARD_PORT` in `.env` or for one command:

```bash
HERMETEAM_DASHBOARD_PORT=9131 docker compose up --build -d
```

The address remains `127.0.0.1`; there is intentionally no host-bind setting.

Check process health and the aggregate API:

```bash
curl --fail http://127.0.0.1:9130/health
curl --fail http://127.0.0.1:9130/api/overview
docker compose ps
```

`/health` proves only that the dashboard process can respond. Use `/api/overview` and the page to inspect dependency state.

## Optional local diagnostics

The secure default does not publish role Hermes APIs or native role dashboards. Enable their loopback-only mappings explicitly with the debug override:

```bash
docker compose -f compose.yaml -f compose.debug.yaml up --build -d
```

The override publishes role APIs on `127.0.0.1:18642` through `127.0.0.1:18648` and native dashboards on `127.0.0.1:9119` through `127.0.0.1:9125`; see [compose.debug.yaml](../compose.debug.yaml) for the exact role mapping and optional port variables. Role APIs still require their configured Bearer keys. Native dashboards use their configured basic authentication.

The dashboard-specific status API is separate: every role wrapper serves `GET /health` and `GET /status` on internal port `8650` by default. `ORCHESTRATOR_STATUS_BIND` and `ORCHESTRATOR_STATUS_PORT` configure that private listener. It is not published by either Compose file. The central dashboard reaches canonical services such as `hermes-planner:8650` over `hermes-control`.

Each role container has `hermeteam.agent=true` and a unique `hermeteam.role` label. The dashboard selects only these seven labeled containers. The restricted Docker proxy also stays private, permits container list/inspect reads, and denies `POST` and unrelated Docker API sections. The dashboard container never mounts the Docker socket.

## Refresh and status semantics

The browser polls every five seconds, pauses polling while the page is hidden, and refreshes immediately when it becomes visible. Manual refresh is available. During a refresh, the last successful view remains visible. A failed refresh marks that retained view stale; it does not turn old data into a new snapshot.

`partial` means at least one Docker or role-status source failed or exceeded its timeout. Other successful roles remain visible. A partial result is usable but incomplete.

Docker state and agent state are independent:

| Docker state            | Meaning                                                                  |
| ----------------------- | ------------------------------------------------------------------------ |
| `RUNNING`               | Container is running and healthy, or has no health result after startup. |
| `STARTING`              | Docker health check is starting.                                         |
| `UNHEALTHY`             | Container runs but its health check fails.                               |
| `RESTARTING` / `PAUSED` | Docker reports that lifecycle state.                                     |
| `STOPPED`               | Container exists but is created, exited, or dead.                        |
| `MISSING`               | No container has the expected role label.                                |
| `UNKNOWN`               | Docker data is unsupported or contradictory.                             |

| Agent state   | Meaning                                                                                                 |
| ------------- | ------------------------------------------------------------------------------------------------------- |
| `UNAVAILABLE` | Container is missing/stopped/unhealthy/restarting, or a running role status API cannot be read.         |
| `BLOCKED`     | The readable queue has a blocked or failed item.                                                        |
| `WORKING`     | At least one assignment is active.                                                                      |
| `QUEUED`      | At least one assignment is due.                                                                         |
| `WAITING`     | Work exists only as a delayed retry.                                                                    |
| `DISABLED`    | The orchestrator is disabled and no higher-priority condition applies.                                  |
| `IDLE`        | A running role has a readable empty current queue.                                                      |
| `UNKNOWN`     | Container or queue data cannot support a known state; this includes starting/paused/unknown containers. |

A running container does not imply a working agent.

## Troubleshooting

| Symptom                                        | Check and action                                                                                                                                                                                                  |
| ---------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Role is `MISSING`                              | Run `docker compose ps -a`; confirm the service exists and retains its canonical `hermeteam.role` label. Recreate that service if it was removed.                                                                 |
| Role is `STOPPED`                              | Inspect `docker compose ps -a` and `docker compose logs <service>`; correct the role failure, then run `docker compose start <service>` or `docker compose up -d <service>`.                                      |
| Role is `UNHEALTHY`                            | Inspect the role health check and `docker compose logs <service>`. The displayed agent state remains unavailable until Docker health recovers.                                                                    |
| Agent is `UNAVAILABLE` while Docker is running | Check `docker compose logs <service>` for status-server startup/configuration failure. Verify the role and dashboard share `hermes-control` and use internal port `8650`.                                         |
| Source reports `sqlite_busy`                   | The read-only status request could not safely read SQLite. Wait for the next poll. If persistent, stop concurrent/manual writers and inspect the role runtime; do not point two role replicas at one `/opt/data`. |
| Queue looks briefly stale                      | The immutable SQLite reader creates no WAL sidecars and can observe a slightly stale snapshot during a concurrent write. Wait for the next five-second poll.                                                      |
| Docker state is unavailable for all roles      | Run `scripts/test-docker-socket-proxy.sh`, inspect `docker compose logs docker-socket-proxy`, and confirm the host Docker socket exists and is accessible. Do not mount it into the dashboard as a workaround.    |
| Dashboard returns no page/API                  | Run `docker compose ps`, inspect `docker compose logs hermeteam-dashboard`, and test `/health`. Rebuild with `docker compose build --no-cache hermeteam-dashboard` if the image is stale.                         |
| Build fails                                    | Run `npm --prefix dashboard ci`, `npm --prefix dashboard run check`, and `npm --prefix dashboard run build` to isolate dependency, type, test, or bundle failures.                                                |
| Port is already allocated                      | Set an unused `HERMETEAM_DASHBOARD_PORT`, then recreate the dashboard. Debug ports have equivalent per-role overrides in `compose.debug.yaml`.                                                                    |
| Page shows partial or stale data               | Inspect the per-role source message and `/api/overview`; repair only that dependency. Other role cards intentionally remain available.                                                                            |

## Secure operating boundary

> **Warning:** Never expose this no-authentication MVP on a LAN, public interface, reverse proxy, or `0.0.0.0`. Loopback binding is a required security boundary, not a convenience default.

For access from another trusted machine, keep Compose unchanged and use an SSH tunnel or a trusted VPN that preserves an explicit local access boundary. For example, run this on the client:

```bash
ssh -N -L 9130:127.0.0.1:9130 operator@dashboard-host
```

Then use `http://127.0.0.1:9130` on the client. Do not add a dashboard Docker socket mount or publish the proxy/status ports. Dashboard responses intentionally exclude secrets, environment values, prompts, issue bodies, transcripts, logs, raw database rows, and raw upstream errors.

Any requirement for shared remote access, authentication/RBAC, history/audit, native Hermes drill-down, retained evidence, control actions, sub-five-second realtime updates, Kubernetes, or multi-host operation triggers migration to the full dashboard architecture rather than relaxing this MVP boundary.

## Restart, shutdown, and recovery

Restart only the stateless dashboard:

```bash
docker compose restart hermeteam-dashboard
```

Stop the stack without deleting role data volumes:

```bash
docker compose down
```

Start it again with `docker compose up --build -d`. No dashboard migration, backup, or restore is required. Do not add `--volumes` unless you intentionally want to delete the role-local state volumes as well.

## Development and release checks

Install exactly the locked dashboard dependency graph and run the normal checks:

```bash
npm --prefix dashboard ci
npm --prefix dashboard run check
npm --prefix dashboard run build
python3 -m unittest discover -s orchestrator/tests -p 'test*.py' -v
bash orchestrator/tests/test_wrapper_lifecycle.sh
scripts/validate.sh
scripts/test-docker-socket-proxy.sh
```

The production browser E2E suite is opt-in because it builds images and creates an isolated temporary Compose project:

```bash
npm --prefix dashboard run test:e2e
# Equivalent integration through the repository smoke entry point:
DASHBOARD_E2E=true scripts/smoke-test.sh
```

It requires Docker, Compose, the installed npm dependencies, and a supported local Chromium/Chrome executable. Its cleanup trap removes its containers, network, volumes, and probe. If a run is interrupted before cleanup, use the project name printed by Compose with `docker compose -p <project> down --volumes --remove-orphans`, then confirm with `docker ps -a` and `docker network ls`.

Render both supported operational modes without starting services:

```bash
docker compose config --quiet
docker compose -f compose.yaml -f compose.debug.yaml config --quiet
docker compose -f dashboard/tests/e2e/compose.e2e.yaml config --quiet
```

Run `npm audit` after `npm ci`. Record and assess every advisory against the production dependency path; do not apply an unreviewed breaking upgrade or claim a clean audit when transitive advisories remain.

## Known limitations

- Five-second polling can miss short intermediate states.
- Queue details are unavailable while a role is stopped.
- Immutable read-only SQLite access can be one poll behind a concurrent WAL-backed write.
- There is no global queue ordering, historical metric, audit trail, alert acknowledgement, native console drill-down, or multi-user access.
- The restricted Docker proxy remains a high-trust dependency and must stay private and digest-pinned.
- Dashboard base-image tags are version-pinned in the Dockerfile but are not locked to registry digests; repeat image verification when upgrading.
