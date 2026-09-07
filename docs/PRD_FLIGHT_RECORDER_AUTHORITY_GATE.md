# HermeTeam — Product Requirements Document (PRD)
## Version 2.1 — Flight Recorder → Authority Audit → Authority Graph → Evidence-Gated Execution → Governance

**Status:** Updated canonical PRD  
**Date:** 2026-09-07  
**Primary MVP:** GitHub-first Agent Action Evidence / Flight Recorder + SDLC Agent Authority Audit  
**Expansion:** Secure GitHub Execution Corridor + AI Coding Agent Governance

---

## 1. Product Objective

Build a GitHub-first system that independently records consequential AI-agent execution, reconstructs causal chains from human intent to outcome, audits declared versus effective coding-agent authority, and can later use the same evidence graph to enforce and govern bounded authority before state changes occur.

The product MUST support an adoption sequence:

`Observe → Record → Prove → Investigate → Audit Authority → Authorize → Gate → Execute → Prove → Govern`

The implementation MUST extend the existing `HermeTeam/hermes-sdlc-agents` runtime rather than replace its role isolation, issue-driven orchestrator, GitHub MCP flow, policy definitions or runtime dashboard.

---

## 2. Primary User Stories

### Evidence / Investigation

As a Head of AI Security,

I want to see every consequential GitHub action performed by an AI coding agent, linked to the human intent, agent identity, delegated authority, policy decision, state transition and resulting outcome,

so that I can investigate incidents and prove what happened without trusting the agent's own logs.

### Authority Audit

As a Security or Platform owner,

I want to see which managed coding agents can access which repositories, what HermeTeam policy says they can do, what GitHub credentials/rules actually permit, and where these differ,

so that I can reduce excessive authority before an incident occurs.

### Secure Corridor

As a Platform engineer,

I want a managed coding agent to create task branches, bounded file changes, CI runs and PRs without being able to write protected branches/paths, merge, administer repositories or bypass policy,

so that autonomous coding can run safely with technical rather than prompt-only boundaries.

### Governance

As an authorized AI-agent operator,

I want to change supported agent authority, grant it temporarily, revoke it and see decision history,

so that I can operate coding agents without manually coordinating YAML policy, provider credentials and repository controls.

---

## 3. Product Personas

### Security Owner
Needs evidence completeness, authority findings, incident reconstruction and audit export.

### Platform Engineer
Needs minimal integration friction, deterministic APIs, safe GitHub automation and no broad credentials inside agent containers.

### Agent Platform Owner
Needs agent-framework neutrality, correlation IDs and a governable permission model.

### Auditor / Incident Responder
Needs immutable, understandable, exportable causal evidence.

### Engineering Manager / Agent Operator
Needs to see agent runtime, effective authority, recent activity, grants and revoke state without editing policy files manually.

---

## 4. Current Product Baseline

HermeTeam already has:

- isolated roles (`planner`, `project-manager`, `builder`, `reviewer`, `release`, `incident`, `learning`);
- separate containers/Pods and API keys;
- role-specific GitHub credentials as the current baseline;
- GitHub MCP integration;
- exact native tool allowlists;
- `policies/roles.yaml`;
- `policies/mcp-policy.rego`;
- `policies/protected-paths.txt`;
- branch restrictions;
- builder `agent/*` task-branch convention;
- builder no-merge/no-production semantics;
- orchestrator issue discovery and run submission;
- SQLite work-item/assignment/run/transition state;
- read-only runtime dashboard and `/api/overview`;
- validation/smoke tests.

The PRD extends these primitives rather than replacing them.

### Current security limitation

`mcp-policy.rego` expresses strong policy semantics, but the current GitHub MVP can connect managed agents directly to the official GitHub MCP endpoint. Therefore the Rego policy is not yet guaranteed to be a mandatory inline decision point for every mutation.

This limitation is acceptable in observe-only Flight Recorder mode only if surfaced as an evidence/control gap. It is NOT acceptable in Secure Corridor enforcement mode.

---

## 5. Product Packaging

The following are product surfaces over one shared Evidence & Authority Core.

### Package P1 — SDLC Agent Authority Audit

Read-mostly product combining Flight Recorder, inventory, effective GitHub control scanning, findings and evidence history.

### Package P2 — Secure GitHub Execution Corridor

Enforcement product routing protected managed-agent GitHub operations through a server-side policy and credential boundary.

### Package P3 — AI Coding Agent Governance

Authenticated control plane for supported policy scopes, temporary authority, revoke, policy versioning, decision history and drift.

The three packages MUST share one canonical identity/evidence/policy model.

---

## 6. Phase 1 — Flight Recorder Requirements

### FR-1 Canonical EvidenceEvent

The system SHALL define a versioned canonical event envelope.

Minimum fields:

- `event_id`
- `schema_version`
- `timestamp`
- `trace_id`
- `intent_id`
- `delegation_id` when applicable
- `principal`
- `agent_id`
- `agent_role`
- `runtime_identity`
- `tool`
- `operation`
- `target`
- `parameters_hash`
- `policy_decision_id`
- `authorization/grant_id` when applicable
- `state_before_ref/hash`
- `state_after_ref/hash`
- `outcome_ref`
- `previous_event_hash`
- `event_hash`
- `signature` or server attestation.

### FR-2 Intent as First-class Object

The system SHALL create/store `Intent` records representing the initiating human/system objective.

Intent fields:

- `intent_id`
- principal
- source
- request summary
- raw request reference/hash
- scope
- created_at
- status.

### FR-3 Correlation Propagation

`trace_id`, `intent_id`, `agent_id`, and relevant `delegation_id` SHALL propagate across:

- orchestrator discovery;
- Hermes run submission;
- provider/MCP tool invocation;
- policy evaluation when present;
- evidence collection;
- state capture;
- outcome collection.

### FR-4 Runtime Identity

Every consequential event SHALL capture enough runtime identity to answer “which agent instance did this?”

Minimum target fields:

- role;
- agent instance ID;
- model/provider where available;
- container image digest;
- profile/config hash;
- `SOUL.md` hash;
- policy bundle hash;
- tool configuration hash.

### FR-5 Consequential Action Classification

The system SHALL classify tool calls into at least:

- read-only;
- non-consequential write;
- consequential write;
- privileged/security-sensitive.

The MVP SHALL prioritize GitHub state-changing calls such as:

- branch creation;
- file push/update;
- pull-request creation/update;
- workflow/security configuration mutations where exposed;
- any future merge/release mutation.

### FR-6 Pre-state Capture

Before a supported consequential action, HermeTeam SHALL capture a stable representation or hash of relevant state when technically possible.

Examples:

- branch/head SHA;
- base SHA;
- target file blob SHA;
- PR state;
- protected-path policy reference.

### FR-7 Post-state Capture

After execution, HermeTeam SHALL capture the resulting state.

Examples:

- new commit SHA;
- new branch head;
- resulting PR;
- changed-files/diff hash;
- CI run reference.

### FR-8 Outcome Proof

The MVP SHOULD capture technical outcome evidence beyond API success.

Examples:

- CI before/after;
- checks passing/failing;
- PR ready/not ready;
- expected artifact exists;
- no rollback required.

### FR-9 Independent Evidence Store

Agent runtimes SHALL NOT receive update/delete authority over stored evidence.

Minimum required controls:

- append-only application API;
- no delete/update endpoint exposed to agents;
- server-generated hashes;
- chain/link to previous event;
- retention configuration outside agent credentials.

### FR-10 Evidence Completeness

Every investigated execution SHALL expose a completeness state:

- `COMPLETE`
- `PARTIAL`
- `UNVERIFIABLE`

and missing evidence dimensions.

Example dimensions:

- principal;
- intent;
- delegation;
- agent/runtime identity;
- policy decision;
- authority;
- state before;
- state after;
- outcome;
- artifact integrity.

### FR-11 Investigation View

The dashboard SHALL support:

- search by intent;
- search by agent;
- search by repository;
- time range;
- consequential-only filter;
- denied actions;
- incomplete evidence;
- blast radius.

### FR-12 Blast Radius

The UI/API SHALL summarize affected objects, including where available:

- repositories;
- branches;
- commits;
- PRs;
- protected paths;
- policy denials;
- external systems/adapters;
- production-labelled changes.

### FR-13 Evidence Export

The system SHALL export an incident/evidence package including:

- causal timeline;
- event hashes;
- state references;
- policy decisions;
- authority references;
- artifacts;
- completeness report.

---

## 7. Phase 1.5 — SDLC Agent Authority Audit Requirements

### AUD-1 Authority Inventory

The system MUST expose, per managed agent/role/repository:

- agent/role identity;
- declared allowed tools;
- declared constraints;
- effective repository scope;
- credential source/reference without secret value;
- token TTL policy where applicable;
- protected branch/path controls;
- current policy version;
- last observed action timestamp.

### AUD-2 Effective GitHub Control Scanner

For an onboarded repository, the system MUST inspect at minimum where the GitHub connection permits:

- GitHub App installation repository set and permissions;
- default branch;
- relevant branch protection/rulesets;
- required PR review/check conditions;
- Actions/workflow permissions relevant to managed agents;
- repository environments as read-only context where useful.

If a provider API cannot expose a required control with the installed permissions, the scanner MUST mark that dimension `UNVERIFIABLE`; it MUST NOT assume the control is safe.

### AUD-3 Declared-vs-Effective Comparison

The system MUST derive findings when GitHub/provider effective authority is broader or materially less protected than HermeTeam policy expects.

### AUD-4 Deterministic Finding Engine

MVP MUST implement at least these rules:

1. managed agent still configured with a reusable direct GitHub credential in enforcement mode;
2. one credential reused by multiple managed roles where separation is expected;
3. builder can write default/protected branch;
4. builder can modify protected paths;
5. builder has merge authority;
6. managed agent has repository scope broader than configured;
7. unknown/unallowlisted tool attempted;
8. mutating action lacks persisted policy decision when enforcement is enabled;
9. mutating action lacks required run/work-item/agent correlation;
10. declared policy denies an action but provider configuration would permit it if gateway were bypassed;
11. credential/token TTL exceeds configured maximum;
12. expected branch/ruleset protection is absent or materially weaker;
13. reviewer can mutate author branch/content;
14. drift exists between `profiles/*/config.yaml`, `policies/roles.yaml` and active policy snapshot;
15. GitHub control scan is stale/failed.

### AUD-5 Evidence History

Operator MUST be able to list/filter decision/action events by:

- time range;
- role/agent;
- repository;
- work item/run;
- allow/review/deny;
- tool;
- finding severity.

### AUD-6 Audit Export

MVP SHOULD provide machine-readable JSON and human-readable Markdown/HTML export containing inventory, findings and selected evidence references. PDF is optional.

---

## 8. Phase 2 — Authority Graph Requirements

### AG-1 Principal

Represent human/system principals separately from agent identities.

### AG-2 Delegation

Represent delegation edges:

- `from_principal`
- `to_agent/principal`
- `scope`
- `permissions`
- `constraints`
- `expires_at`
- `parent_delegation_id`.

### AG-3 Authority Reconstruction

For any action, API/UI SHALL show the authority chain that existed at execution time.

### AG-4 Grant History

Grant creation, renewal, revocation and expiry MUST be retained as evidence.

### AG-5 Unknown Authority

If no valid delegation/grant can be resolved, the action MUST be marked as `AUTHORITY_UNPROVEN` even when the provider accepted it.

---

## 9. Phase 3 — Secure GitHub Execution Corridor / Evidence-Gated Execution

### COR-1 Mandatory Execution Evidence Gateway

All protected managed-agent GitHub operations in enforcement mode SHALL flow through:

`IDENTITY → NORMALIZE → PRE-CAPTURE → POLICY/AUTHORITY → EVIDENCE DECISION → TOKEN → EXECUTE → POST-CAPTURE → OUTCOME`

The gateway is the mandatory runtime authorization boundary for managed agents in Secure Corridor mode.

### COR-2 No Direct GitHub Credential in Managed Agent Containers

In enforcement mode, managed Hermes agent containers MUST use a gateway identity/token and MUST NOT receive reusable GitHub PATs, GitHub App private keys or general installation tokens.

The gateway/token broker owns provider credential material server-side.

### COR-3 Preserve Existing Builder Corridor

The current builder semantics MUST remain:

- repository-scoped;
- branch prefix `agent/`;
- no protected branch writes;
- no merge;
- no repository admin;
- no protected-path mutation;
- bounded GitHub tool set;
- CI evidence required before `PR_READY_FOR_REVIEW` according to the current workflow.

### COR-4 Canonical Policy Decision

Each request MUST generate a canonical policy decision containing at least:

- decision id;
- timestamp;
- agent/role/runtime identity;
- run/work-item correlation if available;
- repository;
- tool/action;
- canonical argument hash;
- policy version/hash;
- `ALLOW|REVIEW|DENY`;
- reason code;
- grant/credential reference when applicable;
- upstream request/result metadata if forwarded.

### COR-5 Fail Closed for Mutation

A mutating request MUST fail closed when any required element cannot be safely resolved or persisted, including:

- identity;
- policy;
- repository binding;
- protected-path data;
- required evidence write;
- grant/approval in gated mode;
- provider installation/token;
- safe tool normalization.

### EG-1 Exact-change Authorization

For flows that require an explicit grant, the grant SHALL be scoped to the smallest practical action:

- repository;
- action/tool;
- branch;
- protected/non-protected path;
- optional commit/diff/action hash;
- expiry.

Exact PR-SHA / changeset one-shot binding is a D1 expansion requirement and is not required for the first Flight Recorder/Audit release.

### EG-2 GitHub App Installation Token Broker

Preferred enforcement authorization path:

- GitHub App;
- installation/repository scope;
- short-lived token;
- issued only after valid policy/approval where approval is required;
- token not persisted in the agent profile or evidence body.

### EG-3 Bypass Detection and Prevention

Negative tests MUST prove that in enforcement mode managed agents cannot:

- call protected GitHub operations outside the gateway using another available credential;
- use a direct official GitHub MCP path available from the container;
- mutate evidence;
- expand their tool allowlist into effective authority;
- modify protected policy/config paths;
- acquire production/cloud credentials.

---

## 10. Phase 4 — AI Coding Agent Governance Requirements

### GOV-1 Authenticated Policy Editor

An authenticated operator MUST be able to edit supported authority dimensions:

- role/agent;
- repository;
- allowed tool/action;
- branch pattern;
- path allow/deny scope;
- persistent vs temporary validity.

The editor MUST NOT silently expose unsupported admin/merge/production capabilities.

### GOV-2 Versioned Policy

Every accepted policy change MUST create a new policy version containing:

- version id/hash;
- parent version;
- actor;
- timestamp;
- reason;
- before/after diff;
- effective-from;
- expires-at where applicable.

### GOV-3 Temporary Permission

Operator MUST be able to grant an otherwise supported action until an explicit timestamp. Expired grants MUST automatically stop authorizing requests without manual cleanup.

### GOV-4 Revoke / Kill Access

Operator MUST be able to revoke an agent's future GitHub mutation authority at the HermeTeam gateway. Token broker MUST stop minting new tokens for the revoked scope.

Because already-issued provider tokens may remain valid until expiry, configured TTL MUST be short and residual-access semantics MUST be visible to the operator.

### GOV-5 Decision History

Every grant/change/revoke MUST be visible as governance evidence and link to the resulting policy version.

### GOV-6 Drift Alert

When a GitHub scan observes that effective controls changed outside HermeTeam and authority expanded or protection weakened, the UI MUST surface a finding with deterministic severity.

---

## 11. Dashboard Requirements

The current dashboard is intentionally read-only/stateless and exposes `/api/overview`. The product MUST preserve this runtime overview while adding evidence/audit/governance views.

Required views:

1. **Runtime** — current container/role queue overview preserved.
2. **Flight Recorder** — causal execution timeline.
3. **Investigation** — trace + blast radius + evidence completeness.
4. **Authority** — agent/repository effective authority inventory and authority chain.
5. **Findings** — deterministic authority/security findings.
6. **Activity** — policy decisions and mutation evidence.
7. **Governance** — supported permission editor, temporary grants, revoke and history.

Authentication is REQUIRED before any Governance write endpoint or sensitive audit history is exposed beyond the current local loopback trust boundary. A simple local operator session is acceptable for the first control-plane MVP; multi-user enterprise RBAC can be deferred.

---

## 12. Product Workflows

### Workflow A — Observe-only Managed Builder

1. GitHub issue becomes intent.
2. Orchestrator assigns Builder.
3. IDs are propagated to the Hermes run.
4. Tool call is captured through a recorder/interceptor or other supported evidence source.
5. Policy may run informationally in `RECORD_ONLY` mode.
6. Existing role credential may temporarily execute during early observe-mode rollout, but this state MUST be surfaced as a standing-authority finding.
7. Pre/post provider state is captured where possible.
8. Evidence is appended outside agent write authority.
9. Dashboard reconstructs the trace.

No new deny behavior is required in this workflow.

### Workflow B — Authority Audit

1. Operator opens Authority Audit.
2. System lists managed agents/repositories.
3. It derives declared authority from `policies/roles.yaml` + active overrides.
4. GitHub scanner reads actual installation/repository/ruleset controls.
5. Finding engine compares declared and effective authority.
6. Operator drills into activity/evidence and exports the audit package.

### Workflow C — Secure Corridor Builder

1. Intent/run exists.
2. Managed agent sends a GitHub tool request to the Execution Evidence Gateway.
3. Gateway validates identity and repository binding.
4. Gateway captures pre-state and persists initial decision evidence.
5. OPA/effective policy returns ALLOW/REVIEW/DENY.
6. If required, a valid grant/approval is resolved.
7. Token broker obtains a short-lived GitHub App installation token server-side.
8. Gateway performs the allowed upstream call.
9. Post-state/outcome is captured and evidence appended.
10. Direct agent→GitHub mutation path is unavailable in secure deployment.

### Workflow D — Governance

1. Authenticated operator selects agent/repository authority.
2. Operator creates a supported policy change or temporary grant.
3. System validates policy limits.
4. New immutable policy/governance decision is stored.
5. Active policy changes without requiring model-prompt modification.
6. On expiry/revoke, subsequent matching requests are denied and recorded.

---

## 13. Data and Evidence Requirements

The existing role-local orchestrator SQLite DB remains the workflow state store for `work_items`, `role_assignments`, `agent_runs`, `transitions` and polling/deduplication.

A separate central Authority/Evidence store MUST own cross-role/cross-repository security history.

Minimum logical entities across phases:

- intents;
- principals;
- delegations;
- runtime identities;
- evidence events;
- state changes;
- outcomes;
- agents;
- repositories;
- GitHub installations;
- policy versions;
- governance decisions;
- policy decisions;
- upstream actions;
- permission/control snapshots;
- findings;
- grants.

The stores MUST correlate using stable references such as `assignment_key`, `hermes_run_id`, `session_id`, repository id, work-item id and `trace_id`; workflow state MUST NOT become the retention boundary for security evidence.

Every evidence object MUST have a stable id and canonical hash. Append-only semantics are required for event and governance history. Findings may have mutable remediation/status metadata only if original evidence remains preserved.

---

## 14. Security Requirements

1. Agent instructions are behavioral controls, not authorization boundaries.
2. Separate role identities remain mandatory.
3. The evidence/authority service MUST use credentials unavailable to agents.
4. Agent Pods MUST NOT receive Kubernetes service-account tokens.
5. No broad cloud credentials in MVP.
6. Protected paths MUST be enforced server-side in enforcement mode.
7. Evidence tampering and bypass attempts MUST be negative-tested.
8. All evidence schema changes MUST be versioned.
9. Secrets MUST NOT be stored raw in evidence; references/hashes/redaction are required.
10. GitHub App private key MUST never be mounted into Hermes agent containers.
11. Provider installation tokens MUST never be persisted in plaintext evidence logs.
12. Mutating requests in enforcement mode MUST be denied if required decision evidence cannot be recorded.
13. Dashboard write API MUST require authentication before POST/control operations are enabled.
14. Existing loopback-only restrictions remain until authenticated remote deployment is explicitly implemented.
15. Direct managed-agent egress to the official GitHub MCP/API SHOULD be blocked in secure Compose/Kubernetes deployments.
16. Evidence retention MUST be independent from role-local queue/database cleanup.

---

## 15. Non-functional Requirements

### Reliability
Evidence ingestion must not silently lose consequential events. Enforcement mutations fail closed when mandatory evidence cannot be persisted.

### Performance
Observe-only recording should add minimal latency; enforcement mode may add controlled pre/post capture and policy/token latency.

### Portability
The evidence/authority schema should not depend on Hermes internals even though HermeTeam uses Hermes today.

### Privacy
Prompts/tool parameters may be stored by reference/hash/redacted representation. Source code is not stored in evidence by default.

### Explainability
Human-readable timeline and authority reasoning must be reconstructable from stored evidence and reason-coded policy decisions.

### Testability
Every security-critical requirement needs positive and negative tests.

### Compatibility
Existing orchestrator behavior, current runtime `/api/overview`, Compose/Kubernetes deployment patterns and role semantics should remain intact unless a requirement explicitly changes the security path.

---

## 16. Acceptance Criteria by Product Surface

### Flight Recorder MVP

Complete when:

1. A GitHub issue can be represented as an Intent.
2. One agent run receives stable `intent_id` and `trace_id`.
3. Builder consequential GitHub calls are captured.
4. Agent runtime identity is captured.
5. Before/after repository state is recorded for supported writes.
6. Evidence is append-only from the agent perspective.
7. Timeline reconstructs Intent → Agent → Tool → State Change → Outcome.
8. Dashboard can investigate by agent/intent.
9. Evidence completeness is shown.
10. A negative test demonstrates the agent cannot delete/change evidence.

### SDLC Agent Authority Audit MVP

Complete when:

1. Managed agents/repos are inventoried.
2. Effective GitHub controls are scanned or explicitly marked unverifiable.
3. Declared-vs-effective authority comparison runs.
4. At least 15 deterministic rules produce findings.
5. Evidence/activity can be filtered by agent/repo/run/tool/decision.
6. Audit export contains inventory, findings and evidence references.

### Secure GitHub Execution Corridor MVP

Complete when:

1. `hermes-builder` performs normal issue → `agent/*` → push → CI → PR flow through the gateway.
2. Forbidden branch/path/repo/tool canaries are denied before upstream mutation.
3. Managed agents no longer receive reusable GitHub provider credentials.
4. Every managed mutation/deny has a persisted policy decision and correlation identifiers.
5. Direct managed-agent bypass path is removed/blocked in secure deployment.

### AI Coding Agent Governance MVP

Complete when:

1. Governance write endpoints require authentication.
2. Operator can create a supported policy version.
3. Operator can create a temporary grant and observe automatic expiry.
4. Operator can revoke future mutation authority.
5. Governance decisions are visible as immutable history.
6. GitHub effective-control rescan can create a drift finding.

---

## 17. Prioritised Backlog

### P0 — Evidence Foundation / Flight Recorder
- EvidenceEvent schema
- Intent storage
- ID propagation
- consequential GitHub interception/recording
- separate append-only Evidence Store
- before/after SHA capture
- Flight Recorder API
- Investigation UI
- negative evidence-tamper tests

### P1 — Authority Audit
- managed agent/repository inventory
- GitHub control scanner
- declared-vs-effective comparison
- 15 deterministic findings
- Activity/Audit views
- audit export
- runtime hashes/digests
- outcome collector
- blast radius

### P2 — Secure Corridor / Authority Graph
- principal/delegation model
- execution gateway enforcement mode
- OPA reason-coded decisions
- GitHub App token broker
- remove direct provider credentials from managed agents
- no-bypass network controls
- grant/approval model
- temporary grants
- revoke

### P3 — Governance & Scale
- authenticated permission editor
- policy overlay/versioning
- drift handling
- multi-repository governance
- SIEM
- additional adapters
- optional LLM intent/risk controller

---

## 18. Explicit Near-term Non-goals

Do not require for the first Flight Recorder/Audit release:

- Terraform/Kubernetes/cloud mutation;
- production deployment authority;
- exact PR SHA / exact changeset one-shot approval;
- post-execution production-state attestation;
- LLM semantic risk classification;
- automatic SOC2/ISO/EU AI Act mapping;
- full multi-tenant SaaS/SSO/SCIM;
- support for every coding-agent vendor.

These remain future D1/D2 or scale requirements, not blockers for the current GitHub-first product.