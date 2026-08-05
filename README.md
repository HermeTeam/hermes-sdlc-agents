# Hermes SDLC Agents

A ready-to-run bundle of six isolated Hermes Agent roles for controlled software delivery lifecycle (SDLC) automation. The bundle includes real `config.yaml` and `SOUL.md` files, Hermes profile distributions, Docker Compose, Kubernetes/Kustomize templates, a shared read-only skills superset, server-side MCP gateway policy examples, bootstrap scripts, structural validation, and smoke tests.

Russian version: [README_RU.md](README_RU.md).

## Core architectural decision

`SOUL.md` controls model behavior, but it is not a security boundary. `tools.include` reduces the visible MCP surface, but the final authorization decision must be repeated by the MCP gateway. Permissions are therefore enforced across several independent layers:

1. Separate Hermes profile/state per role.
2. Separate container or Pod and separate inbound API key.
3. Separate short-lived MCP token with a `role` claim.
4. Exact MCP tool allowlist in `config.yaml`.
5. The same allowlist and argument constraints enforced server-side through OPA or an equivalent policy engine.
6. Separate upstream service accounts held by the MCP gateway.
7. Server-side branch protection, protected paths, approvals, and immutable release candidates.
8. No Kubernetes service-account token mounted into agent Pods.
9. Shared skills are mounted read-only through `skills.external_dirs`; skill writes remain gated by human approval.

Hermes documentation separates profile isolation from sandboxing: a profile isolates state but does not, by itself, restrict the filesystem. Separate containers are recommended when different credentials, network segmentation, and reduced blast radius are required. See [Profiles](https://hermes-agent.nousresearch.com/docs/user-guide/profiles/) and [Docker](https://hermes-agent.nousresearch.com/docs/user-guide/docker/).

## Roles

| Role              | Allowed                                                                                            | Strictly excluded                                                                                                     |
| ----------------- | -------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `hermes-planner`  | requirements/code/catalog/skills read; `spec` and `plan` create/update                             | code write, branch/change request, deployment, production, skill mutation                                             |
| `hermes-builder`  | skills read, repository read, task branch, patch/change-set, CI/workspace evidence, change request | local checkout, GitHub/GitLab credentials, merge, protected branch, production, quality-gate mutation, skill mutation |
| `hermes-reviewer` | skills/change request/diff/tests/findings read; comments, approve/request changes                  | author-branch mutation, merge, production, skill mutation                                                             |
| `hermes-release`  | skills/CI/quality/SLO read; promote or abort an existing candidate                                 | arbitrary `kubectl`, code/config changes, direct traffic editing, skill mutation                                      |
| `hermes-incident` | skills/telemetry read; flag disable; approved runbook execute                                      | flag enable/retarget, arbitrary infrastructure operations, code, skill mutation                                       |
| `hermes-learning` | aggregated outcomes/docs/skills read; proposal/staged skill write                                  | independent activation/publication, direct docs/code/production write                                                 |

Exact allowed tool names are stored in both `profiles/*/config.yaml` and `policies/roles.yaml`. `scripts/validate.sh` fails if the lists drift.

## Repository structure

```text
hermes-sdlc-agents/
├── compose.yaml                  # one container per role
├── kustomization.yaml            # Kubernetes deployment through Kustomize
├── profiles/
│   └── hermes-*/
│       ├── .gitignore            # excludes credentials and runtime state
│       ├── distribution.yaml     # Hermes profile distribution manifest
│       ├── config.yaml           # managed role config
│       ├── SOUL.md               # identity, process, stop conditions
│       └── skills/               # role-safe shared skills, including self-evolution
├── policies/
│   ├── roles.yaml                # canonical role/tool/constraint matrix
│   ├── mcp-policy.rego           # sample server-side OPA decision
│   └── protected-paths.txt       # quality/CI/prod paths for a separate gate
├── secrets/*.env.example         # templates only; no secrets
├── docs/
│   ├── REPOSITORY_API_MCP_FLOW_EN.md
│   ├── REPOSITORY_API_MCP_FLOW_RU.md
│   ├── MCP_CONTRACT.md
│   ├── SECURITY.md
│   └── OPERATIONS.md
├── kubernetes/
└── scripts/
```

## Shared skills superset

Each role enables the Hermes `skills` toolset and uses two external skill directories:

- `/etc/hermes/skills` — skills shipped with the specific role profile;
- `/opt/hermes-shared-skills/current` — shared read-only superset from `https://github.com/stanta/skills_superset/tree/main/skills`.

In Docker Compose, the `skills-superset-sync` service updates the `shared-skills` named volume from `SKILLS_SUPERSET_REPO_URL` / `SKILLS_SUPERSET_REF` before agents start. Agents wait for that service to complete and mount the volume read-only. In Kubernetes, each Pod uses the `sync-shared-skills` initContainer to clone the same repository into an `emptyDir`; the main container then sees the directory read-only.

This lets agents select relevant skills dynamically through `skills_list` / `skill_view`, but it does not extend the SDLC MCP allowlist. Skill mutations still require `skills.write_approval: true`; roles other than `hermes-learning` must submit skill improvements as handoffs/proposals rather than changing skills directly.

## Repository API/MCP flow

Repositories are not mounted into agent containers. Access to GitHub, GitLab, Forgejo, or a provider MCP is performed only by the SDLC MCP gateway through a provider-neutral repository adapter. Hermes sees only narrow `repo_*` tools: read/tree/search, task branch, patch/commit, change request, review comments, and CI evidence.

For the builder this means:

- no `REPO_DIR` and no `/workspace/repo`;
- no GitHub/GitLab token in the agent container;
- changes are submitted as bounded patch/change-sets through `repo_apply_patch` / `repo_commit_changes`;
- task branches always use the `agent/<work-item-id>-` prefix;
- GitHub Pull Requests and GitLab Merge Requests are normalized as `change_request`;
- `PR_READY_FOR_REVIEW` is valid only after CI/workspace evidence exists.

If a project needs local checks before opening a change request, run them in a separate ephemeral workspace worker behind the SDLC MCP gateway. The worker may clone the repository, apply the patch, run allowlisted checks, and push the task branch through upstream credentials, but Hermes receives only typed status/evidence.

Detailed flow documentation:

- [Repository API/MCP Flow — English](docs/REPOSITORY_API_MCP_FLOW_EN.md)
- [Repository API/MCP Flow — Russian](docs/REPOSITORY_API_MCP_FLOW_RU.md)

## Quick start with Docker Compose

Requirements: Docker Engine with Compose v2, an OpenAI-compatible LLM gateway, and a Streamable HTTP SDLC MCP gateway with a repository adapter that follows `docs/MCP_CONTRACT.md`. Compose is intended for local/single-host runs; for production, restrict egress with a firewall/egress proxy or use the Kubernetes NetworkPolicy from this bundle.

```bash
cd hermes-sdlc-agents
scripts/bootstrap.sh
```

Then:

1. Pin `HERMES_IMAGE` to an immutable digest in `.env`.
2. Keep the `test-project/test-project` GitHub repository target in `.env.example` and replace `GITHUB_PROVIDER_TOKEN` in the real `.env` with a token used only by the SDLC MCP repository adapter.
3. Replace all `CHANGE_ME` values in every `secrets/hermes-*.env` file.
4. Issue six different MCP tokens; one token must not be reused across roles.
5. Validate the configuration:

```bash
scripts/validate.sh
```

6. Start the stack:

```bash
docker compose up -d
scripts/smoke-test.sh
```

By default, APIs are bound only to the host loopback interface:

| Role     | URL                         |
| -------- | --------------------------- |
| planner  | `http://127.0.0.1:18642/v1` |
| builder  | `http://127.0.0.1:18643/v1` |
| reviewer | `http://127.0.0.1:18644/v1` |
| release  | `http://127.0.0.1:18645/v1` |
| incident | `http://127.0.0.1:18646/v1` |
| learning | `http://127.0.0.1:18647/v1` |

The Hermes API requires a Bearer key and supports `/v1/responses`, `/v1/runs`, `/health`, and authenticated `/health/detailed`; see the official [API Server reference](https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server/).

Planner canary example:

```bash
set -a
source secrets/hermes-planner.env
set +a
curl --fail http://127.0.0.1:18642/v1/responses \
  -H "Authorization: Bearer ${API_SERVER_KEY}" \
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

The SDLC MCP gateway should be your thin typed facade. It can be built on top of:

- GitHub, GitLab, or Forgejo for repository/change request/review and branch protection through the SDLC MCP repository adapter;
- OpenProject for work items/requirements;
- Backstage Catalog for services, owners, APIs, SLOs, and dependencies;
- Woodpecker CI, Tekton, or Jenkins for CI evidence;
- Semgrep, Gitleaks, Trivy, OSV-Scanner, OpenSSF Scorecard, SonarQube Community Build, and mutation tools for quality findings;
- Argo CD + Argo Rollouts for immutable candidate status, promote, and abort;
- Prometheus, Loki, Tempo, and OpenTelemetry for bounded telemetry queries;
- Unleash for one-way `flags_disable`;
- AWX or Rundeck Community for approved, versioned runbooks;
- OPA for authorization and argument-level policy;
- OpenBao/SOPS/External Secrets Operator for secret issuance and rotation.

Do not give Hermes a direct GitHub/GitLab/Forgejo token, Kubernetes kubeconfig, Argo admin token, cloud credential, or runner shell. The MCP gateway stores upstream credentials and exposes only narrow operations to agents.

## Before enabling automation

- Run a negative canary for every role: ask planner to change code, builder to merge `main`, release to run `kubectl`, incident to enable a flag, and learning to activate a skill. Every request must finish without a mutating operation.
- Verify denial through the MCP/upstream audit log, not only through the model response.
- Ensure `hermes-builder` cannot change any path from `policies/protected-paths.txt` through `repo_apply_patch` / `repo_commit_changes` without a separate server-side CI gate and human approval.
- Ensure tokens have distinct `sub`, `role`, and `jti`, TTL ≤ 1 hour, and audit links every tool call to a Hermes run/session/work item.
- Pin the image digest; `latest` remains only as a convenience value for the first local run.

More details:

- [Repository API/MCP Flow — English](docs/REPOSITORY_API_MCP_FLOW_EN.md)
- [Repository API/MCP Flow — Russian](docs/REPOSITORY_API_MCP_FLOW_RU.md)
- [Configuration reference](docs/CONFIGURATION_REFERENCE.md)
- [MCP contract](docs/MCP_CONTRACT.md)
- [Security model](docs/SECURITY.md)
- [Operations runbook](docs/OPERATIONS.md)
- [Official sources](docs/SOURCES.md)
