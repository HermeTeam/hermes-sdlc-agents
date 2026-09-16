# HermeTeam Capability Gateway

This package contains two related control-plane slices:

1. **least-privilege capability resolution** — choose a sufficient lower-risk MCP capability for an intent;
2. **dynamic request authority (Builder canary)** — place HermeTeam in the actual Builder MCP path and acquire GitHub provider authority server-side only after validating the exact invocation.

## Product invariants

> An agent must not receive a more powerful tool when a lower-risk capability can satisfy the same intent.

> An agent must not hold reusable provider authority when HermeTeam can acquire the minimum authority for one validated request on its behalf.

Model behavior is not a security boundary. MCP metadata and model-judge output are evidence; deterministic server-side policy and the execution gateway decide whether an actual invocation may proceed.

## Least-privilege resolver

`POST /v1/resolve`:

1. receives an intent and optional requested tool;
2. discovers inspected MCP tools when callers do not supply candidates;
3. uses an OpenAI-compatible judge to normalize tools into vendor-neutral canonical capabilities and semantic risk properties;
4. applies deterministic risk weights;
5. removes dominated alternatives;
6. applies `CAPABILITY_MAX_AUTO_RISK` plus governance overrides;
7. persists a human approval request when an explicitly requested tool exceeds the automatic risk ceiling.

The model judge cannot lower deterministic policy decisions. Catalog/judge failure is fail-closed for resolver requests.

## Dynamic request authority

Set:

```dotenv
CAPABILITY_EXECUTION_MODE=dynamic
```

and use `compose.dynamic-authority.yaml` for the current `hermes-builder` canary.

The Builder no longer talks directly to the GitHub MCP endpoint in this mode:

```text
Hermes Builder
      │ internal gateway key
      ▼
HermeTeam Capability / Action Gateway
      │ exact tools/call
      ├─ role/repository/branch/path validation
      ├─ canonical capability + deterministic risk
      ├─ AUTO / HUMAN / EXCEPTION / CAPABILITY_OVERRIDE authority
      ├─ exact args SHA-256
      ├─ one-shot TTL execution grant when required
      └─ GitHub App token broker
                 │ repo + minimal permission set
                 ▼
          GitHub MCP Server
```

The GitHub App private key and installation tokens exist only in `capability-gateway`. The Builder receives only `BUILDER_CAPABILITY_GATEWAY_KEY`, an internal HermeTeam credential.

See [Dynamic Request Authority](../docs/DYNAMIC_REQUEST_AUTHORITY.md) for setup and canary procedures.

## Exact execution grants

For an over-limit actual invocation, the gateway persists the approval scope:

- `agent_id`;
- `run_id` / MCP session fallback;
- exact `tool_id`;
- canonical capability;
- repository;
- branch/ref;
- SHA-256 of normalized tool arguments.

`Allow once` creates a short-lived execution grant bound to that tuple. It is consumed atomically immediately before the approved upstream request is released. Changing any argument creates a different hash and requires new authority.

The existing permanent tool exceptions and capability-risk overrides remain governance policy. They never bypass hard repository/branch/protected-path constraints.

## GitHub App token broker

For actual `tools/call`, HermeTeam maps deterministic capabilities to provider permissions, for example:

```text
repository.file.read       → contents:read
repository.files.modify    → contents:write
repository.pull_request.create → pull_requests:write
ci.workflow.read           → actions:read
ci.workflow.trigger        → actions:write
```

The broker requests an installation token narrowed to the configured repository and the required permission set. Tokens may be cached server-side briefly by repository + permission set; per-request authority remains the exact HermeTeam grant/policy decision because the provider token is never exposed to the agent.

## Governance

Persistent controls are stored in SQLite:

- pending resolver approvals;
- pending exact execution approvals;
- one-shot exact execution grants;
- permanent tool exceptions;
- canonical-capability risk overrides;
- global emergency stop.

The dashboard governance surface uses two credentials:

- `CAPABILITY_ADMIN_KEY` — server-side dashboard → capability gateway credential;
- `DASHBOARD_GOVERNANCE_KEY` — separate operator credential entered in the local dashboard UI.

The dashboard displays exact execution scope before `Allow once` when the request originated in the dynamic MCP path.

## Emergency stop

`emergency_stop` is independent of the model judge and catalog adapters.

In resolver-only mode it exposes no executable resolved capabilities. In dynamic Builder mode it also denies actual Builder MCP traffic before GitHub provider authority is acquired. This execution guarantee currently applies only to roles routed through the dynamic gateway.

## Canary Compose

Resolver/governance canary:

```bash
docker compose -f compose.yaml -f compose.capability-gateway.yaml up -d --build
```

Builder dynamic-authority canary:

```bash
docker compose \
  -f compose.yaml \
  -f compose.capability-gateway.yaml \
  -f compose.dynamic-authority.yaml \
  up -d --build capability-gateway hermes-builder hermeteam-dashboard
```

Copy required values from `capability_gateway/.env.example` to the root `.env` first. The gateway is private on `hermes-control` and is not host-published.

## Security rules

- Never auto-install/execute a newly discovered MCP server merely to inspect it.
- External catalog/registry metadata is untrusted input.
- MCP annotations are not authorization facts.
- Unknown Builder execution tools fail closed.
- Builder repository mutations are constrained to the configured repository and `agent/*` branches.
- Builder protected-path mutations are hard-denied in this canary.
- High-risk exact invocations require an unexpired matching human grant unless governance explicitly changes policy.
- A one-shot grant cannot be reused and cannot authorize changed arguments.
- GitHub App tokens and private keys must never be returned to agents or browser clients.
- Emergency stop is checked before provider token acquisition.

## Tests

Python capability/authority tests:

```bash
python -m unittest discover -s capability_gateway/tests -v
```

Dashboard checks:

```bash
cd dashboard
npm ci
npm run check
```

Pull requests run both in `.github/workflows/ci.yml`.

## Remaining production hardening

1. complete live GitHub App + remote GitHub MCP canaries;
2. remove the legacy Builder GitHub-token interpolation from base `compose.yaml` after the dynamic path is proven;
3. migrate all other roles from standing provider credentials;
4. propagate a stable Hermes `run_id` into every MCP request rather than relying on MCP session fallback;
5. add before/after GitHub state verification and execution outcome evidence;
6. pin/verify MCP tool schema identity against catalog/server drift;
7. add lifecycle retention/cleanup for consumed execution grants;
8. move role-local gateway authentication to workload identity/mTLS when multi-host deployment requires it.
