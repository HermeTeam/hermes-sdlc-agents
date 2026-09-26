# HermeTeam Safe Builder — SMB runtime (Stage 1)

This is a **separate standalone Compose runtime**, not a seven-role `compose.yaml` overlay. It runs exactly one Hermes coding role (`hermes-builder`), private Capability Gateway in mandatory `dynamic` authority mode, loopback-only Dashboard, read-only Docker status proxy, and a pinned, minimal skills sync. No Planner, PM, Reviewer, Release, Incident, Learning or OpenHands containers are required.

## Subscription-managed AI (no provider choice)

The customer does **not** select Qwen, OpenAI, model IDs or API endpoints, and does **not** supply a vendor LLM key. The HermeTeam subscription system must first install an owner-only `runtime/smb/subscription.json` entitlement containing its *HermeTeam tenant gateway* endpoint, assigned model and scoped tenant access token. `scripts/smb-quickstart.py` consumes that binding; it never prompts for a model, vendor, or BYOK value. The Capability Gateway judge uses the same subscription gateway. This repository does **not** implement subscription billing, activation, issuance or token refresh; until the subscription system provides a current binding, startup fails closed. Avoid confusing Stage 1 runtime availability with the later 30-minute self-service wizard.

The binding contract (values below are placeholders, not real service addresses or credentials):

```json
{
  "schema_version": 1,
  "status": "active",
  "llm_base_url": "https://SUBSCRIPTION_GATEWAY.example/v1",
  "model_id": "subscription-assigned-model",
  "access_token": "SUBSCRIPTION_SCOPED_TOKEN"
}
```

The subscription agent, not the user-facing installer, writes this file with mode `0600`. Customer-facing documentation does not provide a `QWEN_API_KEY` field.

## GitHub App enrollment (Stage 1 prerequisite)

Before the future GitHub App wizard exists, the operator places `runtime/smb/installation.json` (mode `0600`) and `secrets/smb/github-app.pem` (mode `0600`). These are **not** seven agent PATs. The GitHub App must already be installed on the selected repository, with permissions appropriate for the bounded Builder operations.

```json
{
  "schema_version": 1,
  "repository": "example-org/example-repo",
  "default_branch": "main",
  "app_id": 123456,
  "installation_id": 12345678
}
```

Only the server-side Capability Gateway receives the private key. Builder connects with a generated, internal, distinct gateway key. The token broker mints repository/permission-scoped installation tokens *after* exact action authorization. Keep GitHub branch protection / rulesets independently enforced.

## Commands

```bash
python3 scripts/smb-quickstart.py init
python3 scripts/smb-quickstart.py check
python3 scripts/smb-quickstart.py up
python3 scripts/smb-quickstart.py status
python3 scripts/smb-quickstart.py down
```

`init` validates both provisioned bindings and produces a private, ignored `.env.smb` with generated internal role, gateway and governance keys; repeated calls preserve them. `check` renders only `compose.smb.yaml` without revealing values. `up` builds and starts the five-service stack and waits for health. The Dashboard remains `http://127.0.0.1:9130` only. `down` preserves volumes and evidence; it never implicitly performs `down --volumes`. Do not use `docker compose config` without `--quiet` on credential-bearing configs.

Builder's MCP profile includes **only** approved GitHub repository tools through the internal gateway. The pre-pinned `skills_superset` checkout supplies selected testing, debugging, reasoning and security skills as read-only resources. DevOps and architecture-design skills are for the operator only, not Builder.

## Security and current limitations

- A subscription-scoped gateway token reaches the Builder as its model API credential; it is **not** a vendor API key. Treat it as a secret and rotate it via subscription provisioning.
- There is no user-facing subscription provider selector, BYOK fallback, legacy direct GitHub token fallback, shared host filesystem access, public Dashboard bind, or unattended orchestration.
- This stage does **not** implement billing/activation, automatic GitHub App registration, durable token renewal or initial issue scheduling. Those belong to subsequent onboarding/operations work.
- Stage 1 is not declared production-ready until a real provisioned subscription, actual GitHub App installation, and independent provider-state security canaries pass.
