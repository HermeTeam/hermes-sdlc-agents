# HermeTeam - Hermes-based SDLC AI Agents Team

A ready-to-run bundle of seven isolated Hermes Agent roles for controlled software delivery lifecycle (SDLC) automation. The bundle includes real `config.yaml` and `SOUL.md` files, Hermes profile distributions, Docker Compose, Kubernetes/Kustomize templates, a shared read-only skills superset, server-side policy examples for the official GitHub MCP Server MVP, bootstrap scripts, structural validation, and smoke tests.

Russian version: [README_RU.md](README_RU.md).

## Core architectural decision

`SOUL.md` controls model behavior, but it is not a security boundary. `tools.include` reduces the visible official GitHub MCP surface, but the final authorization decision must be repeated by GitHub token scopes, branch protection, GitHub rulesets, CI rules, and any provider-side OPA layer. Permissions are therefore enforced across several independent layers:

1. Separate Hermes profile/state per role.
2. Separate container or Pod and separate inbound API key.
3. Separate GitHub credential accepted by the official GitHub MCP Server per role.
4. Exact GitHub MCP native tool allowlist in `config.yaml`.
5. The same allowlist and argument constraints enforced server-side through OPA or an equivalent policy engine.
6. Separate upstream GitHub identities/scopes per role.
7. Server-side branch protection, protected paths, approvals, and immutable release candidates.
8. No Kubernetes service-account token mounted into agent Pods.
9. Shared skills are mounted read-only through `skills.external_dirs`; skill writes remain gated by human approval.

Hermes documentation separates profile isolation from sandboxing: a profile isolates state but does not, by itself, restrict the filesystem. Separate containers are recommended when different credentials, network segmentation, and reduced blast radius are required. See [Profiles](https://hermes-agent.nousresearch.com/docs/user-guide/profiles/) and [Docker](https://hermes-agent.nousresearch.com/docs/user-guide/docker/).

## Roles

| Role                     | Allowed                                                                                                                                                                   | Strictly excluded                                                                                                                |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `hermes-planner`         | GitHub repository/file/tree/search and issue reads                                                                                                                        | code write, branch/PR creation, deployment, production, skill mutation                                                           |
| `hermes-project-manager` | GitHub repository/file/tree/search and issue read/comment/create for BRD/PRD-aligned PM artifacts, weekly decision reports, flow metrics, and Funnel/Discovery governance | code write, branch/PR creation, merge, deployment, production, budget/access mutation, technical micromanagement, skill mutation |
| `hermes-builder`         | GitHub repository read, `agent/*` branch creation, `push_files`, PR creation, Actions evidence                                                                            | local checkout, broad GitHub credentials, merge, protected branch, production, quality-gate mutation, skill mutation             |
| `hermes-reviewer`        | PR/file/Actions reads and issue/PR comments                                                                                                                               | author-branch mutation, merge, production, skill mutation                                                                        |
| `hermes-release`         | GitHub Actions read-only evidence for MVP                                                                                                                                 | deployment mutation until native release/deployment tools are discovered and scoped                                              |
| `hermes-incident`        | GitHub issue read/comment for MVP                                                                                                                                         | flags, runbooks, infrastructure operations, code, skill mutation                                                                 |
| `hermes-learning`        | GitHub issue read/comment/create for human-reviewed improvement proposals                                                                                                 | independent activation/publication, direct docs/code/production write                                                            |

Exact allowed tool names are stored in both `profiles/*/config.yaml` and `policies/roles.yaml`. `scripts/validate.sh` fails if the lists drift.

## Repository structure

```text
hermes-sdlc-agents/
├── compose.yaml                  # one container per role
├── compose.debug.yaml            # opt-in loopback role diagnostics
├── dashboard/                    # stateless read-only local overview
├── kustomization.yaml            # Kubernetes deployment through Kustomize
├── profiles/
│   └── hermes-*/
│       ├── .gitignore            # excludes credentials and runtime state
│       ├── distribution.yaml     # Hermes profile distribution manifest
│       ├── config.yaml           # managed role config
│       ├── SOUL.md               # identity, process, stop conditions
│       └── skills/               # role-safe shared skills, including self-evolution
├── orchestrator/                  # role-local cron issue discovery and /v1/runs submitter
├── policies/
│   ├── roles.yaml                # canonical role/tool/constraint matrix
│   ├── mcp-policy.rego           # sample server-side OPA decision
│   └── protected-paths.txt       # quality/CI/prod paths for a separate gate
├── secrets/*.env.example         # optional per-container Compose/Kubernetes env overrides
├── docs/
│   ├── REPOSITORY_API_MCP_FLOW_EN.md
│   ├── REPOSITORY_API_MCP_FLOW_RU.md
│   ├── GIT_PROVIDER_INTEGRATION.md
│   ├── SECURITY.md
│   ├── OPERATIONS.md
│   ├── DASHBOARD.md
│   └── DASHBOARD_RU.md
├── kubernetes/
└── scripts/
```

## Shared skills superset

Each role enables the Hermes `skills` toolset and uses two external skill directories:

- `/etc/hermes/skills` — skills shipped with the specific role profile;
- `/opt/hermes-shared-skills/current` — shared read-only superset from `https://github.com/stanta/skills_superset/tree/main/skills`.

In Docker Compose, the `skills-superset-sync` service updates the `shared-skills` named volume from `SKILLS_SUPERSET_REPO_URL` / `SKILLS_SUPERSET_REF` before agents start. Agents wait for that service to complete and mount the volume read-only. In Kubernetes, each Pod uses the `sync-shared-skills` initContainer to clone the same repository into an `emptyDir`; the main container then sees the directory read-only.

This lets agents select relevant skills dynamically through `skills_list` / `skill_view`, but it does not extend the Git provider API/MCP allowlist. Skill mutations still require `skills.write_approval: true`; roles other than `hermes-learning` must submit skill improvements as handoffs/proposals rather than changing skills directly.

## Repository API/MCP flow

Repositories are not mounted into agent containers. In the GitHub MVP, Hermes agents connect directly to the official GitHub MCP endpoint through `GIT_PROVIDER_MCP_URL=https://api.githubcopilot.com/mcp/` and send `X-MCP-Toolsets: "repos,issues,pull_requests,actions,git,code_security,dependabot"`. Hermes sees only narrow allowlisted native GitHub MCP tools discovered with runtime `tools/list`; the header only enables server-side availability.

For the builder this means:

- no `REPO_DIR` and no `/workspace/repo`;
- no broad GitHub token in the agent container; Compose maps the role-specific `.env` token, for example `BUILDER_GITHUB_MCP_TOKEN`, into container-local `GIT_PROVIDER_MCP_TOKEN`;
- changes are submitted through native GitHub MCP tools such as `create_branch`, `push_files`, and `create_pull_request`;
- task branches always use the `agent/<work-item-id>-` prefix;
- GitHub Pull Requests are the GitHub MVP change request mechanism;
- `PR_READY_FOR_REVIEW` is valid only after CI/workspace evidence exists.

If a project needs local checks before opening a change request, run them in a separate ephemeral workspace worker or trusted CI with the same repository scopes. The worker may clone the repository, apply the patch, run allowlisted checks, and push the task branch through role-scoped credentials, but Hermes receives only typed status/evidence.

Detailed flow documentation:

- [Repository API/MCP Flow — English](docs/REPOSITORY_API_MCP_FLOW_EN.md)
- [Repository API/MCP Flow — Russian](docs/REPOSITORY_API_MCP_FLOW_RU.md)

## Role-local cron orchestrator

The bundle includes a disabled-by-default cron orchestrator under `orchestrator/`. Each role container runs the same wrapper, writes a minimal cron environment file under `/opt/data/sdlc-orchestrator/`, discovers provider issues with its own read-only `ORCHESTRATOR_GITHUB_TOKEN`, deduplicates assignments in local SQLite, and submits only to `http://127.0.0.1:8642/v1/runs` with that container's own `API_SERVER_KEY`.

Compose builds `Dockerfile.orchestrator` from the pinned `HERMES_IMAGE`, adds `supercronic`, and bind-mounts `./orchestrator` read-only for local iteration. Kubernetes expects the same orchestrator code baked into the `hermes-sdlc-agent-orchestrator` image. Keep `ORCHESTRATOR_ENABLED=false` until canaries pass for one role at a time.

## Quick start with Docker Compose

Requirements: Docker Engine with Compose v2, an OpenAI-compatible LLM gateway, and GitHub credentials accepted by the official GitHub MCP Server. Compose is intended for local/single-host runs; for production, restrict egress with a firewall/egress proxy or use the Kubernetes NetworkPolicy from this bundle.

```bash
cd hermes-sdlc-agents
scripts/bootstrap.sh
```

Then:

1. Pin `HERMES_IMAGE` to an immutable digest in `.env`.
2. Keep the `test-project/test-project` GitHub repository target in `.env.example` and keep `GIT_PROVIDER_MCP_URL=https://api.githubcopilot.com/mcp/` for the GitHub MVP.
3. Replace all `CHANGE_ME` values in `.env`, including role API keys, role-local read-only `ORCHESTRATOR_<ROLE>_GITHUB_TOKEN` values, and role-specific GitHub MCP tokens before enabling cron.
4. Set seven different GitHub MCP tokens in `.env`: `PLANNER_GITHUB_MCP_TOKEN`, `PROJECT_MANAGER_GITHUB_MCP_TOKEN`, `BUILDER_GITHUB_MCP_TOKEN`, `REVIEWER_GITHUB_MCP_TOKEN`, `RELEASE_GITHUB_MCP_TOKEN`, `INCIDENT_GITHUB_MCP_TOKEN`, and `LEARNING_GITHUB_MCP_TOKEN`. One token must not be reused across roles.
5. Optionally create `secrets/hermes-<role>.env` from the matching example to override container-local values for one role. Values in that file win over the centralized root `.env` for that container.
6. Keep the repository MCP `X-MCP-Toolsets` header at `repos,issues,pull_requests,actions,git,code_security,dependabot`; role isolation is still enforced by `tools.include` and role tokens.
7. Validate the configuration:

```bash
scripts/validate.sh
```

8. Start the stack:

```bash
docker compose up -d
scripts/smoke-test.sh
```

The default secure Compose mode publishes only the unauthenticated, read-only central dashboard at <http://127.0.0.1:9130>. Set `HERMETEAM_DASHBOARD_PORT` to change the local port; the host address remains fixed to loopback. Role APIs, native role dashboards, the restricted Docker proxy, and role status port `8650` are not published.

For local diagnostics, explicitly add the loopback-only debug override:

```bash
docker compose -f compose.yaml -f compose.debug.yaml up -d
scripts/smoke-test.sh
```

The override publishes these authenticated role APIs:

| Role            | URL                         |
| --------------- | --------------------------- |
| planner         | `http://127.0.0.1:18642/v1` |
| project-manager | `http://127.0.0.1:18648/v1` |
| builder         | `http://127.0.0.1:18643/v1` |
| reviewer        | `http://127.0.0.1:18644/v1` |
| release         | `http://127.0.0.1:18645/v1` |
| incident        | `http://127.0.0.1:18646/v1` |
| learning        | `http://127.0.0.1:18647/v1` |

The Hermes API requires a Bearer key and supports `/v1/responses`, `/v1/runs`, `/health`, and authenticated `/health/detailed`; see the official [API Server reference](https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server/).

The central dashboard has no authentication and must never be exposed on a LAN, public interface, or `0.0.0.0`. Use an SSH tunnel or trusted VPN for external access. It has no database, history, controls, logs/transcripts, or native Hermes dashboard proxy. See the [dashboard operations guide](docs/DASHBOARD.md) for state semantics, troubleshooting, secure access, shutdown/recovery, development checks, and E2E commands.

Planner canary example:

```bash
set -a
source .env
set +a
curl --fail http://127.0.0.1:18642/v1/responses \
  -H "Authorization: Bearer ${PLANNER_API_SERVER_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{"model":"hermes-planner","input":"Read REQ-123 and create only a draft spec; do not change code."}'
```

Do not pass the `provider` field in external requests: `direct_model_requests` is disabled in the configurations so clients cannot select a different provider/model route.

## Installing as local Hermes profiles

Each directory under `profiles/` is a Hermes profile distribution. For development, install them into an existing Hermes setup:

```bash
scripts/install-profiles.sh
```

Or install one role:

```bash
hermes profile install ./profiles/hermes-reviewer --alias --yes
```

This mode is convenient, but it does not provide strong OS/network isolation. Use separate containers/Pods for production. The distribution format is described in [Hermes Profile Distributions](https://hermes-agent.nousresearch.com/docs/user-guide/profile-distributions).

## Why config is mounted into `/etc/hermes`

Compose and Kubernetes set `HERMES_MANAGED_DIR=/etc/hermes` and mount role config read-only. Managed scope takes precedence over user `config.yaml`, so an agent cannot enable terminal or expand the MCP allowlist through a normal `hermes config set`. This is an additional control plane, not a standalone sandbox; final denials must remain on the MCP/upstream side. See [Managed Scope](https://hermes-agent.nousresearch.com/docs/user-guide/managed-scope).

## Required open-source control plane

The GitHub MVP does not use a separate repository gateway. Hermes roles connect directly to the official GitHub MCP Server. GitLab support is future work and requires a separate tool mapping. Capabilities outside GitHub repository, issue, PR, and Actions tools remain separate integrations or blocked for MVP:

- GitHub for repository/Pull Request/review and branch protection through the official GitHub MCP endpoint;
- OpenProject for work items/requirements;
- Backstage Catalog for services, owners, APIs, SLOs, and dependencies;
- Woodpecker CI, Tekton, or Jenkins for CI evidence;
- Semgrep, Gitleaks, Trivy, OSV-Scanner, OpenSSF Scorecard, SonarQube Community Build, and mutation tools for quality findings;
- Argo CD + Argo Rollouts for immutable candidate status, promote, and abort;
- Prometheus, Loki, Tempo, and OpenTelemetry for bounded telemetry queries;
- Unleash for feature flags through a separate future integration, not the GitHub MCP allowlist;
- AWX or Rundeck Community for approved, versioned runbooks through a separate future integration;
- OPA for authorization and argument-level policy;
- OpenBao/SOPS/External Secrets Operator for secret issuance and rotation.

Do not give Hermes a broad GitHub token, Kubernetes kubeconfig, Argo admin token, cloud credential, or runner shell. In the MVP, only a role-specific GitHub credential limited to allowlisted repository operations is acceptable.

## Before enabling automation

- Run a negative canary for every role: ask planner to change code, builder to merge `main`, release to run `kubectl`, incident to enable a flag, and learning to activate a skill. Every request must finish without a mutating operation.
- Verify denial through the provider MCP/upstream audit log, not only through the model response.
- Ensure `hermes-builder` cannot change any path from `policies/protected-paths.txt` through `push_files` without a separate server-side CI gate and human approval.
- Ensure tokens have distinct `sub`, `role`, and `jti`, TTL ≤ 1 hour, and audit links every tool call to a Hermes run/session/work item.
- Pin the image digest; `latest` remains only as a convenience value for the first local run.

More details:

- [Repository API/MCP Flow — English](docs/REPOSITORY_API_MCP_FLOW_EN.md)
- [Repository API/MCP Flow — Russian](docs/REPOSITORY_API_MCP_FLOW_RU.md)
- [Configuration reference](docs/CONFIGURATION_REFERENCE.md)
- [Git provider integration contract](docs/GIT_PROVIDER_INTEGRATION.md)
- [Security model](docs/SECURITY.md)
- [Operations runbook](docs/OPERATIONS.md)
- [Dashboard operations — English](docs/DASHBOARD.md)
- [Dashboard operations — Russian](docs/DASHBOARD_RU.md)
- [Official sources](docs/SOURCES.md)
