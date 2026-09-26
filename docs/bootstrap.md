# HermeTeam local bootstrap guide

> **SMB mode:** For a single Safe Builder with a provider/model already supplied by a HermeTeam subscription, use [the separate SMB runtime](../smb/README.md) and `python3 scripts/smb-quickstart.py up`. The seven-role procedure below is the advanced/reference deployment; it is not the required first-run path for a team of 3–30 developers. SMB subscription issuance and GitHub App enrollment are prerequisites until the self-service onboarding phase is implemented.


Russian version: [bootstrap_ru.md](bootstrap_ru.md).

This guide describes a safe, repeatable local deployment of the current HermeTeam `master` branch. It separates the base AI SDLC runtime from optional observability and capability-governance canaries so operators can validate each layer before enabling automation.

## 1. What this bootstrap brings up

The full local canary stack consists of:

- seven isolated Hermes roles: Planner, Project Manager, Builder, Reviewer, Release, Incident, Learning;
- the local HermeTeam dashboard;
- role-local GitHub MCP access with separate credentials and exact tool allowlists;
- optional Builder Flight Recorder and Langfuse monitoring;
- optional Capability Gateway governance canary.

Keep the role-local orchestrator disabled during the initial bootstrap. Do not treat the Capability Gateway as a production enforcement boundary yet: in the current implementation Hermes still connects directly to the configured repository MCP endpoint, while the capability resolver/governance service is an opt-in canary.

## 2. Host prerequisites

Required:

```text
git
Docker Engine
Docker Compose v2
bash
curl
python3
pip
openssl
```

Repository validation also requires PyYAML:

```bash
python3 -m pip install pyyaml
```

Check the host:

```bash
docker --version
docker compose version
python3 --version
openssl version
```

The first build needs outbound access to Docker registries, GitHub, the configured LLM endpoint and the configured skills repository. `Dockerfile.orchestrator` downloads `supercronic` and installs the optional Langfuse SDK into the Hermes virtual environment.

## 3. Clone the repository

```bash
git clone https://github.com/HermeTeam/hermes-sdlc-agents.git
cd hermes-sdlc-agents
git checkout master
git pull
```

For a reproducible environment, pin a known commit or release after the first successful canary instead of continuously deploying the moving `master` branch.

## 4. Bootstrap local configuration

Run:

```bash
scripts/bootstrap.sh
```

The script creates `.env` from `.env.example`, sets mode `0600`, and generates the seven role-local `*_API_SERVER_KEY` values when `openssl` is available.

Review unresolved placeholders:

```bash
grep 'CHANGE_ME' .env
```

Replace every placeholder that belongs to an enabled integration before startup.

### Current dashboard password requirement

The current Compose file requires `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD`. If it is not already present in your local `.env`, add it explicitly:

```bash
printf '\nHERMES_DASHBOARD_BASIC_AUTH_PASSWORD=%s\n' \
  "$(openssl rand -hex 32)" >> .env
```

This credential protects the native per-role Hermes dashboards exposed only when the debug overlay is enabled. It is separate from the central HermeTeam dashboard.

## 5. Configure the Hermes image and LLM provider

For an initial local test, the default image may be used:

```dotenv
HERMES_IMAGE=nousresearch/hermes-agent:latest
```

After a successful canary, replace the mutable tag with an immutable image digest.

Configure an OpenAI-compatible model endpoint:

```dotenv
HERMES_MODEL_ID=<model-id>
HERMES_MODEL_BASE_URL=<openai-compatible-base-url>
OPENAI_API_KEY=<llm-api-key>
```

Review role-specific model overrides in `.env`. For example, the current defaults may specify dedicated Builder, Incident, or Learning models. Clear or replace an override if your provider does not expose that model.

## 6. Configure the target GitHub repository

The GitHub MVP uses direct provider API/MCP access and does not clone the target repository into Hermes containers.

Example:

```dotenv
REPOSITORY_ID=my-project
REPOSITORY_PROVIDER=github
REPOSITORY_ACCESS_MODE=github-direct-api-mcp
REPOSITORY_DEFAULT_BRANCH=main
REPOSITORY_CLONE_ALLOWED=false

GITHUB_API_BASE_URL=https://api.github.com
GITHUB_WEB_BASE_URL=https://github.com
GITHUB_OWNER=my-org
GITHUB_REPOSITORY=my-repo
GITHUB_REPOSITORY_FULL_NAME=my-org/my-repo
GITHUB_REPOSITORY_HTML_URL=https://github.com/my-org/my-repo
GITHUB_REPOSITORY_API_URL=https://api.github.com/repos/my-org/my-repo

GIT_PROVIDER_MCP_URL=https://api.githubcopilot.com/mcp/
```

Keep `REPOSITORY_CLONE_ALLOWED=false` for the direct API/MCP deployment mode.

## 7. Create separate GitHub credentials per role

Do not reuse one broad human PAT across roles. Use fine-grained credentials accepted by the official GitHub MCP endpoint, such as fine-grained PATs or GitHub App installation tokens.

Recommended minimum permissions are documented in [GIT_PROVIDER_INTEGRATION.md](GIT_PROVIDER_INTEGRATION.md). The current role model is approximately:

| Role | Minimum provider authority |
| --- | --- |
| Planner | Contents read, Issues read, Pull Requests read, Metadata read |
| Project Manager | Contents read, Issues read/write, Pull Requests read, Metadata read |
| Builder | Contents read/write, Pull Requests read/write, Actions read/write only if needed, Metadata read |
| Reviewer | Contents read, Pull Requests read/write for review/comments, Issues write if needed, Actions read |
| Release | Actions read, Metadata read |
| Incident | Issues read/write, Metadata read |
| Learning | Issues read/write, Pull Requests read, Contents read, Metadata read |

Set the role credentials:

```dotenv
PLANNER_GITHUB_MCP_TOKEN=...
PROJECT_MANAGER_GITHUB_MCP_TOKEN=...
BUILDER_GITHUB_MCP_TOKEN=...
REVIEWER_GITHUB_MCP_TOKEN=...
RELEASE_GITHUB_MCP_TOKEN=...
INCIDENT_GITHUB_MCP_TOKEN=...
LEARNING_GITHUB_MCP_TOKEN=...
```

Do not grant Hermes organization-admin, repository-admin, branch-protection mutation, merge, Kubernetes, cloud-admin, or runner-shell authority unless a later separately enforced integration explicitly requires it.

## 8. Keep automation disabled during bootstrap

Keep these values at their safe defaults:

```dotenv
ORCHESTRATOR_ENABLED=false
ORCHESTRATOR_APPLY_TRANSITIONS=false
ORCHESTRATOR_TRANSITION_COMMENT_ONLY=true
```

Configure the separate read-only discovery credentials if you intend to test the orchestrator later:

```dotenv
ORCHESTRATOR_PLANNER_GITHUB_TOKEN=...
ORCHESTRATOR_PROJECT_MANAGER_GITHUB_TOKEN=...
ORCHESTRATOR_BUILDER_GITHUB_TOKEN=...
ORCHESTRATOR_REVIEWER_GITHUB_TOKEN=...
ORCHESTRATOR_RELEASE_GITHUB_TOKEN=...
ORCHESTRATOR_INCIDENT_GITHUB_TOKEN=...
ORCHESTRATOR_LEARNING_GITHUB_TOKEN=...
```

These credentials are separate from the role MCP credentials.

## 9. Review optional MCP integrations

The role profiles contain additional MCP integrations. Configure only the ones you actually use. Examples include DuckDuckGo Search, PostgreSQL, MongoDB, Context7 and browser-oriented MCP servers.

If an integration is not needed, prefer disabling it in the corresponding role profile instead of leaving fake credentials and assuming it is harmless. Keep the active tool surface as small as possible.

## 10. Validate before starting containers

Run structural validation:

```bash
scripts/validate.sh
```

The validator checks role/profile structure, YAML, repository settings, exact GitHub MCP allowlists, policy/profile drift, security defaults and several role-specific invariants.

Render the base Compose configuration:

```bash
docker compose config --quiet
```

Render the debug configuration too:

```bash
docker compose \
  -f compose.yaml \
  -f compose.debug.yaml \
  config --quiet
```

Do not continue until both commands succeed.

## 11. Start low-risk roles first

For the first runtime canary, start the lower-risk roles and the central dashboard:

```bash
docker compose up -d --build \
  hermes-planner \
  hermes-reviewer \
  hermes-learning \
  hermeteam-dashboard
```

Check status:

```bash
docker compose ps
```

Inspect startup logs if needed:

```bash
docker compose logs --tail=100 hermes-planner
docker compose logs --tail=100 hermes-reviewer
docker compose logs --tail=100 hermes-learning
```

All started role containers should become healthy before continuing.

## 12. Verify the central HermeTeam dashboard

The secure default Compose publishes only the central dashboard on host loopback:

```text
http://127.0.0.1:9130
```

Check it directly:

```bash
curl -fsS http://127.0.0.1:9130/health
curl -fsS http://127.0.0.1:9130/api/overview
```

Do not change the dashboard bind address to `0.0.0.0`. For trusted remote access, keep the loopback binding and use an SSH tunnel or trusted VPN as described in [DASHBOARD.md](DASHBOARD.md).

## 13. Start all seven roles

After the first roles are healthy:

```bash
docker compose up -d --build
```

Then:

```bash
docker compose ps
```

The Compose limits allow substantial resources per agent. On a development laptop, bring roles up gradually if CPU or memory pressure becomes significant.

## 14. Enable the debug overlay for local smoke tests

The base Compose file intentionally does not publish role API ports. `scripts/smoke-test.sh` checks those loopback ports, so use the debug overlay for this step:

```bash
docker compose \
  -f compose.yaml \
  -f compose.debug.yaml \
  up -d --build

scripts/smoke-test.sh
```

The debug overlay publishes role APIs only on loopback:

| Role | API port |
| --- | ---: |
| Planner | 18642 |
| Builder | 18643 |
| Reviewer | 18644 |
| Release | 18645 |
| Incident | 18646 |
| Learning | 18647 |
| Project Manager | 18648 |

It also publishes the native Hermes role dashboards on loopback ports `9119` through `9125`.

Remove the debug overlay when it is no longer required.

## 15. Run negative security canaries before positive mutations

Before enabling any unattended automation, verify that forbidden actions fail without changing provider state.

Minimum negative canaries:

- Planner: request a source-code mutation;
- Builder: request a write to `main` or `master`;
- Builder: request a write to protected paths such as `.github/workflows/`;
- Builder: request a pull-request merge;
- Reviewer: request `push_files` or another repository mutation;
- Release: request `kubectl`, deployment, or production mutation;
- Incident: request an infrastructure mutation;
- Learning: request autonomous skill activation/publication.

Do not accept a model statement such as “I cannot do that” as proof. Verify the resulting GitHub/provider state and, where available, MCP/provider audit evidence.

Only after negative canaries pass should you run bounded positive canaries, such as Builder creating an `agent/*` branch and opening a pull request.

## 16. Optional: enable Flight Recorder and Langfuse

Configure Langfuse in the root `.env`:

```dotenv
HERMES_LANGFUSE_PUBLIC_KEY=pk-lf-...
HERMES_LANGFUSE_SECRET_KEY=sk-lf-...
HERMES_LANGFUSE_BASE_URL=https://cloud.langfuse.com
HERMES_LANGFUSE_ENV=development
HERMES_LANGFUSE_SAMPLE_RATE=1.0
HERMES_LANGFUSE_CAPTURE=sanitized

HERMETEAM_GATE_MODE=shadow
HERMETEAM_GATE_BLOCK_LEVEL=critical

LANGFUSE_MONITOR_WINDOW_MINUTES=60
LANGFUSE_MONITOR_TIMEOUT_MS=3000
```

Start with the observability overlay:

```bash
docker compose \
  -f compose.yaml \
  -f compose.observability.yaml \
  up -d --build
```

Keep `HERMETEAM_GATE_MODE=shadow` while collecting and calibrating real traces. The Builder writes structured intent/action events and exports LLM traces to Langfuse when configured; the HermeTeam dashboard can query Langfuse aggregate metrics server-side.

## 17. Optional: enable the Capability Gateway canary

Add the values documented in `capability_gateway/.env.example` to the root `.env`:

```dotenv
CAPABILITY_ADMIN_KEY=<long-random-secret>
DASHBOARD_GOVERNANCE_KEY=<different-long-random-secret>
CAPABILITY_MAX_AUTO_RISK=MEDIUM

CAPABILITY_JUDGE_BASE_URL=<openai-compatible-base-url>
CAPABILITY_JUDGE_API_KEY=<judge-key>
CAPABILITY_JUDGE_MODEL=<judge-model>
```

Generate separate governance secrets, for example:

```bash
openssl rand -hex 32
openssl rand -hex 32
```

Render the overlay before startup:

```bash
docker compose \
  -f compose.yaml \
  -f compose.capability-gateway.yaml \
  config --quiet
```

Start it:

```bash
docker compose \
  -f compose.yaml \
  -f compose.capability-gateway.yaml \
  up -d --build
```

For a combined observability + capability-governance canary:

```bash
docker compose \
  -f compose.yaml \
  -f compose.observability.yaml \
  -f compose.capability-gateway.yaml \
  up -d --build
```

The capability service stays on the private `hermes-control` network and is not host-published.

Check its health from inside the service container:

```bash
docker compose exec capability-gateway \
  python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8787/health').read().decode())"
```

The central dashboard governance UI can then show pending risky-tool requests and offers controls such as `Allow once`, tool exception, capability risk override and emergency stop.

### Current enforcement limitation

The Capability Gateway is currently a canary resolver/governance service, not yet a mandatory MCP execution boundary. Hermes role profiles still use `GIT_PROVIDER_MCP_URL` and role-specific `GIT_PROVIDER_MCP_TOKEN` directly. Therefore a governance decision or emergency stop in this canary must not be interpreted as a guaranteed block of every real provider mutation.

## 18. Enable the orchestrator only after canaries pass

Keep:

```dotenv
ORCHESTRATOR_ENABLED=false
```

until all of the following are true:

- role health is stable;
- exact MCP `tools/list` output has been checked for each role credential;
- negative role canaries pass;
- bounded positive canaries pass;
- provider state confirms the expected result;
- observability is sufficient to investigate a failed run.

Then follow the staged orchestrator rollout in [OPERATIONS.md](OPERATIONS.md): start with one low-risk role, run the orchestrator manually, verify SQLite deduplication, and only then enable periodic scheduling role by role.

## 19. Shutdown and recovery

Stop the stack without deleting role state:

```bash
docker compose down
```

Do not use `--volumes` unless you intentionally want to destroy role-local state.

Restart a single role or dashboard:

```bash
docker compose restart hermes-builder
docker compose restart hermeteam-dashboard
```

For an agent security incident, stop the affected role and revoke its provider/API credentials. Stopping a container alone is insufficient if a credential may have leaked. See [OPERATIONS.md](OPERATIONS.md).

## 20. Local deployment checklist

### Host

- [ ] Docker Engine works.
- [ ] Docker Compose v2 works.
- [ ] Python 3 and PyYAML are installed.
- [ ] `git`, `curl`, `openssl`, `bash` are available.
- [ ] Required outbound network access works.

### Configuration

- [ ] `scripts/bootstrap.sh` completed.
- [ ] `.env` is private and contains no unresolved required `CHANGE_ME` values.
- [ ] `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD` is set.
- [ ] LLM endpoint, model and key are correct.
- [ ] Target GitHub repository values are correct.
- [ ] `REPOSITORY_CLONE_ALLOWED=false`.
- [ ] Seven distinct role GitHub MCP credentials are configured.
- [ ] Orchestrator credentials are separate from MCP credentials.
- [ ] `ORCHESTRATOR_ENABLED=false` during initial validation.

### Static validation

- [ ] `scripts/validate.sh` passes.
- [ ] `docker compose config --quiet` passes.
- [ ] Debug overlay rendering passes.
- [ ] Optional overlay rendering passes before it is enabled.

### Runtime

- [ ] Low-risk roles become healthy first.
- [ ] All seven roles become healthy.
- [ ] Central dashboard is reachable only on loopback.
- [ ] `/health` and `/api/overview` respond.
- [ ] Debug overlay smoke test passes.

### Security canaries

- [ ] Planner mutation is denied/no-op.
- [ ] Builder protected-branch write is denied.
- [ ] Builder protected-path write is denied.
- [ ] Builder merge is unavailable/denied.
- [ ] Reviewer mutation is unavailable/denied.
- [ ] Release production mutation is unavailable/denied.
- [ ] Learning autonomous activation is unavailable/denied.
- [ ] Provider state is checked after every negative canary.

### Observability

- [ ] Langfuse credentials are configured if observability is enabled.
- [ ] Builder traces appear in Langfuse.
- [ ] HermeTeam dashboard can show Langfuse monitor data.
- [ ] Intent/action gate remains in `shadow` until calibrated.

### Capability Gateway

- [ ] `CAPABILITY_ADMIN_KEY` and `DASHBOARD_GOVERNANCE_KEY` are different.
- [ ] Judge endpoint is configured.
- [ ] Capability Gateway is healthy.
- [ ] Governance UI is reachable through the central dashboard.
- [ ] Operators understand that the current gateway is not yet a mandatory execution boundary.

### Automation

- [ ] Automation remains disabled until role canaries pass.
- [ ] The first orchestrator rollout is performed for one role only.
- [ ] Deduplication and retry behavior are verified before expanding rollout.

A successful initial local deployment is therefore:

```text
7 healthy Hermes roles
        +
local HermeTeam dashboard
        +
verified negative role canaries
        +
optional Builder Flight Recorder / Langfuse
        +
optional Capability Gateway governance canary
        +
ORCHESTRATOR_ENABLED=false
```

Only after this baseline is stable should unattended role-local automation be enabled.
