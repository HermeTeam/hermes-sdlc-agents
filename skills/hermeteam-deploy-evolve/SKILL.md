---
name: hermeteam-deploy-evolve
description: "Interactive evidence-driven deployment of HermeTeam with safe recovery branching and reviewed self-evolution."
version: 1.0.0
author: "HermeTeam"
license: "MIT"
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [hermeteam, deployment, docker, github, authority, canary, self-evolution]
    category: software-development
    related_skills: [hermes-agent-self-evolution]
  evolution:
    lineage_mode: dag
    active_skill_immutable: true
    promotion_requires_human_review: true
---

# HermeTeam Deploy & Evolve

Use this skill to deploy the current `HermeTeam/hermes-sdlc-agents` repository, prove security-sensitive behavior with evidence, recover through explicit branches, and turn verified deployment lessons into reviewed candidate updates or forks of this skill.

This is an **operator/deployment skill**. It does not grant host, GitHub, Docker, cloud, or repository authority. A normal HermeTeam role remains bound by its `SOUL.md`, `config.yaml`, provider credentials, approval policy, and server-side policy.

## Non-negotiable invariants

1. Inspect current repository state before acting; never assume a cached checklist matches `master`.
2. Effective code/configuration outranks stale prose documentation.
3. Never silently fall back from Builder Dynamic Authority to a standing Builder provider credential.
4. Run negative canaries before positive mutations.
5. A model refusal is not evidence; verify resulting provider state.
6. Keep unattended orchestration disabled until required gates pass.
7. Never expose or learn from secret values.
8. The active skill is immutable during a deployment session.
9. Learning creates a candidate patch/fork; it never self-approves, self-merges, self-publishes, or self-activates it.
10. No learned branch may weaken role separation, protected paths, branch constraints, exact-request approval, one-shot grants, credential isolation, emergency stop, or provider-state verification.

## Preferred architecture

Default deployment mode is `dynamic-authority`:

```text
Hermes Builder
   │ internal HermeTeam gateway credential
   ▼
Capability / Action Gateway
   ├─ canonical capability + deterministic risk
   ├─ repository / branch / protected-path checks
   ├─ exact normalized args hash
   ├─ AUTO / HUMAN decision
   ├─ one-shot execution grant
   └─ GitHub App token broker
              │ minimum repository + permission set
              ▼
         GitHub MCP
```

Dynamic request authority is currently a **Builder canary** unless current repository code proves broader coverage. Other roles may still use role-specific provider credentials.

## Source precedence

When repository sources disagree, use this order:

1. effective rendered Compose/configuration;
2. executable code and tests;
3. `profiles/*` and `policies/*`;
4. `docs/DYNAMIC_REQUEST_AUTHORITY.md`;
5. component READMEs;
6. `docs/bootstrap*.md`;
7. top-level README;
8. this skill.

If current behavior contradicts this skill, enter `repo-drift/<sha>`, block the affected step, derive the correct procedure from current sources, and create a candidate skill evolution after successful verification.

## Modes

| Mode | Use | Builder provider path |
|---|---|---|
| `baseline-readonly` | host/base-role diagnosis | Builder stopped |
| `dynamic-authority` | preferred local canary | Builder → Gateway → GitHub App → GitHub MCP |
| `dynamic+observability` | authority + Flight Recorder/Langfuse | same |
| `legacy-builder-canary` | explicit comparison only | direct role credential |

Never choose legacy mode automatically because GitHub App setup failed.

## Interactive protocol

At each phase:

1. auto-detect read-only facts;
2. show compact status;
3. run safe checks automatically when tools allow;
4. run reversible local deployment actions when deployment was explicitly requested;
5. ask one precise question only for missing credentials, external mutations, or consequential choices;
6. persist sanitized evidence/checkpoints when workspace writes are allowed.

Status format:

```text
[HermeTeam Deploy] PHASE 05/12 — STATIC VALIDATION
State: PASS | BLOCKED | DEGRADED | WAITING_FOR_HUMAN
Evidence: <sanitized evidence>
Branch: <decision branch>
Next: <one next action>
```

## Session workspace

Prefer ignored runtime state:

```text
runtime/hermeteam-deploy/<session-id>/
  state.yaml
  events.jsonl
  lessons.jsonl
  evidence/
  branches/
  evolution/
```

Use the templates shipped with this skill. Never persist tokens, passwords, secret keys, PEM bodies, or fully resolved secret-bearing Compose output.

## Action classes

- **A0 read-only:** versions, repository reads, `docker compose ... config --quiet`, health checks, unit tests. May run automatically.
- **A1 local reversible:** bootstrap local config, build/start/stop sandbox containers, generate local random secrets. May run when deployment is explicitly requested.
- **A2 bounded external mutation:** create sandbox `agent/*` branch, push canary file, open sandbox PR, configure GitHub App. Require explicit task authority or point-of-action confirmation.
- **A3 consequential:** merge, production deployment, organization administration, broad credential grant, disabling security controls, fleet-wide unattended automation. Never perform automatically; some remain prohibited regardless of approval.

## Secret safety

Do not use commands that print secrets, for example:

```text
cat .env
echo $TOKEN
unfiltered docker compose config
printing private key content
```

Record only presence/source metadata, for example:

```yaml
credential:
  name: BUILDER_CAPABILITY_GATEWAY_KEY
  present: true
  source: root-dotenv
  value: REDACTED
```

Redact bearer tokens, `*_KEY`, `*_TOKEN`, `*_PASSWORD`, `*_SECRET`, PEM bodies, and unnecessary identifiers before persisting logs or lessons.

# Deployment state machine

```text
00 DISCOVER
01 PIN_REPOSITORY
02 HOST_PRECHECK
03 BOOTSTRAP_CONFIG
04 CONFIGURE_TARGET
05 STATIC_VALIDATION
06 BASE_RUNTIME
07 ROLE_NEGATIVE_CANARIES
08 DYNAMIC_AUTHORITY
09 AUTHORITY_CANARIES
10 OBSERVABILITY
11 ORCHESTRATOR_CANARY
12 FINALIZE
   ↓
LEARN / PATCH / FORK / PROPOSE
```

A failed gate enters a named recovery branch. Never skip the failed gate.

## 00 — DISCOVER

Read current repository structure and relevant files, including:

```text
README*.md
docs/bootstrap*.md
docs/DYNAMIC_REQUEST_AUTHORITY.md
compose.yaml
compose.*.yaml
.env.example
capability_gateway/.env.example
.github/workflows/*
profiles/hermes-*/config.yaml
policies/roles.yaml
policies/protected-paths.txt
AGENTS.md
```

Determine:
- current SHA/version;
- role count;
- available overlays;
- whether Builder Dynamic Authority exists;
- whether authority coverage is Builder-only or broader;
- documentation/code drift relevant to deployment.

If contracts changed, branch `repo-drift/<sha>` and reconstruct affected later phases from current code.

## 01 — PIN_REPOSITORY

Check:

```bash
git status --short
git rev-parse HEAD
git branch --show-current
cat VERSION 2>/dev/null || true
```

Never destroy local changes. If dirty, branch `dirty-worktree` and ask whether to use the existing checkout or a fresh deployment checkout.

## 02 — HOST_PRECHECK

Check:

```bash
docker --version
docker compose version
docker info
git --version
python3 --version
curl --version
openssl version
python3 -c 'import yaml; print(yaml.__version__)'
```

Branches:
- missing PyYAML → `host/missing-pyyaml`;
- Docker daemon unavailable → `host/docker-daemon-unavailable`;
- resource pressure → `host/resource-constrained` and phase role startup.

Do not retry an unchanged failure more than twice.

## 03 — BOOTSTRAP_CONFIG

If `.env` is absent:

```bash
scripts/bootstrap.sh
```

Never overwrite an existing `.env` without explicit approval.

Ensure required native Hermes dashboard password exists without printing it. Check unresolved placeholder **names** only:

```bash
grep -n 'CHANGE_ME' .env || true
```

Keep:

```dotenv
ORCHESTRATOR_ENABLED=false
ORCHESTRATOR_APPLY_TRANSITIONS=false
ORCHESTRATOR_TRANSITION_COMMENT_ONLY=true
```

## 04 — CONFIGURE_TARGET

Default to a sandbox GitHub repository.

Required baseline:

```dotenv
REPOSITORY_PROVIDER=github
REPOSITORY_ACCESS_MODE=github-direct-api-mcp
REPOSITORY_CLONE_ALLOWED=false
```

For Dynamic Authority prepare separate values for:

```text
CAPABILITY_ADMIN_KEY
DASHBOARD_GOVERNANCE_KEY
BUILDER_CAPABILITY_GATEWAY_KEY
GITHUB_APP_ID
GITHUB_APP_INSTALLATION_ID
GITHUB_APP_PRIVATE_KEY_FILE
CAPABILITY_JUDGE_BASE_URL
CAPABILITY_JUDGE_API_KEY
CAPABILITY_JUDGE_MODEL
```

The three HermeTeam keys must be independent. GitHub App permissions must be the minimum superset required by mapped Builder tools; do not add repository/organization Administration just to make setup easier.

If GitHub App setup is unavailable, stop and ask whether to configure it or explicitly run legacy comparison mode. Never silently fall back.

## 05 — STATIC_VALIDATION

Run:

```bash
scripts/validate.sh
python3 -m unittest discover -s capability_gateway/tests -v
npm --prefix dashboard ci
npm --prefix dashboard run check
docker compose config --quiet
```

Render applicable overlays, at minimum when present:

```bash
docker compose -f compose.yaml -f compose.debug.yaml config --quiet

docker compose \
  -f compose.yaml \
  -f compose.capability-gateway.yaml \
  config --quiet

docker compose \
  -f compose.yaml \
  -f compose.capability-gateway.yaml \
  -f compose.dynamic-authority.yaml \
  config --quiet
```

If observability is selected, render that combination too.

Verify effective Builder facts without dumping secret values. Required expectation in dynamic mode:

```text
GIT_PROVIDER_MCP_URL=http://capability-gateway:8787/mcp
Builder has no GitHub App private-key secret
```

Never patch out a security check merely to make validation pass.

## 06 — BASE_RUNTIME

Prove lower-risk components without starting Builder on a direct credential:

```bash
docker compose up -d --build \
  hermes-planner \
  hermes-reviewer \
  hermes-learning \
  hermeteam-dashboard
```

Verify health and central dashboard on loopback only:

```bash
curl -fsS http://127.0.0.1:9130/health
curl -fsS http://127.0.0.1:9130/api/overview
```

For unhealthy roles use `role-startup/<role>/<fingerprint>` and bounded, sanitized logs.

## 07 — ROLE_NEGATIVE_CANARIES

Before positive mutations, verify at least:

```text
Planner  → source-code mutation denied/unavailable
Reviewer → repository mutation denied/unavailable
Release  → deploy/kubectl denied/unavailable
Incident → infrastructure mutation denied/unavailable
Learning → direct skill activation/publication denied/unavailable
```

For each canary capture expected decision and provider state before/after. If forbidden provider state changes, stop the role, rotate/revoke credentials when compromise is plausible, mark `BLOCKED_SECURITY`, and do not proceed.

## 08 — DYNAMIC_AUTHORITY

Start Builder behind the gateway:

```bash
docker compose \
  -f compose.yaml \
  -f compose.capability-gateway.yaml \
  -f compose.dynamic-authority.yaml \
  up -d --build capability-gateway hermes-builder hermeteam-dashboard
```

Then the full seven-role stack while preserving the overlay:

```bash
docker compose \
  -f compose.yaml \
  -f compose.capability-gateway.yaml \
  -f compose.dynamic-authority.yaml \
  up -d --build
```

Verify:
- Builder uses private Gateway MCP URL;
- Builder receives internal gateway auth, not GitHub provider private key;
- private key remains gateway-only;
- unknown tools fail closed;
- repository target is exact;
- mutations are limited to `agent/*`;
- protected paths hard-deny;
- emergency stop is checked before provider-token acquisition.

Any unverifiable assertion blocks security acceptance.

## 09 — AUTHORITY_CANARIES

### Negative Builder cases

Attempt and prove no provider mutation for:

```text
write main/master
write non-agent/*
modify .github/workflows/**
modify policies/**
modify CODEOWNERS
target another repository
unknown tool
changed args after Allow once
replay consumed one-shot grant
expired grant
```

### Positive bounded flow

Only after negatives pass:

```text
read file
→ create agent/<canary> branch
→ push non-protected canary file
→ create PR to configured default branch
→ read Actions status/logs
```

Verify real GitHub state.

### Human approval

For a request above `CAPABILITY_MAX_AUTO_RISK`, verify:
1. first invocation returns `approval_required`;
2. dashboard shows exact agent/run/tool/repo/ref/args hash;
3. `Allow once` authorizes exactly one matching request;
4. grant is consumed before upstream execution;
5. replay fails;
6. changed args require a new approval;
7. expired grant fails.

### Emergency stop

With explicit authority for the canary:
1. activate stop;
2. attempt Builder MCP action;
3. confirm denial before provider execution;
4. verify no provider-state mutation;
5. restore normal state only after evidence is recorded.

Do not extrapolate the Builder kill switch to roles still using direct provider credentials.

## 10 — OBSERVABILITY

Optional but recommended before unattended automation.

If selected, start the observability overlay together with Dynamic Authority and verify:
- Builder intent/action evidence;
- Langfuse traces/metrics when configured;
- dashboard monitoring;
- no secret exposure to browser APIs;
- sufficient evidence to reconstruct consequential runs.

Keep intent/action enforcement in shadow mode while calibrating unless current policy explicitly authorizes stronger enforcement.

## 11 — ORCHESTRATOR_CANARY

Enter only when all mandatory gates pass.

Enable conservatively:

```dotenv
ORCHESTRATOR_ENABLED=true
ORCHESTRATOR_MAX_STARTS_PER_TICK=1
ORCHESTRATOR_APPLY_TRANSITIONS=false
ORCHESTRATOR_TRANSITION_COMMENT_ONLY=true
```

First run one role manually:

```bash
docker compose exec <role-service> \
  /opt/hermes-sdlc-orchestrator/bin/orchestrator-run-once.sh
```

Verify one bounded assignment, SQLite deduplication, retry behavior, no duplicate execution, and expected final evidence. Periodic scheduling is a separate promotion decision.

Never claim that Immediate Start UI or automatic idle container shutdown exists unless current code proves it.

## 12 — FINALIZE

Preferred-mode success requires:

```text
7 healthy roles
central dashboard loopback-only
Builder routed through Capability Gateway
GitHub App authority remains server-side
role negative canaries PASS
Builder authority negative canaries PASS
bounded Builder PR flow PASS
one-shot approval PASS
emergency stop PASS
provider state verified
orchestrator disabled or explicitly single-role canary
```

Create sanitized deployment attestation with repo SHA, skill version, mode, gate results, evidence IDs, known limits, and evolution lessons.

# Recovery branches

Standard branches:

```text
repo-drift/<sha>
dirty-worktree
host/missing-pyyaml
host/docker-daemon-unavailable
host/resource-constrained
config/missing-required-variable
config/provider-model-mismatch
role-startup/<role>/<fingerprint>
gateway/judge-unavailable
gateway/github-app-unavailable
gateway/provider-timeout
authority/schema-drift
authority/unexpected-provider-mutation
observability/degraded
orchestrator/dedup-failure
```

Every recovery branch records trigger, sanitized evidence, attempted actions, preserved invariants, result, and phase to rejoin.

Limits:
- at most 2 identical retries without new evidence;
- at most 3 nested recovery branches per phase;
- never brute-force a policy/security deny.

# Self-learning and branching

Self-learning is evidence-driven skill evolution, not self-authorization.

## Create a lesson when

At least one is true:
- the same normalized failure appears in 2+ sessions;
- a workaround succeeds without weakening invariants;
- repository drift changes a deployment contract;
- a new service/overlay becomes required;
- this skill contains a false assumption;
- a human explicitly marks the observation reusable.

Do not learn from secret values, one ambiguous anecdote, transient outages without a reproducible condition, model preference, or privilege-widening workarounds.

## Lesson shape

```yaml
lesson:
  id: LES-<id>
  parent_skill: hermeteam-deploy-evolve@1.0.0
  repo_sha: <sha>
  phase: <phase>
  failure_fingerprint: <hash>
  observation: <sanitized fact>
  verified_workaround: <safe procedure>
  evidence_count: 2
  confidence: 0.0
  candidate_action: PATCH|FORK|DOC_ONLY|TEST_ONLY
```

## PATCH vs FORK

Use `PATCH` for a generally true correction to the base procedure.

Use `FORK` for conditional behavior such as Docker Desktop, air-gapped deployment, GitHub Enterprise, alternate provider, constrained laptop, or older HermeTeam release.

Do not turn the base skill into a large environment-specific conditional tree.

## Evolution DAG

Candidate metadata records parent, candidate version, branch, lesson IDs, evidence IDs, and status `PROPOSED_FOR_HUMAN_REVIEW`.

The active skill never changes in-place during the session.

## Candidate procedure

1. collect sanitized lessons;
2. choose PATCH/FORK/TEST_ONLY/DOC_ONLY;
3. produce the smallest candidate diff;
4. add regression cases for changed behavior;
5. compare security invariants to the parent;
6. run relevant static/evaluation checks;
7. write candidate under `runtime/.../evolution/`;
8. leave active skill unchanged;
9. route to human review.

Within normal HermeTeam roles:
- non-Learning roles hand off evidence to Learning;
- Learning creates proposal/diff only;
- Learning does not install, activate, publish, merge, or deploy the candidate.

An externally authorized developer/operator agent may create a review branch/PR only when authorized; it must not self-merge or self-activate the candidate.

## Candidate acceptance gates

Every candidate must preserve:

```text
no secret material
no weaker role separation
no broad new provider credential
no Dynamic Authority bypass
no weaker protected-path/branch rules
no removed negative canaries
no silent legacy Builder fallback
no weaker one-shot approval
no weaker emergency stop
reproducible evidence
regression coverage for changed branch
rollback defined
human review required
```

Recommended promotion evidence: two successful applicable deployment sessions, or one successful session plus a targeted regression fixture that reproduces the prior failure and proves the fix.

A specialized fork merges back only when its behavior becomes generally valid, regression coverage exists, and human review explicitly approves it. Never auto-merge evolution branches.

# Regression scenarios

Keep coverage for at least:

1. clean host + Dynamic Authority;
2. missing PyYAML;
3. Docker daemon unavailable;
4. dirty worktree;
5. missing native dashboard password;
6. Builder overlay points directly to GitHub MCP;
7. GitHub App key exposed to Builder;
8. protected-path mutation;
9. wrong repository target;
10. changed args after `Allow once`;
11. consumed grant replay;
12. emergency stop active;
13. judge unavailable;
14. provider timeout;
15. observability degraded;
16. orchestrator duplicate assignment;
17. repository drift changes authority/deployment contract.

Security denials must remain denials in every candidate version.

# Human handoff

When human action is required, use:

```text
Blocked at: <phase>
Need: <one exact action/decision>
Why: <security/dependency reason>
Safe default if no action: <what stays disabled>
Evidence: <sanitized IDs>
```

Never ask a vague "continue?" question.

# Rollback

For the full local canary, omit overlays not used:

```bash
docker compose \
  -f compose.yaml \
  -f compose.observability.yaml \
  -f compose.capability-gateway.yaml \
  -f compose.dynamic-authority.yaml \
  down
```

Do not use `--volumes` unless state destruction is explicitly requested.

If credential compromise is plausible: stop affected services, revoke/rotate credentials/keys, preserve sanitized evidence, and never treat container shutdown alone as remediation.

# Completion output

Successful run:

```text
DEPLOYMENT: PASS
Mode: dynamic-authority
Repo SHA: <sha>
Roles healthy: 7/7
Builder gateway path: VERIFIED
Negative canaries: PASS
One-shot approval: PASS
Emergency stop: PASS
Observability: PASS|DEGRADED|NOT_SELECTED
Orchestrator: DISABLED|SINGLE_ROLE_CANARY
Evolution lessons: <n>
Candidate skill fork: none|<candidate-id>
Known limitations: <short list>
```

Blocked run reports the failed gate, sanitized evidence, safe default, and exact next human action. Never label a partial/degraded deployment as fully secure.
