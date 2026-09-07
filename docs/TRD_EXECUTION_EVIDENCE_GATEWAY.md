# HermeTeam — Technical Requirements Document (TRD)
## Version 2.1 — Execution Evidence, Authority Audit, Secure Corridor and Governance Architecture

**Status:** Updated canonical TRD  
**Date:** 2026-09-07  
**Repository:** `HermeTeam/hermes-sdlc-agents`  
**Primary implementation target:** GitHub-first Flight Recorder + SDLC Agent Authority Audit  
**Expansion target:** Secure GitHub Execution Corridor + AI Coding Agent Governance

---

## 1. Technical Objective

Extend the existing Hermes SDLC agent bundle with a security-grade evidence and authority plane capable of reconstructing:

`Intent → Principal → Delegation → Agent Identity → Tool Call → Policy Decision → Authorization → State Before → State Change → State After → Outcome → Evidence`

and, separately, of answering:

`Declared Authority ↔ Effective GitHub Authority ↔ Observed Agent Actions`

The first implementation MUST support observe-first deployment and MUST reuse the existing role/container/GitHub-MCP architecture. The same components MUST later support mandatory policy enforcement and governance without replacing the evidence model.

---

## 2. Design Principles

1. **Extend, do not replace.** Preserve the current issue-driven orchestrator, role isolation and runtime dashboard.
2. **Separate workflow state from security evidence.** Role-local queue/run state and cross-role authority/evidence have different lifecycles and retention requirements.
3. **One evidence model.** Flight Recorder, Authority Audit, Secure Corridor and Governance write/query the same canonical evidence/authority model.
4. **Observe before enforce.** The gateway may run in `RECORD_ONLY` mode before it becomes a blocking boundary.
5. **Make existing policy real in enforcement mode.** `policies/roles.yaml` and `policies/mcp-policy.rego` already express much of the desired boundary; enforcement mode adds a mandatory inline decision point instead of creating a second authorization model.
6. **Keep provider credentials out of agents in secure mode.** Managed Hermes containers must not retain reusable GitHub credentials once Secure Corridor is enabled.
7. **Fail closed for mutation in enforcement mode.** Policy, identity, repository, evidence, token or normalization ambiguity MUST NOT become a mutation.
8. **Preserve defense in depth.** `tools.include`, managed profiles, `SOUL.md`, GitHub permissions/rulesets and trusted CI remain independent controls.
9. **No source-code logging by default.** Evidence stores canonical hashes, references and bounded metadata; source content remains in GitHub unless explicitly configured otherwise.
10. **Provider truth is separate from declared policy.** GitHub control scanning is required because repository/App configuration may drift outside HermeTeam.

---

## 3. Current Repository Anchors

The existing implementation already includes relevant anchors:

- `policies/roles.yaml`
- `policies/mcp-policy.rego`
- `policies/protected-paths.txt`
- `profiles/hermes-*/config.yaml`
- `profiles/hermes-*/SOUL.md`
- `orchestrator/sdlc_orchestrator/db.py`
- `orchestrator/sdlc_orchestrator/config.py`
- `orchestrator/sdlc_orchestrator/hermes_client.py`
- `orchestrator/sdlc_orchestrator/provider_github.py`
- `orchestrator/sdlc_orchestrator/reconciler.py`
- `orchestrator/sdlc_orchestrator/status_server.py`
- `orchestrator/sdlc_orchestrator/status_snapshot.py`
- `orchestrator/tests/test_orchestrator.py`
- current central `GET /api/overview`
- `dashboard/src/server/index.ts`
- `dashboard/src/server/overview.ts`
- `dashboard/src/shared/contracts.ts`
- `dashboard/src/web/App.tsx`
- `compose.yaml`
- `compose.debug.yaml`
- `kustomization.yaml`
- `kubernetes/*`
- `scripts/validate.sh`
- `scripts/smoke-test.sh`
- dashboard/orchestrator smoke and E2E tests.

Current orchestrator state is:

```text
work_items → role_assignments → agent_runs → transitions
```

in role-local SQLite. That state machine remains workflow-owned.

The current security gap is that `mcp-policy.rego` is not necessarily a mandatory inline enforcement point when an agent connects directly to the official GitHub MCP endpoint.

---

## 4. Bounded Contexts and Target Architecture

HermeTeam SHALL separate four bounded contexts.

### 4.1 Workflow Plane — existing orchestrator

Owns:

- issue/work-item discovery;
- assignment lifecycle;
- Hermes run submission/retry/reconciliation;
- transitions;
- role-local runtime status.

Existing owner: `orchestrator/`.

### 4.2 Evidence & Authority Plane — new central service

Owns:

- intents/principals/delegations;
- runtime identity snapshots;
- evidence events;
- state changes/outcomes;
- policy versions/decisions;
- GitHub installation/repository inventory;
- permission/control snapshots;
- findings;
- grants/governance decisions;
- evidence export.

This state is cross-role and cross-repository and MUST NOT use role-local orchestrator DB as its primary retention store.

### 4.3 Execution Evidence Gateway — new execution boundary

Owns:

- managed-agent identity validation;
- MCP/tool request normalization;
- action classification;
- pre/post state capture where possible;
- policy/authority evaluation;
- initial decision evidence;
- server-side provider token acquisition;
- upstream execution;
- post-action evidence/outcome.

Modes:

- `RECORD_ONLY` — records/evaluates but does not introduce new deny behavior beyond existing hard protections;
- `ENFORCE` — protected mutations require valid policy/authority and fail closed.

### 4.4 Dashboard Control Plane

Owns:

- Runtime view;
- Flight Recorder / Investigation;
- Authority inventory;
- Findings;
- Activity;
- Governance UX.

Browser MUST NOT receive database/provider secrets.

### 4.5 Target topology

```text
                         ┌──────────────────────────────────────┐
                         │ Dashboard                            │
                         │ Runtime / Recorder / Authority /     │
                         │ Findings / Activity / Governance     │
                         └────────────────┬─────────────────────┘
                                          │ server-side API
                                          ▼
                         ┌──────────────────────────────────────┐
                         │ Authority / Evidence Service         │
                         │ evidence, policies, scans, findings, │
                         │ grants, exports                      │
                         └────────────────┬─────────────────────┘
                                          ▲
                                          │ decisions/evidence
                                          │
GitHub issue → Orchestrator → Hermes role │
                               │ MCP       │
                               ▼           │
                    ┌──────────────────────┴───────────────┐
                    │ Execution Evidence / Policy Gateway  │
                    │ identity → normalize → pre-state     │
                    │ → record → policy → token → upstream │
                    │ → post-state → outcome → record      │
                    └──────────────────────┬───────────────┘
                                           │ short-lived provider credential
                                           ▼
                                 GitHub MCP and/or GitHub API
                                           │
                                           ▼
                                         GitHub
```

The orchestrator links to the Evidence & Authority Plane using correlation identifiers; it does not become the evidence store.

---

## 5. Recommended Repository Layout Changes

Add:

```text
hermes-sdlc-agents/
├── authority/
│   ├── pyproject.toml
│   ├── authority_core/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── models.py
│   │   ├── ids.py
│   │   ├── canonical.py
│   │   ├── hashing.py
│   │   ├── evidence.py
│   │   ├── completeness.py
│   │   ├── policies.py
│   │   ├── github_app.py
│   │   ├── github_scan.py
│   │   ├── findings.py
│   │   ├── grants.py
│   │   ├── exports.py
│   │   └── service.py
│   └── tests/
│
├── policy-gateway/
│   ├── pyproject.toml
│   ├── gateway/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── identity.py
│   │   ├── normalize.py
│   │   ├── classify.py
│   │   ├── mcp_proxy.py
│   │   ├── opa.py
│   │   ├── state_capture.py
│   │   ├── upstream.py
│   │   └── server.py
│   └── tests/
│
├── policies/
│   ├── roles.yaml                 # existing bootstrap/default policy
│   ├── mcp-policy.rego            # existing runtime semantics, extend with reason codes
│   ├── protected-paths.txt        # existing
│   └── finding-rules.yaml         # optional rule metadata
│
└── dashboard/src/
    ├── server/
    │   ├── index.ts               # existing routing; extend incrementally
    │   ├── authority-client.ts     # new
    │   └── auth.ts                 # new before write routes
    ├── shared/
    │   └── authority-contracts.ts  # new strict contracts
    └── web/
        ├── App.tsx                 # shell/nav after regression tests
        ├── RuntimePage.tsx         # extracted current runtime UI
        ├── FlightRecorderPage.tsx
        ├── InvestigationPage.tsx
        ├── AuthorityPage.tsx
        ├── FindingsPage.tsx
        ├── ActivityPage.tsx
        └── GovernancePage.tsx
```

### Why `authority/` is separate from `orchestrator/`

`orchestrator/sdlc_orchestrator/db.py` is role-local workflow state. Security evidence is cross-role, append-oriented, longer-lived and must survive queue cleanup/restart semantics. Coupling both schemas would make independent retention, central/multi-host deployment and security isolation harder.

The orchestrator MAY gain correlation columns/references, but it MUST NOT own the canonical evidence/grant/finding history.

---

## 6. Canonical Data Model

The exact database engine is not a product contract. SQLite is acceptable for a local prototype; PostgreSQL is recommended for production/multi-role use. Larger artifacts may move to object storage.

Minimum logical entities:

### 6.1 `intents`

```sql
CREATE TABLE intents (
    intent_id TEXT PRIMARY KEY,
    principal_id TEXT,
    source_type TEXT NOT NULL,
    source_ref TEXT,
    summary TEXT,
    request_hash TEXT,
    scope_json TEXT,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL
);
```

### 6.2 `runtime_identities`

```sql
CREATE TABLE runtime_identities (
    runtime_identity_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    role TEXT NOT NULL,
    model_provider TEXT,
    model_name TEXT,
    container_digest TEXT,
    profile_hash TEXT,
    soul_hash TEXT,
    config_hash TEXT,
    policy_bundle_hash TEXT,
    tools_hash TEXT,
    observed_at TEXT NOT NULL
);
```

### 6.3 `delegations`

```sql
CREATE TABLE delegations (
    delegation_id TEXT PRIMARY KEY,
    parent_delegation_id TEXT,
    from_principal_id TEXT NOT NULL,
    to_subject_id TEXT NOT NULL,
    scope_json TEXT NOT NULL,
    permissions_json TEXT NOT NULL,
    constraints_json TEXT,
    issued_at TEXT NOT NULL,
    expires_at TEXT,
    revoked_at TEXT
);
```

### 6.4 `evidence_events`

```sql
CREATE TABLE evidence_events (
    event_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    trace_id TEXT NOT NULL,
    intent_id TEXT,
    delegation_id TEXT,
    principal_id TEXT,
    agent_id TEXT NOT NULL,
    agent_role TEXT NOT NULL,
    runtime_identity_id TEXT,
    event_type TEXT NOT NULL,
    tool_name TEXT,
    operation TEXT,
    target TEXT,
    parameters_hash TEXT,
    policy_decision_id TEXT,
    grant_id TEXT,
    state_before_hash TEXT,
    state_after_hash TEXT,
    outcome_id TEXT,
    previous_event_hash TEXT,
    event_hash TEXT NOT NULL,
    server_signature TEXT,
    created_at TEXT NOT NULL
);
```

### 6.5 `state_changes`

```sql
CREATE TABLE state_changes (
    state_change_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    system_type TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_ref TEXT NOT NULL,
    before_ref TEXT,
    before_hash TEXT,
    after_ref TEXT,
    after_hash TEXT,
    delta_hash TEXT,
    captured_at TEXT NOT NULL
);
```

### 6.6 `outcomes`

```sql
CREATE TABLE outcomes (
    outcome_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    expected_json TEXT,
    observed_json TEXT,
    status TEXT NOT NULL,
    artifact_refs_json TEXT,
    verified_at TEXT
);
```

### 6.7 Authority Audit / Governance entities

Add logical tables/collections for:

- `agents`
- `repositories`
- `github_installations`
- `policy_versions`
- `governance_decisions`
- `policy_decisions`
- `upstream_actions`
- `permission_snapshots`
- `findings`
- `grants`.

Every security-significant row/object MUST have a stable ID. Event, policy-decision and governance-decision records are append-oriented.

---

## 7. Canonical Evidence and Hashing

Canonical serialization MUST:

- use stable field ordering;
- normalize supported scalars/lists/objects;
- exclude raw secrets/tokens;
- avoid full source content by default;
- preserve enough target metadata to reconstruct the action.

Event chain:

```text
event_hash = H(canonical_event_without_signature + previous_event_hash)
```

Server signature/attestation is generated outside agent credentials.

Agents MUST NOT receive:

- evidence DB update/delete credentials;
- signing key;
- retention-admin credentials.

Unknown schema versions MAY be stored opaquely in observe mode, but enforcement code MUST fail closed if it cannot safely evaluate the required schema.

---

## 8. ID and Correlation Propagation

Introduce/use stable identifiers:

- `intent_id`
- `trace_id`
- `delegation_id`
- `agent_id`
- `runtime_identity_id`
- `assignment_key`
- `hermes_run_id`
- `session_id`
- `event_id`
- `decision_id`
- `grant_id`.

### 8.1 Orchestrator integration

Candidate existing files:

- `orchestrator/sdlc_orchestrator/db.py`
- `orchestrator/sdlc_orchestrator/hermes_client.py`
- `orchestrator/sdlc_orchestrator/prompts.py`
- `orchestrator/sdlc_orchestrator/reconciler.py`
- `orchestrator/tests/test_orchestrator.py`.

Required changes SHOULD be minimal:

1. create/reuse `intent_id` and `trace_id` when work is accepted;
2. persist correlation references beside existing workflow state if needed;
3. include correlation context in `/v1/runs` metadata/input context where Hermes supports it;
4. expose stable run/work-item identifiers to the gateway/evidence plane;
5. preserve current retry/final-response/transition semantics.

Do NOT migrate `work_items`, `role_assignments`, `agent_runs` or `transitions` into the Authority DB.

### 8.2 `provider_github.py` boundary clarification

`orchestrator/sdlc_orchestrator/provider_github.py` currently owns issue discovery and issue-label/comment transitions for orchestration. It is NOT the primary path for Hermes repository MCP mutations such as builder `push_files`.

Therefore:

- do not overload it with all Execution Evidence Gateway logic;
- reuse it only for work-item correlation and orchestration-specific provider evidence as needed;
- managed-agent GitHub tool calls are intercepted at the MCP/gateway boundary.

---

## 9. Execution Evidence / Policy Gateway

### 9.1 Responsibilities

The gateway MUST be capable of:

1. authenticate managed role/agent;
2. parse/normalize MCP request;
3. bind request to configured repository;
4. classify action;
5. capture supported pre-state;
6. create initial evidence/policy-decision record;
7. evaluate current policy/authority;
8. in `RECORD_ONLY`, record decision without introducing new blocking semantics except existing hard protections;
9. in `ENFORCE`, deny invalid/review-required actions unless a valid grant/approval exists;
10. obtain server-side short-lived provider token if execution is allowed;
11. call upstream GitHub MCP and/or exact GitHub API adapter;
12. capture post-state/outcome;
13. append upstream result evidence.

### 9.2 Managed profile integration

Current profiles use official GitHub MCP plus `GIT_PROVIDER_MCP_TOKEN`.

Target secure-mode configuration:

```text
GIT_PROVIDER_MCP_URL=http://hermeteam-policy-gateway:8787/mcp/
GIT_PROVIDER_MCP_TOKEN=<gateway role identity token, NOT GitHub token>
```

Maintain existing `tools.include` in `profiles/hermes-*/config.yaml` as defense-in-depth/tool discoverability. Gateway is the runtime authorization boundary in `ENFORCE` mode.

### 9.3 Identity

Reuse claims anticipated by `policies/roles.yaml`:

- `iss`
- `sub`
- `aud=git-provider-mcp`
- `role`
- `exp`
- `jti`.

Gateway MUST reject missing, expired or wrong-audience identity. `maximumTokenTtlSeconds: 3600` remains an initial upper bound unless policy changes it.

Recommended `sub`: stable managed instance/role identity, e.g. `hermes-builder@local`.

### 9.4 MCP proxy strategy

Preferred implementation is an MCP-aware reverse proxy supporting only required methods/tool semantics:

- initialize/session behavior required by the chosen transport;
- `tools/list`;
- `tools/call`;
- no generic raw HTTP tunnel;
- reject provider resources/prompts/sampling/elicitation where the current security model excludes them.

If upstream official GitHub MCP proxying is operationally unsuitable, implement the exact currently-used GitHub tool subset against GitHub REST API behind the same gateway contract. The product contract is HermeTeam's normalized tool/action boundary, not the upstream transport.

### 9.5 Canonical request

Example:

```json
{
  "agent": {"sub":"hermes-builder@local","role":"hermes-builder","jti":"..."},
  "repository": {"owner":"example","repo":"service-a","default_branch":"main"},
  "tool":"push_files",
  "args":{"branch":"agent/REQ-123-fix","files":[{"path":"src/a.py","content_hash":"..."}]},
  "protected_paths":[".github/","policies/"],
  "correlation": {
    "trace_id":"...",
    "intent_id":"...",
    "assignment_key":"...",
    "hermes_run_id":"...",
    "session_id":"...",
    "work_item":"REQ-123"
  }
}
```

Canonical hashing MUST not require storing raw source content.

### 9.6 Policy output

Extend existing Rego semantics to produce reason-coded output:

```json
{
  "decision":"ALLOW",
  "reason_code":"allowed_task_branch",
  "role":"hermes-builder",
  "tool":"push_files",
  "policy_version":"...",
  "required_evidence":[],
  "required_approval":false
}
```

Required Rego improvements:

- explicit reason codes;
- safe handling of unknown role/tool;
- required identity claim checks;
- policy version/hash input/output;
- mutation classification;
- repository/branch/protected-path checks preserved;
- tests for every current role.

### 9.7 Fail-closed rules in `ENFORCE`

Mutation MUST be denied when:

- identity invalid;
- policy unavailable/invalid;
- repository unknown/mismatched;
- protected-path data unavailable when required;
- required initial decision evidence cannot be persisted;
- required grant/approval cannot be resolved;
- GitHub App installation cannot be resolved;
- token broker fails;
- tool/arguments cannot be safely normalized.

---

## 10. GitHub State Capture

### Branch creation

Pre:
- source/base/default SHA;
- branch absence.

Post:
- branch ref;
- head SHA.

### `push_files`

Pre:
- branch head SHA;
- relevant file blob SHA(s) where available;
- base commit.

Post:
- new commit SHA;
- resulting blob SHA(s);
- changed-path/diff hash.

### PR creation/update

Pre:
- source/head SHA;
- target/base SHA.

Post:
- PR number/ref;
- head/base SHA;
- changed-files hash;
- checks/status refs.

### Protected paths

Any touched path matching `policies/protected-paths.txt` MUST be tagged security-sensitive even in observe mode. In enforcement mode current policy semantics must deny or require explicit supported authority according to policy.

---

## 11. Evidence Completeness Engine

Dimensions:

```text
principal
intent
delegation
runtime_identity
tool_call
policy_decision
authority
state_before
state_after
outcome
artifact_integrity
```

Return both status and missing dimensions:

```json
{
  "status":"PARTIAL",
  "score":0.82,
  "missing":["delegation","outcome"]
}
```

Do not present a numeric score without explicit missing dimensions.

---

## 12. Authority Graph

Do not require a graph database for MVP. Use relational records/views first.

Logical edges:

```text
Principal -REQUESTED-> Intent
Intent -DELEGATED_AS-> Delegation
Delegation -AUTHORIZED-> Agent
Agent -INVOKED-> ToolCall
ToolCall -EVALUATED_BY-> PolicyDecision
ToolCall -CAUSED-> StateChange
StateChange -PRODUCED-> Outcome
Outcome -SUPPORTED_BY-> EvidenceArtifact
```

For any observed action, the API SHOULD be able to answer whether authority was:

- `PROVEN`
- `UNPROVEN`
- `EXPIRED`
- `REVOKED`
- `NOT_REQUIRED_IN_OBSERVE_MODE`.

---

## 13. GitHub App and Token Broker

### 13.1 Purpose

Current `compose.yaml` injects role-specific GitHub tokens. That is acceptable only as a migration/observe-mode baseline. Secure Corridor release state removes reusable provider credentials from managed agent containers.

### 13.2 GitHub App permissions

Request only the union needed for supported flows, then apply narrower HermeTeam policy at runtime. Evaluate at minimum:

- Metadata: read;
- Contents: read/write where builder needs it;
- Pull requests: read/write;
- Issues: read/write where managed workflows require it;
- Actions: read; write only if workflow dispatch is required;
- administration/branch-protection mutation: NOT requested for agent execution.

### 13.3 Broker contract

Suggested `authority/authority_core/github_app.py`.

Input:

- installation/repository;
- managed agent/role;
- exact normalized operation;
- policy decision;
- grant/approval when required;
- expiry constraint.

Output:

- short-lived token handle/value only to gateway memory;
- `grant_id`/installation reference;
- expiry.

Rules:

- never log raw token;
- never persist raw token in evidence;
- minimal TTL;
- no token in Hermes profile/state;
- revoke stops future issuance immediately at HermeTeam even if already-issued provider tokens have residual TTL.

---

## 14. Authority Inventory and GitHub Effective-Control Scanner

### 14.1 Inventory

Authority service MUST build inventory from:

- `policies/roles.yaml`;
- active policy overrides;
- managed role/profile information;
- GitHub App installation/repository mapping;
- observed runtime identities/actions.

Per agent/role/repository expose:

- declared tools;
- declared branch/path constraints;
- provider repository scope;
- credential source/reference;
- TTL policy;
- policy version;
- last observed action.

### 14.2 GitHub scanner

Suggested `authority/authority_core/github_scan.py`.

Read where connection permissions allow:

- installation repositories/permissions;
- default branch;
- branch protections/rulesets;
- required reviews/checks;
- Actions/workflow permissions;
- relevant environment controls/context.

Scanner snapshots MUST include:

- `snapshot_id`;
- repository;
- observed_at;
- source/provider API references;
- normalized control data;
- completeness/permission limitations;
- canonical hash.

Unknown/unreadable controls are `UNVERIFIABLE`, not implicitly safe.

### 14.3 Scan triggers

Support:

- onboarding scan;
- manual rescan;
- periodic scan later;
- rescan after governance/provider configuration change where practical.

---

## 15. Deterministic Finding Engine

Suggested `authority/authority_core/findings.py`.

MVP rules:

1. direct reusable provider credential remains in managed agent in enforcement mode;
2. credential reuse across roles where separation expected;
3. builder can write protected/default branch;
4. builder can touch protected path;
5. builder has merge authority;
6. provider repository scope broader than configured;
7. unknown/unallowlisted tool attempted;
8. mutation missing policy decision in enforcement mode;
9. mutation missing required correlation;
10. declared deny but provider would permit if gateway were bypassed;
11. TTL policy too long;
12. expected ruleset/branch protection absent/weaker;
13. reviewer can mutate author branch/content;
14. profile/roles/runtime policy drift;
15. GitHub control scan stale/failed.

Finding record SHOULD contain:

- finding id;
- rule id/version;
- severity;
- agent/repository scope;
- evidence refs;
- first_seen/last_seen;
- status;
- remediation hint;
- canonical source snapshot hash.

Severity is deterministic rule metadata, not LLM judgement in MVP.

---

## 16. Policy Versions and Governance

### 16.1 Bootstrap policy

`policies/roles.yaml` remains the checked-in bootstrap/default policy.

The runtime system MAY layer a versioned overlay instead of rewriting the Git working tree for every operator change.

Effective policy:

```text
checked-in base policy
        +
versioned runtime overlay
        +
temporary active grant
        =
effective policy for decision
```

Every decision stores the effective policy version/hash.

### 16.2 Supported override dimensions

Initial Governance supports only:

- role/agent;
- repository;
- tool/action;
- branch pattern;
- path allow/deny;
- validity window.

Do not expose merge/admin/production capability merely because provider APIs support it.

### 16.3 Temporary grants

Grant includes:

- subject;
- repo;
- supported action scope;
- constraints;
- issued_by;
- reason;
- issued_at;
- expires_at;
- revoked_at;
- parent policy version.

Expired/revoked grant MUST stop authorizing future requests without manual cleanup.

### 16.4 Revoke semantics

Revoke MUST:

1. mark grant/subject scope revoked in Authority service;
2. make gateway deny future matching requests;
3. stop token broker from minting tokens for revoked scope;
4. preserve all historical evidence;
5. display residual expiry of already-issued provider tokens if relevant.

---

## 17. Dashboard and API Design

### 17.1 Preserve existing runtime API

`GET /api/overview` remains contractually stable as much as possible.

Before refactoring `dashboard/src/web/App.tsx`, protect current behavior with existing/new tests and then extract it to `RuntimePage.tsx`.

### 17.2 Server-side Authority client

Add `dashboard/src/server/authority-client.ts`.

Dashboard server calls Authority service over private `hermes-control` network. Browser does not call DB/internal service directly.

### 17.3 Proposed read routes

```text
GET /api/intents
GET /api/intents/:id
GET /api/events
GET /api/events/:id
GET /api/investigations/:traceId
GET /api/evidence/:traceId/completeness
GET /api/evidence/:traceId/export
GET /api/authority/agents
GET /api/authority/agents/:id
GET /api/authority/repositories
GET /api/authority/findings
GET /api/authority/activity
GET /api/authority/policies
GET /api/authority/policies/:id
GET /api/delegations
```

### 17.4 Proposed control routes

```text
POST /api/governance/policies
POST /api/governance/grants
POST /api/governance/revoke
POST /api/approvals
POST /api/authority/repositories/:id/rescan
```

All control routes require authentication.

### 17.5 Authentication

Current `dashboard/src/server/index.ts` rejects non-GET and the dashboard is unauthenticated/loopback-only. Do NOT simply add POST routes.

Minimal local control-plane MVP:

- configured operator credential/password hash/secret;
- server-side session;
- HttpOnly + SameSite cookie;
- CSRF-safe POST semantics;
- login rate limiting;
- loopback bind remains default.

Enterprise SSO/RBAC is later work.

### 17.6 TypeScript contracts

Add `dashboard/src/shared/authority-contracts.ts` with explicit parsing/validation matching current `shared/contracts.ts` style. Do not trust Authority service JSON directly in React.

### 17.7 UI decomposition

Incrementally split:

- `App.tsx` → shell/navigation;
- `RuntimePage.tsx` → current runtime view;
- `FlightRecorderPage.tsx`;
- `InvestigationPage.tsx`;
- `AuthorityPage.tsx`;
- `FindingsPage.tsx`;
- `ActivityPage.tsx`;
- `GovernancePage.tsx`.

No design-system rewrite is required.

---

## 18. Compose Changes

Add services:

```text
hermeteam-authority
hermeteam-policy-gateway
```

Optional OPA runtime:

```text
opa
```

Add persistent volume:

```text
authority-data:
```

### Authority service

Owns:

- Authority/Evidence DB;
- GitHub App private key/credentials;
- evidence signing key;
- scanner;
- findings;
- policy/grant data;
- export.

It is reachable only on the private control network.

### Gateway

Owns:

- gateway identity verification;
- OPA access;
- provider token use;
- upstream GitHub access;
- state capture.

### Agent services

Migration target:

- `GIT_PROVIDER_MCP_URL` points to gateway;
- `GIT_PROVIDER_MCP_TOKEN` contains gateway identity, not GitHub credential;
- direct GitHub MCP/API egress blocked where feasible in secure mode.

### Dashboard

Gets only private Authority service URL/credential and remains loopback-published by default.

---

## 19. Kubernetes Changes

Add:

- `kubernetes/hermeteam-authority.yaml`
- `kubernetes/policy-gateway.yaml`
- optional `kubernetes/opa.yaml`
- Service objects;
- Secret refs for GitHub App/evidence signing/operator auth;
- PVC strategy for evidence DB;
- NetworkPolicy updates.

Update `kustomization.yaml` resources/images.

Security requirements:

- no GitHub App private key in agent Pods;
- no evidence DB credential in agent Pods;
- no Kubernetes service-account tokens in agent Pods beyond current explicit model;
- agent egress restricted to gateway/required model/services in secure mode;
- Authority DB/service not directly reachable by agent Pods unless an append-only narrowly scoped endpoint is intentionally exposed.

---

## 20. Validation Changes

Extend `scripts/validate.sh` with mode-aware invariants.

### Observe/record mode

- evidence service/gateway config parses;
- evidence/signing secrets not present in tracked files;
- evidence store not mounted writable into agents;
- role allowlist consistency remains green;
- recorder configuration explicitly marks whether direct provider credential remains.

### Secure Corridor mode

Additionally require:

- no managed role has reusable GitHub MCP token env requirement;
- managed role MCP URL points to gateway;
- gateway/authority services exist;
- GitHub App secret absent from agent env/volumes;
- policy covers all valid roles;
- protected paths parse;
- no unsupported governance admin capabilities;
- Kubernetes NetworkPolicy/Compose topology does not expose bypass path.

---

## 21. Test Strategy

### 21.1 Gateway unit tests

- identity claims;
- canonical argument hashing;
- tool/action classification;
- all current role allow/deny semantics;
- repository mismatch;
- protected branch/path;
- expired identity;
- unknown role/tool;
- policy unavailable;
- evidence-write failure;
- record-only vs enforce behavior.

### 21.2 Authority service unit tests

- event hashing/chain validation;
- append-only semantics;
- policy bootstrap/import;
- overlay/version resolution;
- temporary grant expiry;
- revoke;
- runtime identity hashing;
- GitHub scanner normalization;
- 15 finding rules;
- finding dedup/status preservation;
- completeness calculation;
- export integrity.

### 21.3 Dashboard tests

- existing `/api/overview` remains green;
- auth before write routes;
- method guards;
- strict Authority response parsing;
- Runtime page regression;
- Recorder/Authority/Findings/Activity empty/error/partial states;
- Governance write path requires session.

### 21.4 Integration tests

Use fake upstream MCP/GitHub and fake Authority service to prove:

- denied call is never forwarded in enforce mode;
- allowed call forwarded exactly once;
- initial decision/evidence persisted before mutation;
- upstream result appended;
- raw token absent from evidence;
- record-only mode captures without new deny;
- Authority service outage fails enforcement mutation closed.

### 21.5 Real GitHub canaries

Dedicated test repository.

Positive:

1. planner reads allowed repository/file;
2. builder creates `agent/REQ-123-*`;
3. builder pushes allowed file;
4. builder triggers/reads CI where supported;
5. builder opens PR;
6. reviewer performs its allowed read/comment flow.

Negative:

1. builder writes `main` → DENY;
2. builder writes `master` → DENY;
3. builder writes `release/*` → DENY;
4. builder modifies protected path → DENY;
5. builder targets different repo → DENY;
6. builder calls merge/admin → DENY;
7. planner creates branch → DENY;
8. reviewer pushes files → DENY;
9. unknown tool → DENY;
10. expired gateway identity → DENY;
11. revoked agent mutation → DENY;
12. expired temporary grant → DENY;
13. evidence mutation/delete attempt → impossible/denied;
14. direct provider bypass from secure agent environment → unavailable/blocked.

---

## 22. Migration Plan

### M0 — Freeze existing contracts

- preserve `/api/overview` behavior with tests;
- preserve orchestrator state-machine tests;
- document current direct-MCP baseline.

### M1 — Evidence Foundation

- add `authority/` service/package;
- add canonical IDs/events/hashing;
- add central DB;
- add intent/run correlation;
- no traffic changes yet.

### M2 — Flight Recorder / `RECORD_ONLY`

- add gateway abstraction;
- intercept one managed role first;
- capture pre/post state and outcome;
- record policy informationally;
- preserve current execution semantics;
- show evidence completeness.

### M3 — Authority Audit

- inventory;
- GitHub scanner;
- 15 findings;
- Activity/Authority/Findings UI;
- export.

### M4 — GitHub App / Secure Corridor canary

- token broker;
- point one read-only role to gateway identity;
- then builder;
- run positive/negative real-repo suite.

### M5 — Remove direct provider credentials

- remove `*_GITHUB_MCP_TOKEN` requirements from managed agents in secure mode;
- block direct provider egress;
- update Compose/Kubernetes/docs/examples.

### M6 — Governance

- dashboard authentication;
- policy overlay/versioning;
- temporary grant;
- revoke;
- drift rescan/history.

---

## 23. Ordered Implementation Sequence

This section is intentionally compatible with AI-agent implementation planning. Each numbered item SHOULD be delivered as a small reviewable PR or tightly related PR set, with existing tests kept green.

### Epic A — Protect baseline
1. lock current dashboard `/api/overview` behavior with regression tests;
2. lock current orchestrator workflow/state behavior with regression tests.

### Epic B — Evidence Foundation
3. create `authority/` package/service skeleton;
4. define IDs and canonical `EvidenceEvent` schema;
5. implement canonical hashing/chain validation;
6. implement central append-oriented DB/store;
7. add intent/trace correlation to orchestrator without moving workflow tables;
8. add runtime identity snapshot model.

### Epic C — GitHub Flight Recorder
9. create `policy-gateway/` package skeleton;
10. implement managed identity validation;
11. implement MCP/tool normalization and action classification;
12. implement GitHub pre-state capture;
13. implement initial evidence append;
14. implement record-only policy evaluation;
15. implement upstream call adapter/proxy;
16. implement post-state capture and outcome evidence;
17. migrate one read-only role as recorder canary;
18. migrate Builder in `RECORD_ONLY` and preserve task flow.

### Epic D — Investigation / Authority Audit
19. implement completeness engine;
20. implement investigation/timeline API;
21. implement managed agent/repository inventory;
22. implement GitHub effective-control scanner;
23. implement 15 deterministic findings;
24. add dashboard Flight Recorder/Investigation/Authority/Findings/Activity views;
25. add audit/evidence export.

### Epic E — Secure Corridor
26. extend Rego to reason-coded decisions and test all roles;
27. implement GitHub App JWT/installation token broker;
28. switch gateway to `ENFORCE` for dedicated canary;
29. remove direct GitHub provider credential from builder;
30. add secure Compose/Kubernetes no-bypass network path;
31. run adversarial real-GitHub canaries.

### Epic F — Governance
32. add dashboard authentication;
33. implement policy overlay/version creation;
34. implement temporary grants and automatic expiry;
35. implement revoke/kill future authority;
36. add Governance editor/history UI;
37. add drift comparison/rescan and stale-state indicators;
38. run full end-to-end governance scenario.

---

## 24. Observability

Without secrets, expose structured metrics/logs for:

- events by role/tool/repository;
- evidence completeness;
- allow/review/deny count + reason code;
- upstream latency/status;
- token broker failures;
- evidence write failures;
- active policy version;
- scan age/failures;
- open findings by severity;
- grant/revoke/expiry events.

All logs use decision/event/correlation IDs. Never log raw provider tokens or full source file contents by default.

---

## 25. Key Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Official GitHub MCP proxy complexity | blocks gateway rollout | exact-tool GitHub REST implementation behind same normalized contract |
| Agent bypasses gateway | invalidates enforcement claim | remove provider tokens + network egress controls in secure mode |
| Evidence service unavailable | gaps / unsafe mutation | observe mode marks gaps; enforcement mutation fails closed |
| GitHub App permission union broader than one role | provider blast radius | gateway per-role/repo policy + short TTL + GitHub rulesets |
| Dashboard write path added to unauthenticated app | privilege escalation | authentication before any POST/control route |
| Overloading orchestrator SQLite | coupled retention/failure | dedicated Authority/Evidence store |
| Provider controls unreadable | false confidence | mark `UNVERIFIABLE`, never assume safe |
| Base policy vs runtime overlay drift | confusing authority | explicit version/hash + deterministic drift finding |
| Already issued token after revoke | residual window | short TTL, stop new issuance, gateway deny, display residual expiry |
| Recording layer captures sensitive content | privacy/security | hashes/references/redaction by default |

---

## 26. Definition of Done — Flight Recorder / Authority Audit

The first commercial MVP is technically complete when:

- stable `intent_id`/`trace_id` correlate one full Builder execution;
- supported Builder writes are captured;
- pre/post GitHub state is recorded;
- runtime identity is recorded;
- evidence events are hash-linked and outside agent update/delete authority;
- evidence completeness identifies missing dimensions;
- current Runtime dashboard remains available;
- Flight Recorder/Investigation timeline works;
- agent/repository Authority inventory works;
- GitHub control scan works or clearly marks unverifiable dimensions;
- at least 15 deterministic findings run;
- audit/evidence export works;
- evidence tamper negative test passes;
- existing orchestrator/dashboard/validation tests remain green.

---

## 27. Definition of Done — Secure GitHub Execution Corridor

Secure Corridor is technically complete when:

- managed agent GitHub MCP traffic for the protected flow uses gateway;
- Builder issue → `agent/*` → push → CI → PR succeeds through gateway;
- direct managed-agent GitHub provider credentials are removed;
- direct bypass path is blocked/unavailable in secure deployment;
- every mutation has a persisted reason-coded policy decision;
- GitHub App token is server-side and short-lived;
- forbidden branch/path/repo/tool canaries are denied before upstream mutation;
- evidence outage/policy ambiguity fails mutation closed;
- Compose secure mode works end-to-end;
- Kubernetes manifests render and preserve network/secret boundaries.

---

## 28. Definition of Done — AI Coding Agent Governance

Governance is technically complete when:

- write/control API is authenticated;
- base policy remains auditable and active runtime policy is versioned;
- operator can create supported temporary authority;
- expiry automatically removes authorization;
- revoke blocks future matching mutations;
- governance decisions are preserved as evidence;
- latest GitHub scan is compared with declared/effective policy;
- drift can create a finding;
- Governance UI shows current policy, history, temporary grants and revoke state.

---

## 29. Explicit Technical Non-goals for Current MVP

Do not require in the first GitHub Flight Recorder/Audit release:

- blockchain;
- generic cloud control plane;
- full OpenTelemetry replacement;
- arbitrary LLM reasoning persistence;
- autonomous production credentials;
- exact PR-SHA one-shot grant as mandatory functionality;
- post-execution production infrastructure attestation;
- full SIEM/GRC implementation;
- graph database;
- complex ML/LLM risk classifier;
- enterprise SSO/SCIM;
- parity for every third-party agent vendor.

---

## 30. Architectural Principle

The central HermeTeam primitive is the **Execution Evidence & Authority Gateway**, backed by an independently retained **Evidence & Authority Plane**.

It supports a progression:

```text
RECORD_ONLY
  → Flight Recorder
  → Authority Audit
  → Authority Graph
  → ENFORCE / Secure Corridor
  → Governance
  → exact-change / cross-system attestation
```

The customer may start by trusting HermeTeam only to observe and prove. Once enforcement is enabled, the same evidence graph, policy model and identity model become the basis for non-bypassable bounded execution rather than a second product architecture.