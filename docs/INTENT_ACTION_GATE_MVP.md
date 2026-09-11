# HermeTeam Intent + Action Gate MVP

## Goal

This MVP implements the smallest useful Flight Recorder / gate for the existing Hermes builder without introducing a separate Evidence platform or a network LLM proxy.

The user story is:

> As an operator, I want to see what the model proposed, compare it with the tool call Hermes actually attempted, assign a risk level, monitor the LLM runtime, and optionally stop critical actions before the tool executes.

The first canary is `hermes-builder` only.

## Architecture

```text
GitHub issue
    |
    v
Orchestrator -- session_id --> Hermes builder
                              |
                              | provider hooks
                              +------> Langfuse traces
                              |            |
                              |            +--> Metrics API v2
                              |                     |
                              |                     v
                              |             HermeTeam Dashboard
                              |             observations / latency /
                              |             tokens / cost / models
                              |
                              +------> HermeTeam Intent/Action plugin
                                          |
                                          +-- llm.request
                                          +-- llm.response
                                          +-- intent.proposed_action
                                          +-- action.requested
                                          +-- action.completed
                                          |
                                          +-- Docker log: HERMETEAM_EVENT ...
                                          +-- /opt/data/hermeteam/intent-action-events.jsonl
```

`session_id` is the MVP correlation key. The existing orchestrator already assigns it to the `/v1/runs` request and stores it beside the Hermes run, so this change does not add another trace-ID system.

## Why Hermes hooks instead of a separate LLM proxy

Hermes already exposes stable observer lifecycle hooks around provider requests and tool calls. Using them has three advantages for the first version:

1. no OpenAI streaming/protocol proxy to maintain;
2. model proposals and actual tool calls share Hermes correlation identifiers;
3. `pre_tool_call` is the last process-local point where a proposed action can be compared with the actual arguments and blocked in canary mode.

A future Secure GitHub Execution Corridor still requires an external MCP/action gateway. Hermes hooks are fail-open by design and therefore are not the final security boundary.

## Event model

The plugin emits JSON events with schema `hermeteam.intent-action.v1`.

### `llm.request`

Captures provider/model/request metadata and a bounded, secret-safe request representation. Message `content`, credentials and long text are omitted or hashed.

### `llm.response`

Captures response metadata, usage, finish reason and a bounded response representation. Full conversational analysis belongs in Langfuse rather than the local security log.

### `intent.proposed_action`

Extracted from model `tool_calls` / function-call output before Hermes dispatches the tool.

Fields include `session_id`, `turn_id`, `api_request_id`, `tool_call_id`, tool name, argument hash plus bounded arguments, category, risk (`low`, `medium`, `high`, `critical`) and deterministic reason codes.

### `action.requested`

Emitted immediately before the actual Hermes tool dispatch. The plugin compares the actual tool name and argument hash with the last model proposal. A mutation with no matching proposal, or changed arguments, is raised to at least `high` risk.

### `action.completed`

Emitted after tool completion with status, duration and a bounded/hash representation of the result.

## Modes

The plugin itself defaults to safe canary settings even without extra environment variables:

```text
HERMETEAM_GATE_MODE=shadow
HERMETEAM_GATE_BLOCK_LEVEL=critical
HERMETEAM_GATE_LOG_PATH=/opt/data/hermeteam/intent-action-events.jsonl
```

Modes:

- `record` — recorder only;
- `shadow` — recorder + risk classification, never blocks (default/recommended canary);
- `enforce` — `pre_tool_call` blocks actions at or above `HERMETEAM_GATE_BLOCK_LEVEL`.

Do not treat `enforce` as the final security perimeter. A plugin/hook failure is fail-open inside Hermes. Production enforcement belongs in the future external Action/MCP Gateway, where evidence/policy failure can fail closed before GitHub mutation.

## Initial deterministic risk classifier

The MVP deliberately does not add a second LLM controller yet. It establishes the data path first.

| Action | Initial risk |
| --- | --- |
| `get_*`, `list_*`, `search_*`, `read_*` | low |
| normal task-branch create/update/push | medium |
| protected path or `main`/`master`/production target | high |
| merge/deploy/release/destroy/permission/security-admin operations | critical |
| actual mutation not matching a model proposal | at least high |

Once real traces exist, an LLM intent/risk controller can be evaluated in **shadow** against these deterministic labels before it is allowed to influence execution.

## Langfuse tracing and monitoring

The builder profile enables Hermes' built-in `observability/langfuse` plugin. The managed image installs the optional `langfuse` SDK into Hermes' `/opt/hermes/.venv`.

For the canary, runtime observability variables are kept out of the validated role-secret contract. Put them in the project `.env` and start the builder and dashboard with `compose.observability.yaml`:

```dotenv
HERMETEAM_GATE_MODE=shadow
HERMETEAM_GATE_BLOCK_LEVEL=critical
HERMETEAM_GATE_LOG_PATH=/opt/data/hermeteam/intent-action-events.jsonl

HERMES_LANGFUSE_PUBLIC_KEY=pk-lf-...
HERMES_LANGFUSE_SECRET_KEY=sk-lf-...
HERMES_LANGFUSE_BASE_URL=https://cloud.langfuse.com
HERMES_LANGFUSE_ENV=development
HERMES_LANGFUSE_RELEASE=
HERMES_LANGFUSE_SAMPLE_RATE=1.0
HERMES_LANGFUSE_CAPTURE=sanitized

LANGFUSE_MONITOR_WINDOW_MINUTES=60
LANGFUSE_MONITOR_TIMEOUT_MS=3000
```

`HERMES_LANGFUSE_BASE_URL` can point either to Langfuse Cloud or to a self-hosted Langfuse v4 deployment. The dashboard monitor uses the current Metrics API v2 (`/api/public/v2/metrics`).

Without Langfuse keys, trace export is inert and the dashboard reports the Langfuse monitor as `unconfigured`; the HermeTeam JSONL recorder still works.

### HermeTeam dashboard monitor

The dashboard backend receives the Langfuse credentials through the Compose observability overlay and performs the API calls server-side. The browser receives only a normalized monitoring snapshot from:

```text
GET /api/langfuse-monitor
```

The UI currently shows a bounded rolling window with:

- observation count;
- p95 latency;
- total token usage;
- total estimated cost;
- top models by cost/observation volume;
- `ok / degraded / unconfigured` monitor state;
- a link to the configured Langfuse UI for detailed drill-down.

The monitor performs two bounded Metrics API queries (`row_limit=1` summary and `row_limit=8` model breakdown). Upstream error bodies are not returned to the browser. Langfuse public and secret keys never appear in the dashboard API response or rendered page.

Langfuse remains the detailed LLM/agent observability layer. The local HermeTeam event stream is intentionally smaller and oriented around intent/action matching. Neither layer assumes that a provider exposes private chain-of-thought; reasoning content is recorded only when the provider/Hermes observability surface actually provides it.

## Privacy and secrets

The local event recorder does **not** persist raw source bodies or common credential fields. Keys such as `content`, `token`, `authorization`, `password`, `secret` and `private_key` are omitted and hashed. Long strings are represented by size and SHA-256. Hermes' own observer payload is already sanitized before this plugin sees it.

Normal Hermes secret/PII redaction remains enabled in the builder profile. Langfuse monitor credentials exist only in the builder/dashboard server process environments when the observability overlay is enabled; they are never serialized into the browser contract.

## Run

Rebuild the managed image:

```bash
docker compose build hermes-builder
```

Start the normal builder canary; the local recorder works with its internal defaults:

```bash
docker compose up -d hermes-builder
```

To enable Langfuse tracing and the HermeTeam monitoring panel from `.env`, use the observability override for both services:

```bash
docker compose -f compose.yaml -f compose.observability.yaml up -d hermes-builder hermeteam-dashboard
```

Open the local HermeTeam dashboard at the configured loopback port (default `http://127.0.0.1:9130`). The Langfuse section refreshes every 15 seconds; runtime/queue state refreshes every 5 seconds.

Watch structured security events:

```bash
docker logs -f hermes-builder | grep HERMETEAM_EVENT
```

Or inspect the persistent role volume:

```bash
docker exec hermes-builder tail -f /opt/data/hermeteam/intent-action-events.jsonl
```

## Tests

Intent/action plugin tests:

```bash
sh scripts/test-intent-action-gate.sh
```

Dashboard monitor and UI tests are part of the existing dashboard check:

```bash
cd dashboard
npm run check
```

Coverage includes hook registration, risk classification, sensitive-content omission, LLM events, proposal/action matching, mismatch escalation, critical-action blocking, bounded Langfuse Metrics API queries, degraded/unconfigured states, server-side credential containment and monitoring UI rendering.

## Next increments

1. Run builder in `shadow` and collect real false-positive / false-negative cases plus Langfuse latency/cost baselines.
2. Add an optional LLM semantic intent/risk controller in shadow mode, using the same event schema.
3. Add intent/action risk scores and policy-result scores to Langfuse so they can be charted and alerted alongside cost/latency.
4. Surface the local intent/action event timeline in the HermeTeam dashboard and cross-link it to Langfuse traces.
5. Add GitHub before/after state verification for consequential repository mutations.
6. Move hard enforcement to the external MCP Action Gateway and keep Hermes-side hooks as recorder/advisory defense in depth.
7. Replace standing GitHub credentials with short-lived GitHub App installation tokens once the Action Gateway is mandatory.
