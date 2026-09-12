# HermeTeam — Safe AI SDLC with Hermes Agents

**HermeTeam is a reference implementation of Safe AI SDLC: a security-first approach to autonomous software development in which AI agents can plan, code, review and operate, while their identity, authority and consequential actions remain independently controlled.**

The project started as a practical multi-agent SDLC team built on Hermes Agent. That foundation remains central: Planner, Project Manager, Builder, Reviewer, Release, Incident and Learning roles perform real delivery work through separate profiles, containers, credentials and tool surfaces. As those agents gain more autonomy, HermeTeam adds the control plane needed to make that autonomy observable, bounded and governable.

> **More autonomy requires more control — not more trust.**

Russian version: [README_RU.md](README_RU.md).

## Safe AI SDLC

Traditional AI-assisted development usually evolves in one direction:

```text
more capable model
      ↓
more tools
      ↓
more permissions
      ↓
more autonomy
```

HermeTeam follows a different model:

```text
more capability
      +
more observability
      +
more constrained authority
      +
independent verification
      ↓
more safe autonomy
```

The approach is built around six principles:

1. **Separate identity and authority by role.** Planner, Builder, Reviewer, Release and other roles do not share one human identity or broad credential.
2. **Intent is not execution.** What the model proposes and what the runtime actually calls are treated as different security-relevant events.
3. **Observe before enforce.** Start with evidence and shadow-mode controls, then introduce blocking only where the real risk justifies it.
4. **The agent does not authorize itself.** Prompts and `SOUL.md` shape behavior; credentials, provider controls and policy determine authority.
5. **Automate reversible work; control consequential transitions.** Human approval belongs around merge, production, permission escalation and other high-impact boundaries — not every low-risk step.
6. **Verify outcomes, not only intentions.** A mature Safe AI SDLC system checks the state produced by execution, not only the model response or tool success flag.

## Architecture direction

HermeTeam evolves from a real AI SDLC runtime into a control plane for governed autonomy:

```text
GitHub Issue / Requirement
          │
          ▼
┌─────────────────────────────┐
│ AI SDLC Team                │
│ Planner · PM · Builder      │
│ Reviewer · Release          │
│ Incident · Learning         │
└─────────────┬───────────────┘
              │
              ▼
        Flight Recorder
   what did the agent see/do?
              │
              ▼
          Intent Risk
    what does it intend to do?
              │
              ▼
          Action Gate
 what is it actually executing?
              │
              ▼
       Authority Policy
     is this action allowed?
              │
              ▼
          GitHub / CI
              │
              ▼
        Verify Outcome
     what actually changed?
```

The current `master` branch implements the **AI SDLC foundation and defense-in-depth role controls**. Flight Recorder, intent/action correlation, runtime risk assessment and stronger inline enforcement are the next control-plane layers being developed and validated incrementally rather than assumed as already complete.

## What is implemented today

The repository provides a ready-to-run GitHub-first Hermes SDLC environment with:

- seven isolated Hermes Agent roles;
- separate profile/state per role;
- separate containers or Kubernetes Pods and separate inbound API keys;
- role-specific GitHub credentials;
- exact native GitHub MCP tool allowlists;
- canonical role/tool constraints in `policies/roles.yaml`;
- server-side OPA policy examples in `policies/mcp-policy.rego`;
- protected-path and branch-boundary controls;
- a role-local orchestrator with SQLite workflow state;
- Docker Compose and Kubernetes/Kustomize deployment;
- a shared read-only skills superset;
- structural validation and smoke tests;
- a local read-only dashboard for operational visibility.

Repositories are not mounted into agent containers in the GitHub MVP. Agents work through scoped provider API/MCP operations, and the Builder is intentionally bounded to `agent/*` branches and pull-request creation rather than merge or production authority.

## Core security decision

`SOUL.md` controls model behavior, but it is **not** a security boundary. `tools.include` reduces the visible official GitHub MCP surface, but final authorization must also be enforced by upstream credentials, branch protection, GitHub rulesets, CI rules and provider-side policy.

Permissions are therefore distributed across independent layers:

1. Separate Hermes profile/state per role.
2. Separate container or Pod and separate inbound API key.
3. Separate GitHub credential accepted by the official GitHub MCP Server per role.
4. Exact GitHub MCP native tool allowlist in `config.yaml`.
5. The same allowlist and argument constraints represented server-side through OPA or an equivalent policy engine.
6. Separate upstream GitHub identities/scopes per role.
7. Server-side branch protection, protected paths, approvals and immutable release candidates.
8. No Kubernetes service-account token mounted into agent Pods.
9. Shared skills mounted read-only; skill writes remain gated by human approval.

Hermes documentation separates profile isolation from sandboxing: a profile isolates state but does not by itself restrict the filesystem. Separate containers are recommended when different credentials, network segmentation and reduced blast radius are required. See [Profiles](https://hermes-agent.nousresearch.com/docs/user-guide/profiles/) and [Docker](https://hermes-agent.nousresearch.com/docs/user-guide/docker/).

## Roles

| Role | Allowed | Strictly excluded |
| --- | --- | --- |
| `hermes-planner` | GitHub repository/file/tree/search and issue reads | code write, branch/PR creation, deployment, production, skill mutation |
| `hermes-project-manager` | repository/file/tree/search and issue read/comment/create for PM artifacts, reports and flow governance | code write, branch/PR creation, merge, deployment, production, budget/access mutation, skill mutation |
| `hermes-builder` | repository read, `agent/*` branch creation, `push_files`, PR creation, Actions evidence | broad GitHub credentials, merge, protected branch, production, quality-gate mutation, skill mutation |
| `hermes-reviewer` | PR/file/Actions reads and issue/PR comments | author-branch mutation, merge, production, skill mutation |
| `hermes-release` | GitHub Actions read-only evidence for MVP | deployment mutation until native release/deployment tools are explicitly scoped |
| `hermes-incident` | GitHub issue read/comment for MVP | flags, runbooks, infrastructure operations, code, skill mutation |
| `hermes-learning` | issue read/comment/create for human-reviewed improvement proposals | independent activation/publication, direct docs/code/production write |

Exact allowed tool names live in both `profiles/*/config.yaml` and `policies/roles.yaml`. `scripts/validate.sh` fails if those lists drift.

## Safe autonomy boundary

The project is intentionally not designed around “trust the prompt”. It separates useful autonomous work from consequential authority.

For example, the Builder can:

```text
read repository context
create agent/* branch
write bounded changes
inspect CI evidence
open pull request
```

but it cannot own the irreversible transition:

```text
write main/master/release/*
merge pull request
change protected security/CI paths without an independent gate
use Kubernetes/cloud production credentials
```

This is the basic Safe AI SDLC rule:

> **The agent may propose an action. The agent must not decide whether it is authorized to perform it.**

## Repository API/MCP flow

In the GitHub MVP, Hermes agents connect to the official GitHub MCP endpoint using role-specific credentials and narrow native tool allowlists discovered through runtime `tools/list`.

For the Builder:

- no `REPO_DIR` and no writable `/workspace/repo`;
- no shared human PAT;
- changes go through native tools such as `create_branch`, `push_files` and `create_pull_request`;
- task branches use the `agent/<work-item-id>-` prefix;
- GitHub Pull Requests are the MVP change-request boundary;
- `PR_READY_FOR_REVIEW` is valid only after the required CI/workspace evidence exists.

If local checks are needed before opening a change request, run them in a separate ephemeral workspace worker or trusted CI with the same repository scopes. Hermes should receive typed status/evidence rather than a broad shell or production credential.

Detailed flow documentation:

- [Repository API/MCP Flow — English](docs/REPOSITORY_API_MCP_FLOW_EN.md)
- [Repository API/MCP Flow — Russian](docs/REPOSITORY_API_MCP_FLOW_RU.md)

## Role-local orchestrator

The repository includes a disabled-by-default cron orchestrator under `orchestrator/`. Each role container runs the same wrapper, discovers provider issues with its own read-only orchestrator token, deduplicates assignments in local SQLite and submits runs only to that container's local Hermes API.

Keep `ORCHESTRATOR_ENABLED=false` until canaries pass for one role at a time.

## Quick start

Requirements: Docker Engine with Compose v2, an OpenAI-compatible LLM gateway and GitHub credentials accepted by the official GitHub MCP Server.

```bash
cd hermes-sdlc-agents
scripts/bootstrap.sh
```

Then:

1. Pin `HERMES_IMAGE` to an immutable digest in `.env`.
2. Replace all `CHANGE_ME` values.
3. Configure distinct role-specific GitHub MCP tokens. Do not reuse one token across roles.
4. Keep repository MCP toolsets narrow and let each role expose only its exact allowlist.
5. Validate:

```bash
scripts/validate.sh
```

6. Start:

```bash
docker compose up -d
scripts/smoke-test.sh
```

The secure default Compose mode publishes only the local read-only central dashboard on loopback. Role APIs are not publicly exposed. For diagnostics, use the explicit loopback-only debug override:

```bash
docker compose -f compose.yaml -f compose.debug.yaml up -d
scripts/smoke-test.sh
```

## Repository structure

```text
hermes-sdlc-agents/
├── compose.yaml
├── compose.debug.yaml
├── dashboard/
├── orchestrator/
├── profiles/
│   └── hermes-*/
│       ├── distribution.yaml
│       ├── config.yaml
│       ├── SOUL.md
│       └── skills/
├── policies/
│   ├── roles.yaml
│   ├── mcp-policy.rego
│   └── protected-paths.txt
├── secrets/*.env.example
├── kubernetes/
├── kustomization.yaml
├── scripts/
└── docs/
```

## Roadmap: from AI SDLC to governed autonomy

The intended progression is deliberately incremental:

```text
01 OBSERVE  → Flight Recorder
02 ASSESS   → Intent / target / risk classification
03 CONTROL  → Intent ↔ actual action comparison and policy gate
04 VERIFY   → Observe resulting repository/production state
05 GOVERN   → Manage agent authority, grants, revocation and drift
```

The project should not jump directly to a giant governance platform. The preferred path is to observe real agent behavior first, validate controls in shadow/canary modes and only then put consequential mutations behind mandatory enforcement.

## Before enabling automation

- Run a negative canary for every role: ask Planner to change code, Builder to merge `main`, Release to run `kubectl`, Incident to enable a flag and Learning to activate a skill. Every request must finish without the forbidden mutation.
- Verify denial through provider/upstream evidence, not only the model response.
- Ensure `hermes-builder` cannot change protected paths without a separate server-side gate and human approval.
- Keep role credentials distinct and short-lived where the provider supports it.
- Pin image digests for production use.

## Documentation

- [Configuration reference](docs/CONFIGURATION_REFERENCE.md)
- [Git provider integration contract](docs/GIT_PROVIDER_INTEGRATION.md)
- [Security model](docs/SECURITY.md)
- [Operations runbook](docs/OPERATIONS.md)
- [Dashboard operations — English](docs/DASHBOARD.md)
- [Dashboard operations — Russian](docs/DASHBOARD_RU.md)
- [Repository API/MCP Flow — English](docs/REPOSITORY_API_MCP_FLOW_EN.md)
- [Repository API/MCP Flow — Russian](docs/REPOSITORY_API_MCP_FLOW_RU.md)
- [Official sources](docs/SOURCES.md)

## Positioning

HermeTeam is not another coding model and not merely a multi-agent demo. It is an attempt to define and implement **how autonomous AI software development should be structured when agents receive real tools and real authority**.

The AI SDLC team is the execution foundation. Safe AI SDLC is the approach. Flight Recorder, Intent Risk, Action Gate and authority governance are the control layers that let that execution become progressively more autonomous without surrendering control.
