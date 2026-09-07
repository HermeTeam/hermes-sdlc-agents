# HermeTeam — Technical Requirements Document (TRD)
## Version 2.0 — Execution Evidence Architecture

**Status:** Updated canonical TRD  
**Date:** 2026-09-07  
**Repository:** `HermeTeam/hermes-sdlc-agents`  
**Primary implementation target:** GitHub-first Flight Recorder

---

## 1. Technical Objective

Extend the existing Hermes SDLC agent bundle with a security-grade evidence plane capable of reconstructing:

`Intent → Principal → Delegation → Agent Identity → Tool Call → Policy Decision → Authorization → State Before → State Change → State After → Outcome → Evidence`

The first implementation MUST work in observe-first mode and MUST reuse the existing role/container/GitHub-MCP architecture.

---

## 2. Current Repository Anchors

The existing implementation already includes relevant anchors:

- `policies/roles.yaml`
- `policies/mcp-policy.rego`
- `policies/protected-paths.txt`
- `profiles/hermes-*`
- `orchestrator/`
- `orchestrator/sdlc_orchestrator/db.py`
- `provider_github.py`
- `reconciler.py`
- current central `/api/overview`
- `dashboard/src/web/App.tsx`
- `compose.yaml`
- `compose.debug.yaml`
- `kustomization.yaml`
- `scripts/validate.sh`
- smoke/negative tests

The architecture currently separates roles/credentials and avoids writable repo checkouts in agent containers. That remains unchanged.

---

## 3. Target Architecture

```text
                 ┌────────────────────┐
                 │ Human / Issue / API│
                 └─────────┬──────────┘
                           │
                        Intent
                           │
                           ▼
                 ┌────────────────────┐
                 │ Orchestrator       │
                 │ IDs + Delegation   │
                 └─────────┬──────────┘
                           │
                           ▼
                 ┌────────────────────┐
                 │ Hermes Agent       │
                 │ isolated role      │
                 └─────────┬──────────┘
                           │ tool request
                           ▼
              ┌────────────────────────────┐
              │ Execution Evidence Gateway │
              │                            │
              │ 1. PRE-CAPTURE             │
              │ 2. POLICY / AUTHORITY      │
              │ 3. EXECUTE                 │
              │ 4. POST-CAPTURE            │
              └───────┬───────────┬────────┘
                      │           │
                      │           ▼
                      │      GitHub API/MCP
                      │
                      ▼
              Evidence Collector
                      │
            ┌─────────┴─────────┐
            ▼                   ▼
      Event / Graph DB      Artifact Store
            │                   │
            └─────────┬─────────┘
                      ▼
             Investigation API
                      │
                      ▼
                  Dashboard
```

In Phase 1 the gateway may operate as recorder/interceptor without deny authority. In Phase 3 the same path becomes enforcement.

---

## 4. Data Model

### 4.1 `intent`

```sql
CREATE TABLE intents (
    intent_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_ref TEXT,
    summary TEXT,
    request_hash TEXT,
    scope_json TEXT,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL
);
```

### 4.2 `delegation`

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

### 4.3 `evidence_event`

```sql
CREATE TABLE evidence_events (
    event_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    trace_id TEXT NOT NULL,
    intent_id TEXT NOT NULL,
    delegation_id TEXT,
    principal_id TEXT,
    agent_id TEXT NOT NULL,
    agent_role TEXT NOT NULL,
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

### 4.4 `runtime_identity`

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

### 4.5 `state_change`

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

### 4.6 `outcome`

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

---

## 5. Event Schema

Create a shared package/module, suggested location:

`orchestrator/sdlc_orchestrator/evidence/`

Suggested files:

```text
evidence/
  __init__.py
  schema.py
  ids.py
  hashing.py
  store.py
  recorder.py
  state.py
  outcome.py
  completeness.py
```

`schema.py` MUST provide a versioned `EvidenceEvent`.

Use strict validation (Pydantic/dataclass + explicit validation).

Unknown schema versions MUST fail closed for enforcement but MAY be stored as opaque future events in observe mode.

---

## 6. ID Propagation

Introduce stable identifiers:

- `intent_id`
- `trace_id`
- `delegation_id`
- `agent_id`
- `run_id`
- `event_id`

### 6.1 Orchestrator

When an issue is discovered:

1. create/reuse intent;
2. create trace;
3. assign agent/run;
4. include IDs in `/v1/runs` metadata/input context;
5. persist mapping in orchestrator DB.

### 6.2 Provider boundary

Every GitHub/MCP operation MUST receive correlation context.

If native MCP metadata cannot transport all IDs, wrap the provider call in the local gateway and maintain server-side request correlation.

---

## 7. Execution Evidence Gateway

Suggested module:

`orchestrator/sdlc_orchestrator/evidence_gateway.py`

Interface:

```python
execute(
    context: ExecutionContext,
    action: ToolAction,
) -> ExecutionResult
```

Pipeline:

```text
classify_action
    ↓
capture_pre_state
    ↓
record_pre_event
    ↓
evaluate_policy / resolve_authority
    ↓
execute_provider_call
    ↓
capture_post_state
    ↓
collect_outcome
    ↓
record_post_event
```

### Phase 1 behavior

- policy can be informational;
- existing role credentials continue to execute;
- recorder cannot block except existing protections;
- evidence gaps are emitted.

### Phase 3 behavior

- gateway becomes mandatory for protected actions;
- policy result can be ALLOW / REVIEW / DENY;
- exact grant/token required before execution.

---

## 8. GitHub State Capture

### 8.1 Branch creation

Pre:
- repository default/base SHA
- branch absence

Post:
- branch ref
- head SHA

### 8.2 `push_files`

Pre:
- branch head SHA
- relevant file blob SHA(s)
- base commit

Post:
- new commit SHA
- new file blob SHA(s)
- diff/changed-path hash

### 8.3 PR creation/update

Pre:
- source/head SHA
- target/base SHA

Post:
- PR number
- head SHA
- base SHA
- changed files hash
- status/check refs

### 8.4 Protected paths

For any touched path matching `policies/protected-paths.txt`, set security sensitivity metadata even in observe-only mode.

---

## 9. Evidence Store

### 9.1 MVP storage

SQLite/PostgreSQL is acceptable for metadata if the application enforces append-only semantics.

Recommended production direction:
- PostgreSQL metadata;
- object store for larger artifacts;
- immutable/WORM retention option.

### 9.2 Tamper evidence

Each event:

```text
event_hash = H(
    canonical_event_without_signature
    + previous_event_hash
)
```

Server signs/attests the resulting hash.

Agents MUST NOT hold the signing key.

### 9.3 Agent permissions

Agent execution identity:

- may submit tool actions;
- may indirectly cause evidence append;
- MUST NOT update/delete evidence;
- MUST NOT change retention;
- MUST NOT access signing key.

---

## 10. Evidence Completeness Engine

Suggested module:

`evidence/completeness.py`

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

Return:

```json
{
  "status": "PARTIAL",
  "score": 0.82,
  "missing": ["delegation", "outcome"]
}
```

Do not present score alone; always expose missing dimensions.

---

## 11. Authority Graph

Do not require Neo4j for MVP.

Use relational tables and materialized/query views.

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

Add a graph database only if query complexity requires it later.

---

## 12. Policy Gateway Integration

Existing:
- `policies/roles.yaml`
- `policies/mcp-policy.rego`

Required extensions:

Policy input SHOULD include:

```json
{
  "principal": {},
  "intent": {},
  "delegation": {},
  "agent": {},
  "tool": {},
  "target": {},
  "state_before": {},
  "evidence_completeness": {},
  "requested_grant": {}
}
```

Policy output:

```json
{
  "decision": "ALLOW|REVIEW|DENY",
  "reason": "...",
  "required_evidence": [],
  "required_approval": false
}
```

Persist policy bundle hash with each decision.

---

## 13. GitHub App Token Broker — Phase 3

Replace standing writable role tokens for protected operations with short-lived GitHub App installation tokens.

Suggested service:

`authority/token_broker.py`

Input:
- principal
- delegation
- repo
- exact operation
- branch/path scope where representable
- approval
- expiry

Output:
- token reference/handle
- `grant_id`
- expiry

Rules:
- never log raw token;
- never persist raw token in evidence;
- token TTL minimal;
- one-time/exact-change grant preferred;
- agent never receives broader permissions than the approved action path.

---

## 14. Dashboard/API Changes

### API

Add endpoints:

```text
GET  /api/intents
GET  /api/intents/{id}
GET  /api/events
GET  /api/events/{id}
GET  /api/investigations/{trace_id}
GET  /api/agents/{id}/blast-radius
GET  /api/evidence/{trace_id}/completeness
GET  /api/evidence/{trace_id}/export

# Phase 2/3
GET  /api/authority
GET  /api/delegations
POST /api/grants
POST /api/grants/{id}/revoke
POST /api/approvals
```

### UI

Extend current `dashboard/src/web/App.tsx` or split into routes/components:

```text
Overview
Flight Recorder
Investigation
Authority
Governance
```

The current dashboard is read-only; preserve that safety property for Flight Recorder MVP. Authenticated mutation endpoints arrive only with Governance/Approval.

---

## 15. Orchestrator DB Migration

Extend `orchestrator/sdlc_orchestrator/db.py`.

Add migrations/tables:

- intents
- delegations
- runs correlation
- evidence events or references
- state changes
- outcomes
- grants (Phase 3)

Existing deduplication must remain intact.

---

## 16. `provider_github.py`

Refactor provider mutations so all supported consequential calls are routed through a single injectable execution boundary.

Target:

```python
gateway.execute(context, ToolAction(...))
```

Avoid evidence logic duplicated in each caller.

Read-only calls can use lightweight telemetry, but writes MUST use the evidence boundary.

---

## 17. `reconciler.py`

Extend reconciliation to verify:

- expected provider action ↔ actual GitHub state;
- missing post-state;
- stale/out-of-band changes;
- evidence gaps.

In Phase 3 add drift checks between granted authority and observed action.

---

## 18. Compose/Kubernetes

### New service (optional split)

```text
hermeteam-evidence
```

Responsibilities:
- append evidence;
- hash/sign;
- query;
- export.

Alternatively keep in orchestrator for first prototype, but security boundary should be separable.

### Secrets

Add:
- evidence signing key;
- database credentials;
- future GitHub App key.

These MUST NOT be mounted into Hermes agent containers.

### Network policy

Agents may call only required local gateway endpoints; evidence database/signing service should not be directly reachable from agent Pods.

---

## 19. Validation Changes

Extend `scripts/validate.sh`:

- role allowlist consistency;
- evidence service not mounted writable into agents;
- signing key absent from agent containers;
- no DB admin credentials in agent env;
- protected paths still enforced;
- required gateway config present for enforcement mode.

---

## 20. Adversarial Tests

### Evidence tampering

Agent attempts:
- UPDATE evidence
- DELETE evidence
- modify previous event hash
- access signing key
- alter retention

Expected: impossible/denied.

### Gateway bypass

Agent attempts:
- direct GitHub mutation with alternate token;
- direct MCP endpoint bypass;
- local git credential;
- expanded tool list.

Expected:
- observe mode: gap detected and surfaced where technically detectable;
- enforcement mode: blocked by credential/network architecture.

### Authority bypass

Agent attempts:
- action after grant expiry;
- action against another repository;
- action on protected branch/path;
- different tool than approved;
- reuse of one-time grant.

Expected: DENY.

---

## 21. Implementation Sequence

### Epic A — Evidence Foundation
1. versioned EvidenceEvent schema
2. IDs and correlation model
3. DB migrations
4. hashing/signature primitives
5. append-only store interface

### Epic B — GitHub Flight Recorder
6. consequential-action classifier
7. gateway abstraction
8. pre-state capture
9. post-state capture
10. Builder integration
11. outcome capture

### Epic C — Investigation
12. evidence completeness
13. timeline API
14. blast radius
15. dashboard Flight Recorder
16. signed/exportable package

### Epic D — Authority Graph
17. principal/delegation model
18. authority resolution
19. grant history
20. Authority UI

### Epic E — Evidence-Gated Execution
21. OPA input/output extension
22. approval model
23. GitHub App/token broker
24. temporary grants
25. revoke/expiry
26. exact-change constraints

### Epic F — Governance
27. authority inventory
28. scanner/findings
29. drift detection
30. authenticated governance UI
31. SIEM/export
32. multi-repository scale

---

## 22. Definition of Done — Flight Recorder MVP

MVP is technically complete when all are true:

- `intent_id` and `trace_id` are stable end-to-end;
- Builder writes are intercepted;
- pre/post GitHub state is captured;
- runtime identity is captured;
- events are hash-linked and appended outside agent write control;
- current dashboard can display one complete causal trace;
- blast radius works for an agent or intent;
- evidence completeness reports missing dimensions;
- one outcome proof (CI/check result) is linked;
- tamper negative tests pass;
- existing role isolation/OPA/protected paths/smoke tests still pass.

---

## 23. Explicit Technical Non-goals

Do not add in this MVP:

- blockchain;
- generic cloud control plane;
- full OpenTelemetry replacement;
- browser/session video recording;
- arbitrary LLM reasoning persistence;
- autonomous production credentials;
- full SIEM/GRC implementation;
- mandatory graph database;
- complex ML risk classifier.

---

## 24. Architectural Principle

The central HermeTeam primitive should evolve from “Policy Gateway” to:

> **Execution Evidence Gateway**

It combines independent evidence collection with policy/authority enforcement but supports read-mostly evidence recording before enforcement is enabled.

This preserves the current Secure Corridor / Authority design while enabling a lower-friction commercial wedge.
