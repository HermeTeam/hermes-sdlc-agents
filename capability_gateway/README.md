# HermeTeam Capability Gateway MVP

This directory contains the first vertical slice of the HermeTeam least-privilege tool resolver.

## Product invariant

> An agent must not receive a more powerful tool when a lower-risk capability can satisfy the same intent.

The gateway is intentionally separate from the existing Hermes role prompts. Model behavior is not a security boundary.

## Current flow

1. Receive an agent intent and optionally a tool the agent requested.
2. If no tool list is supplied, discover inspected tools from an external MCP catalog (Glama adapter). The official MCP Registry adapter is also present for authoritative server discovery; official registry entries are not considered executable until concrete tool schemas are available from an inspector/catalog.
3. Send each concrete tool descriptor plus the intent to an OpenAI-compatible judge.
4. Normalize the tool into a vendor-neutral `canonical_capability` and classify `read`, `write`, `destructive`, `egress`, `credential_access`, `arbitrary_execution`, and `open_world` properties.
5. Apply deterministic risk weights. MCP self-declared annotations are weak evidence only and cannot lower risk.
6. Compare candidates. A lower-risk, no-more-privileged tool with equivalent intent fit dominates a more powerful alternative.
7. Hide dominated alternatives from the agent-facing result.
8. Filter tools above `CAPABILITY_MAX_AUTO_RISK` unless a human governance rule explicitly allows them.
9. If the agent explicitly requested an over-limit tool, persist an approval request and recommend the safest sufficient alternative.
10. The dashboard can approve that exact tool once, add it as a persistent exception, or lower the enforcement category for every tool normalized to the same canonical capability.
11. `emergency_stop` overrides every model/catalog result and returns no executable capability.

## Judge configuration

The MVP requires an OpenAI-compatible `/v1/chat/completions` endpoint:

```bash
export CAPABILITY_JUDGE_BASE_URL=https://llm-gateway.example
export CAPABILITY_JUDGE_API_KEY=...
export CAPABILITY_JUDGE_MODEL=...
```

The judge is mandatory. If it is unavailable or returns malformed JSON, resolution fails closed with `503 judge_unavailable`.

## Governance configuration

```bash
export CAPABILITY_MAX_AUTO_RISK=MEDIUM
export CAPABILITY_ADMIN_KEY='a-long-random-admin-secret-at-least-24-chars'
export CAPABILITY_GATEWAY_DB=/opt/data/capability-gateway.sqlite3
```

Persistent controls:

- pending risky-tool approval queue;
- one-time grant for one approval request/tool pair;
- permanent tool exception;
- risk-category override for a canonical capability;
- global emergency stop.

The red emergency stop is independent from the LLM judge and catalog availability.

## API

Agent-facing:

```http
POST /v1/resolve
Content-Type: application/json

{
  "intent": "read the latest production deployment status",
  "catalog_query": "deployment status",
  "requested_tool_id": "some-server:shell_exec"
}
```

Callers may instead pass already discovered concrete MCP tool descriptors in `tools`.

Gateway governance endpoints require:

```http
Authorization: Bearer $CAPABILITY_ADMIN_KEY
```

Available controls:

- `GET /v1/governance`
- `POST /v1/governance/allow-once`
- `POST /v1/governance/tool-exception`
- `POST /v1/governance/capability-risk`
- `POST /v1/governance/emergency-stop`

## Dashboard governance

The base dashboard remains read-only unless the optional capability-gateway overlay is enabled. When enabled, governance writes use two credentials:

- `CAPABILITY_ADMIN_KEY` stays server-side between the dashboard server and capability gateway;
- `DASHBOARD_GOVERNANCE_KEY` is the separate operator credential entered into the dashboard UI.

The dashboard exposes:

- the agent intent that caused the risky request;
- requested tool and canonical capability;
- requested risk category versus automatic ceiling;
- safer sufficient tool recommendation when one exists;
- **Allow once**;
- **Add tool exception**;
- **Set all `<canonical capability>` to `<allowed category>`**;
- red **Запретить все и немедленно** emergency stop.

## Canary Compose overlay

The base `compose.yaml` is intentionally unchanged. Enable this MVP as a canary overlay:

```bash
docker compose -f compose.yaml -f compose.capability-gateway.yaml up -d --build
```

Copy the required values from `capability_gateway/.env.example` into the root `.env` first.

The gateway is not published on a host port; it is reachable only through the private `hermes-control` network. The dashboard continues to be published on loopback only.

## Security rules

- Never auto-install or execute a newly discovered MCP server merely to inspect it.
- External registry/catalog metadata is untrusted input.
- Tool annotations such as `readOnlyHint`/`destructiveHint` are not authorization facts.
- A model classification may add risk semantics but must never bypass deterministic/server-side policy.
- Judge failure is fail-closed.
- Emergency stop is deny-all and must not depend on external services.
- Capability-level risk overrides change enforcement policy; they do **not** rewrite the immutable base assessment.
- Permanent exceptions and capability overrides remain visible in governance state.
- A one-time approval is conservative in this canary: it is consumed when the resolver exposes the approved risky tool. Production hardening should move atomic consumption to the actual execution boundary.

## Tests

The Python package intentionally uses only the standard library in this first slice:

```bash
python -m unittest discover -s capability_gateway/tests -v
```

Dashboard changes remain covered by the existing TypeScript typecheck/test commands once the branch runs in CI:

```bash
cd dashboard
npm run check
```

## Remaining before production enforcement

1. Put the capability gateway in the actual MCP execution path so agents can only invoke resolver-approved tools.
2. Move one-time grant consumption from resolver exposure to the downstream execution boundary and bind it to the exact tool invocation arguments.
3. Add catalog artifact pinning/cache/reputation so remote catalog drift cannot silently change an approved tool.
4. Add live fixture tests for registry/catalog schemas and an OpenAI-compatible judge fixture.
5. Add adversarial canaries: misleading `readOnlyHint`, tool schema rug-pull, judge outage, catalog outage, over-privileged shell alternative, stale one-time grant, and emergency-stop race.
