# Dynamic Request Authority — Builder canary

This document describes the first HermeTeam canary that replaces a long-lived Builder GitHub credential with **per-request HermeTeam authority plus server-side GitHub App installation tokens**.

## Security invariant

> The agent never receives provider authority. It receives permission to request one capability. HermeTeam validates the exact invocation, acquires the minimum provider authority server-side, executes on the agent's behalf, and never returns the GitHub token to the agent.

The important distinction is:

- **HermeTeam execution grant** — exact, short-lived, one-shot authority for one `agent/run/tool/repository/branch/args_hash` tuple;
- **GitHub App installation token** — provider credential narrowed to one repository and the minimal GitHub permission set required by that tool call.

GitHub permissions cannot express branch/path/exact-arguments restrictions. Those constraints are enforced by HermeTeam before an upstream MCP request is released.

## Current canary scope

Dynamic request authority is enabled for **`hermes-builder` only**. Other roles continue to use their current role-specific provider credentials until this path is proven with live canaries.

The Builder canary recognizes these GitHub MCP tools:

| Tool | Canonical capability | Base risk | GitHub permission |
| --- | --- | --- | --- |
| `get_file_contents` | `repository.file.read` | LOW | `contents:read` |
| `get_repository_tree` | `repository.tree.read` | LOW | `contents:read` |
| `search_code` | `repository.code.search` | LOW | `contents:read` |
| `create_branch` | `repository.branch.create` | MEDIUM | `contents:write` |
| `push_files` | `repository.files.modify` | MEDIUM | `contents:write` |
| `create_pull_request` | `repository.pull_request.create` | MEDIUM | `pull_requests:write` |
| `actions_run_trigger` | `ci.workflow.trigger` | HIGH | `actions:write` |
| `actions_get` / `actions_list` | `ci.workflow.read` | LOW | `actions:read` |
| `get_job_logs` | `ci.logs.read` | LOW | `actions:read` |

Unknown tools fail closed.

## Builder argument constraints

Before minting provider authority, HermeTeam verifies the actual `tools/call` arguments:

- `owner/repo` must equal `GITHUB_REPOSITORY_FULL_NAME`;
- Builder branch mutation must target `agent/*`;
- pull requests must use an `agent/*` head and `REPOSITORY_DEFAULT_BRANCH` as base;
- workflow dispatch must target an `agent/*` ref;
- paths listed in `policies/protected-paths.txt` are hard-denied for Builder mutation;
- the exact tool and normalized arguments are hashed with SHA-256.

Protected paths remain a hard boundary in this canary. Human `Allow once` does not override them; a separate trusted path is required for such changes.

## Human approval semantics

When the effective request risk exceeds `CAPABILITY_MAX_AUTO_RISK`, the first invocation is blocked and a pending approval is persisted with:

- agent ID;
- run/session ID;
- canonical capability;
- exact tool ID;
- repository;
- branch/ref;
- SHA-256 of normalized invocation arguments.

The dashboard shows this scope before the operator approves it.

`Allow once` creates an execution grant with a short TTL (`CAPABILITY_EXECUTION_GRANT_TTL_SECONDS`, default 60 seconds). The grant is consumed atomically immediately before the approved request is sent upstream. Any change to the arguments produces a different hash/request and requires a new approval.

If upstream execution fails after the grant has been consumed, a new human approval is required. This is intentionally conservative.

## Provider token model

The gateway creates a short-lived GitHub App installation token only after request authorization. Tokens are narrowed to:

- the configured repository;
- the permission set mapped from the actual tool call.

Provider tokens remain inside `capability-gateway`. They may be cached server-side for a short interval (default 300 seconds) by `repository + permission set`. This does **not** weaken per-request authority because the GitHub token is never exposed to Hermes and every `tools/call` still has to pass HermeTeam exact-request authorization.

MCP initialization/tool discovery may require a wider Builder permission union so GitHub can expose the configured tools. That discovery token is also server-side only. Actual `tools/call` requests use the minimum permission set shown above.

## GitHub App setup

Create a GitHub App installed only on the repository/repositories to be used by HermeTeam. For the Builder canary, grant no more than the permission superset required by the configured tools, typically:

- Contents: read/write;
- Pull requests: read/write;
- Actions: read/write if `actions_run_trigger` is enabled; otherwise read.

Do not grant Administration, organization administration, branch-protection mutation, or unrelated permissions.

Download the App private key and store it outside Git, for example:

```text
secrets/github-app-private-key.pem
```

`secrets/*.pem` is ignored by Git.

## Environment

Copy the dynamic authority variables from `capability_gateway/.env.example` into the root `.env` and replace all placeholders:

```dotenv
CAPABILITY_ADMIN_KEY=<random-32+-char-secret>
DASHBOARD_GOVERNANCE_KEY=<different-random-32+-char-secret>
CAPABILITY_MAX_AUTO_RISK=MEDIUM

CAPABILITY_JUDGE_BASE_URL=https://CHANGE_ME_QWEN_API_HOST/compatible-mode/v1
CAPABILITY_JUDGE_API_KEY=<qwen-api-key>
CAPABILITY_JUDGE_MODEL=qwen3.7-max

BUILDER_CAPABILITY_GATEWAY_KEY=<third-independent-random-secret>

GITHUB_APP_ID=<app-id>
GITHUB_APP_INSTALLATION_ID=<installation-id>
GITHUB_APP_PRIVATE_KEY_FILE=./secrets/github-app-private-key.pem

CAPABILITY_EXECUTION_GRANT_TTL_SECONDS=60
CAPABILITY_PROVIDER_TOKEN_CACHE_SECONDS=300
CAPABILITY_PROVIDER_TIMEOUT_SECONDS=10
CAPABILITY_UPSTREAM_TIMEOUT_SECONDS=180
```

Generate independent local secrets, for example:

```bash
openssl rand -hex 32
```

Do not reuse the dashboard governance key, gateway admin key, or Builder gateway key.

## Current Compose compatibility note

The base `compose.yaml` still contains the legacy required interpolation for `BUILDER_GITHUB_MCP_TOKEN`. During this Builder canary, keep a value present in the host `.env` so Compose can render the base file. **`compose.dynamic-authority.yaml` overrides the value injected into `hermes-builder` with `BUILDER_CAPABILITY_GATEWAY_KEY`; the legacy GitHub token is not passed to the Builder container in dynamic mode.**

After the canary is proven, the next cleanup is to remove this legacy Builder token requirement from the base Compose contract entirely.

Verify the effective environment before starting:

```bash
docker compose \
  -f compose.yaml \
  -f compose.capability-gateway.yaml \
  -f compose.dynamic-authority.yaml \
  config
```

Check that `hermes-builder` resolves to:

```text
GIT_PROVIDER_MCP_URL=http://capability-gateway:8787/mcp
```

and that no GitHub App private key is present in the Builder service.

## Start the canary

Keep the orchestrator disabled initially:

```dotenv
ORCHESTRATOR_ENABLED=false
```

Start the capability gateway, dashboard, and Builder:

```bash
docker compose \
  -f compose.yaml \
  -f compose.capability-gateway.yaml \
  -f compose.dynamic-authority.yaml \
  up -d --build capability-gateway hermes-builder hermeteam-dashboard
```

Inspect status:

```bash
docker compose \
  -f compose.yaml \
  -f compose.capability-gateway.yaml \
  -f compose.dynamic-authority.yaml \
  ps
```

The capability gateway is private to the `hermes-control` network and is not published to the host.

## Required canaries

Run these before enabling unattended Builder automation.

### Positive

- read a normal repository file;
- create an `agent/*` branch;
- push a non-protected file to `agent/*`;
- create a pull request from `agent/*` to the configured default branch;
- read Actions status/logs.

Confirm GitHub state, not only the model response.

### Negative

- attempt to write `main`, `master`, or any non-`agent/*` branch;
- attempt to write `.github/workflows/**`, `policies/**`, `CODEOWNERS`, or another protected path;
- target a repository different from `GITHUB_REPOSITORY_FULL_NAME`;
- call an unmapped/forbidden tool;
- retry a human-approved high-risk request with any changed argument;
- reuse a consumed one-shot grant;
- activate emergency stop and confirm no provider token is minted/execution occurs.

### Human approval

With `CAPABILITY_MAX_AUTO_RISK=MEDIUM`, `actions_run_trigger` is HIGH and should:

1. return `approval_required`;
2. appear in Risk Governance with exact scope and arguments hash;
3. execute once after `Allow once`;
4. require a new approval on replay or argument mutation.

## Emergency stop

In dynamic execution mode the red emergency stop is now in the actual Builder MCP path. When active, the gateway denies MCP execution before provider token acquisition.

This guarantee applies only to roles routed through the dynamic gateway. Roles still using direct provider credentials remain outside this kill switch until migrated.

## Verification and tests

Python authority tests:

```bash
python -m unittest discover -s capability_gateway/tests -v
```

Dashboard checks:

```bash
cd dashboard
npm ci
npm run check
```

The repository CI runs these checks on pull requests.

## Remaining hardening after Builder canary

The following are intentionally follow-on work:

1. remove the legacy `BUILDER_GITHUB_MCP_TOKEN` base-Compose requirement;
2. migrate Planner/Reviewer/PM/Release/Incident/Learning to the same authority path;
3. add live GitHub App + remote MCP fixture/canary coverage;
4. correlate Hermes run IDs explicitly into every MCP request instead of falling back to MCP session ID;
5. add before/after GitHub state verification and execution outcome records;
6. pin/verify MCP server/tool schema identity against schema drift;
7. add lifecycle cleanup/retention for consumed execution-grant records;
8. replace local role keys with workload identity/mTLS when multi-host deployment requires it.

Until those canaries pass, this feature should be treated as a **Builder dynamic-authority canary**, not as a production-complete multi-role authority plane.
