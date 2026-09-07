# HermeTeam — Product Requirements Document (PRD)
## Version 2.0 — Flight Recorder → Authority Graph → Evidence-Gated Execution

**Status:** Updated canonical PRD  
**Date:** 2026-09-07  
**Primary MVP:** GitHub-first Agent Action Evidence / Flight Recorder  
**Expansion:** Authority Graph + Execution Evidence Gateway

---

## 1. Product Objective

Build a GitHub-first system that independently records consequential AI-agent execution, reconstructs causal chains from human intent to outcome, and can later use the same evidence graph to enforce bounded authority before state changes occur.

The product MUST support an adoption sequence:

`Observe → Record → Prove → Investigate → Authorize → Gate → Execute → Prove`

---

## 2. MVP User Story

As a Head of AI Security,

I want to see every consequential GitHub action performed by an AI coding agent, linked to the human intent, agent identity, delegated authority, policy decision, state transition and resulting outcome,

so that I can investigate incidents and prove what happened without trusting the agent's own logs.

---

## 3. Product Personas

### Security Owner
Needs evidence completeness, incident reconstruction and audit export.

### Platform Engineer
Needs minimal integration friction and deterministic APIs.

### Agent Platform Owner
Needs agent-framework neutrality and correlation IDs.

### Auditor / Incident Responder
Needs immutable, understandable, exportable causal evidence.

---

## 4. Current Product Baseline

HermeTeam already has:

- isolated roles (`planner`, `project-manager`, `builder`, `reviewer`, `release`, `incident`, `learning`);
- separate containers/Pods and API keys;
- role-specific GitHub credentials;
- GitHub MCP integration;
- exact native tool allowlists;
- OPA policy examples;
- protected-path rules;
- branch restrictions;
- orchestrator issue discovery and run submission;
- SQLite state/deduplication;
- read-only dashboard;
- validation/smoke tests.

The PRD extends these primitives rather than replacing them.

---

## 5. Phase 1 — Flight Recorder Requirements

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
- `signature` or server attestation

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
- status

### FR-3 Correlation Propagation

`trace_id`, `intent_id`, `agent_id`, and relevant `delegation_id` SHALL propagate across:

- orchestrator discovery;
- Hermes run submission;
- provider/MCP tool invocation;
- policy evaluation;
- evidence collection;
- state capture;
- outcome collection.

### FR-4 Runtime Identity

Every consequential event SHALL capture enough runtime identity to answer “which agent instance did this?”

Minimum target fields:

- role
- agent instance ID
- model/provider where available
- container image digest
- profile/config hash
- `SOUL.md` hash
- policy bundle hash
- tool configuration hash

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

Example:

- principal ✓
- intent ✓
- delegation ✕
- agent identity ✓
- policy ✓
- before state ✓
- after state ✓
- outcome ✕

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

## 6. Phase 2 — Authority Graph Requirements

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
- `parent_delegation_id`

### AG-3 Authority Reconstruction

For any action, API/UI SHALL show the authority chain that existed at execution time.

### AG-4 Grant History

Grant creation, renewal, revocation and expiry MUST be retained as evidence.

### AG-5 Unknown Authority

If no valid delegation/grant can be resolved, the action MUST be marked as `AUTHORITY_UNPROVEN` even when the provider accepted it.

---

## 7. Phase 3 — Evidence-Gated Execution Requirements

### EG-1 Execution Evidence Gateway

All protected consequential operations SHALL flow through:

`PRE-CAPTURE → POLICY/AUTHORITY → EXECUTE → POST-CAPTURE`

### EG-2 Exact-change Authorization

The grant SHALL be scoped to the smallest practical action:

- repository;
- action/tool;
- branch;
- protected/non-protected path;
- optional commit/diff/action hash;
- expiry.

### EG-3 GitHub App Installation Token Broker

Preferred authorization path:

- GitHub App;
- installation/repository scope;
- short-lived token;
- issued only after valid policy/approval;
- token not persisted in agent profile.

### EG-4 User Approval UX

When an action requires approval, the dashboard SHALL offer:

- one-time;
- temporary;
- persistent policy-based approval where permitted.

Approval history becomes evidence.

### EG-5 Grant Editor

The user SHALL be able to inspect and revoke active agent authority.

### EG-6 Policy Decision Capture

Every allow/review/deny decision SHALL be persisted with:

- policy version/hash;
- evaluated inputs;
- decision;
- reason;
- authority/grant reference.

### EG-7 Bypass Detection

Negative tests MUST prove agents cannot:

- call protected GitHub operations outside the gateway using another available credential;
- mutate evidence;
- expand their tool allowlist;
- modify protected policy/config paths;
- acquire production/cloud credentials.

---

## 8. Dashboard Requirements

### Page: Overview

Show:

- active agents;
- consequential actions;
- incomplete evidence;
- denied/review events;
- top repositories touched;
- latest intents.

### Page: Flight Recorder

Timeline from intent to outcome.

### Page: Incident Investigation

Interactive causal tree and blast radius.

### Page: Authority

Principal → delegation → agent → grant → action graph.

### Page: Governance

Later phase:

- inventory;
- grants;
- expiry;
- revoke;
- drift;
- findings.

---

## 9. Product Workflows

### Workflow A — Observe-only Builder

1. GitHub issue becomes intent.
2. Orchestrator assigns Builder.
3. IDs are propagated to Hermes run.
4. Tool call is captured.
5. GitHub provider executes with existing role credential.
6. State after is captured.
7. Evidence is appended.
8. Dashboard reconstructs the trace.

No blocking behavior is introduced.

### Workflow B — Investigation

1. Security selects suspicious agent/intent.
2. HermeTeam loads all correlated evidence.
3. It builds timeline and causal graph.
4. It reports blast radius.
5. Missing evidence is highlighted.
6. Evidence package can be exported.

### Workflow C — Evidence-Gated Builder

1. Intent is created.
2. Delegation is resolved.
3. Gateway captures pre-state.
4. Policy evaluates exact action.
5. If required, human approves.
6. Token broker issues short-lived token.
7. action executes;
8. post-state/outcome is captured.
9. signed evidence is persisted.

---

## 10. Security Requirements

- Agent instructions are behavioral controls, not authorization boundaries.
- Separate role credentials remain mandatory.
- The evidence service MUST use credentials unavailable to agents.
- Agent Pods MUST NOT receive Kubernetes service-account tokens.
- No broad cloud credentials in MVP.
- Protected paths MUST be enforced server-side.
- Evidence tampering and bypass attempts MUST be negative-tested.
- All evidence schema changes MUST be versioned.
- Secrets MUST NOT be stored raw in evidence; references/hashes/redaction are required.

---

## 11. Non-functional Requirements

### Reliability
Evidence ingestion should not silently lose consequential events.

### Performance
Observe-only recording should add minimal latency; enforcement mode may add controlled pre/post capture latency.

### Portability
The schema should not depend on Hermes internals even though HermeTeam uses Hermes today.

### Privacy
Prompts/tool parameters may be stored by reference/hash/redacted representation.

### Explainability
Human-readable timeline must be reconstructable from the stored graph.

### Testability
Every security-critical requirement needs positive and negative tests.

---

## 12. MVP Acceptance Criteria

Phase 1 is MVP-complete when:

1. A GitHub issue can be represented as an Intent.
2. One agent run receives a stable `intent_id` and `trace_id`.
3. Builder consequential GitHub calls are captured.
4. Agent runtime identity is captured.
5. Before/after repository state is recorded for supported writes.
6. Evidence is append-only from the agent perspective.
7. Timeline reconstructs Intent → Agent → Tool → State Change → Outcome.
8. Dashboard can investigate by agent/intent.
9. Evidence completeness is shown.
10. A negative test demonstrates the agent cannot delete/change evidence.

---

## 13. Prioritised Backlog

### P0
- EvidenceEvent schema
- Intent storage
- ID propagation
- Builder GitHub interception
- append-only Evidence Store
- before/after SHA capture
- Flight Recorder API
- Investigation UI
- negative evidence-tamper tests

### P1
- Delegation model
- runtime hashes/digests
- evidence completeness
- outcome collector
- signed export
- blast radius

### P2
- GitHub App token broker
- approval UX
- temporary grants
- revoke
- Authority Graph UI
- drift detection

### P3
- additional roles/adapters
- SIEM
- organisation inventory
- LLM intent/risk controller
