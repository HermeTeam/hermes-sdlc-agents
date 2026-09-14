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
9. If the agent explicitly requested an over-limit tool, return an approval request and recommend the safest sufficient alternative.
10. `emergency_stop` overrides every model/catalog result and returns no executable capability.

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

- one-time grant for one approval request/tool pair;
- permanent tool exception;
- risk-category override for a canonical capability;
- global emergency stop.

The red emergency stop must remain independent from the LLM judge and catalog availability.

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

Governance endpoints require:

```http
Authorization: Bearer $CAPABILITY_ADMIN_KEY
```

Available controls:

- `GET /v1/governance`
- `POST /v1/governance/allow-once`
- `POST /v1/governance/tool-exception`
- `POST /v1/governance/capability-risk`
- `POST /v1/governance/emergency-stop`

## Security rules

- Never auto-install or execute a newly discovered MCP server merely to inspect it.
- External registry/catalog metadata is untrusted input.
- Tool annotations such as `readOnlyHint`/`destructiveHint` are not authorization facts.
- A model classification may raise or add risk but must never bypass deterministic/server-side policy.
- Emergency stop is deny-all and must not depend on external services.
- Capability-level risk overrides change enforcement policy; they do **not** rewrite the immutable base assessment.
- Permanent exceptions must remain auditable. The dashboard integration must not expose mutation endpoints without a separate governance credential.

## Tests

The package intentionally uses only the Python standard library in this first slice:

```bash
python -m unittest discover -s capability_gateway/tests -v
```

## Next integration slice

1. Wire the capability gateway in front of MCP execution so the agent sees only resolver-approved tools.
2. Atomically consume one-time grants at the execution boundary.
3. Add dashboard governance UI:
   - allow once;
   - add tool exception;
   - lower/raise risk category for the canonical capability;
   - red **Deny all immediately** emergency-stop control.
4. Add a dashboard governance API protected by a credential separate from the existing read-only dashboard.
5. Add catalog trust/reputation inputs and cache/pinning so external catalog drift cannot silently change an approved tool.
