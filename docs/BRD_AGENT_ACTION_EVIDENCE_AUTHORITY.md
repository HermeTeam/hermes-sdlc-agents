# HermeTeam — Business Requirements Document (BRD)
## Version 2.0 — Agent Action Evidence / Authority / Evidence-Gated Execution

**Status:** Updated canonical business requirements  
**Date:** 2026-09-07  
**Product:** HermeTeam  
**Repository:** `HermeTeam/hermes-sdlc-agents`

---

## 1. Executive Summary

HermeTeam is the evidence and authority layer between AI intent and consequential software state change.

The commercial entry point is no longer only “prevent an AI coding agent from exceeding its authority.” The first wedge is now:

> **Independently record, reconstruct and prove what an AI agent actually did before asking the customer to put HermeTeam in the blocking path.**

The product therefore evolves in four phases:

1. **Flight Recorder** — OBSERVE → RECORD → PROVE → INVESTIGATE.
2. **Authority Graph** — WHO DELEGATED WHAT → TO WHICH AGENT → WITH WHAT SCOPE → FOR HOW LONG.
3. **Evidence-Gated Execution** — PRE-CAPTURE → POLICY/AUTHORITY → EXECUTE → POST-CAPTURE.
4. **Governance & Scale** — inventory, drift, auditor packages, additional systems and organisation-wide policy.

HermeTeam remains GitHub-first. Safe Builder remains the operational SDLC product for teams that already want bounded autonomous Issue → PR work. Flight Recorder is the lower-friction entry product because it can start in read-mostly / observe-first mode.

---

## 2. Business Problem

AI agents are moving from recommendation to execution in software delivery systems. A single human instruction can produce multiple sub-agents, tool calls, repository mutations, CI actions and downstream state changes.

Existing systems expose fragments:

- GitHub knows repository actions.
- CI knows test/build results.
- identity systems know principals and credentials.
- LLM observability products know prompts/traces.
- SIEM platforms know security events.
- policy engines know allow/deny decisions.

The buyer still cannot reliably answer the full causal question:

> **Who intended the change, who delegated authority, which agent acted, through which tool and policy decision, what state changed, and what was the verified outcome?**

This is the business gap HermeTeam addresses.

---

## 3. Core Business Thesis

The durable control layer is not only authorization. It is the complete chain:

`Intent → Principal → Delegation → Agent Identity → Tool Call → Policy Decision → Authorization → State Before → State Change → State After → Outcome → Evidence`

The product must support two orthogonal questions:

1. **Authority:** Was this agent allowed to perform this action?
2. **Evidence:** What did the agent actually do and can we independently prove it?

The evidence layer must sit outside the agent's write authority.

---

## 4. Target Customers

### 4.1 Initial ICP

Engineering organisations using AI coding or autonomous SDLC agents against real repositories and CI/CD.

Initial characteristics:

- GitHub is the primary source-code platform.
- at least one AI coding agent can create branches, commits or pull requests;
- security or platform teams need bounded autonomy;
- the organisation is unwilling to hand agents broad human PATs or production credentials;
- auditability, incident response or governance is becoming material.

### 4.2 Buyer Personas

**Primary buyer**
- Head of AI Security
- CISO / Deputy CISO
- Head of Platform Security

**Technical champion**
- Platform Engineering Lead
- DevSecOps Lead
- Staff/Principal Engineer responsible for AI developer tooling

**Secondary buyers**
- Internal Audit
- Incident Response
- Governance / Risk
- Cyber-insurance control owner
- CTO in smaller engineering organisations

---

## 5. Jobs to Be Done

### JTBD-1 — Incident reconstruction

“When an AI agent changes something consequential, show me everything caused by that intent and prove the blast radius.”

### JTBD-2 — Agent accountability

“Show which principal delegated which rights to which agent and whether those rights were valid at execution time.”

### JTBD-3 — Evidence completeness

“Tell me whether I have enough independent evidence to explain this action to security, audit or incident response.”

### JTBD-4 — Safe autonomy

“Allow low-risk work to proceed autonomously while independently protecting high-risk authority.”

### JTBD-5 — Progressive governance

“Let me start read-only, then add warnings, approvals and enforcement without replacing my agent framework.”

---

## 6. Product Hierarchy

### Phase 1 — HermeTeam Flight Recorder

**Goal:** cheapest possible adoption and fastest proof of value.

Capabilities:

- canonical agent execution event stream;
- intent, trace, delegation and agent identity correlation;
- consequential tool-call capture;
- before/after state evidence;
- append-only evidence store;
- evidence completeness;
- incident reconstruction;
- blast-radius view;
- signed evidence export.

**Business promise:**

> “Deploy HermeTeam without changing who can merge. Get an independent record of what autonomous agents actually did.”

### Phase 2 — HermeTeam Authority Graph

Capabilities:

- principal graph;
- delegation graph;
- scope / limits / expiry;
- parent-child delegation;
- grant history;
- relation between authority and execution evidence.

**Business promise:**

> “For every agent action, trace the right back to the principal who delegated it.”

### Phase 3 — HermeTeam Execution Evidence Gateway

Capabilities:

- pre-action capture;
- server-side policy evaluation;
- exact-action authorization;
- short-lived credential/token issuance;
- execution through controlled corridor;
- post-action state capture;
- approval/revoke;
- evidence-gated execution.

**Business promise:**

> “No critical repository change without valid authority and sufficient evidence.”

### Phase 4 — Governance & Scale

Capabilities:

- authority inventory;
- drift detection;
- governance UI;
- multi-repository policy;
- SIEM/export;
- auditor packages;
- additional adapters beyond GitHub/MCP;
- optional LLM intent/risk controller.

---

## 7. Business Requirements

### BR-01 — Independent Evidence

Evidence required to prove agent actions MUST be stored outside the agent's ability to update or delete.

### BR-02 — Causal Traceability

Every consequential action MUST be linkable to an `intent_id`, `trace_id`, `agent_id`, and where applicable a `delegation_id`.

### BR-03 — State Proof

For supported consequential operations, HermeTeam MUST record sufficient information to establish the relevant before and after state.

### BR-04 — Outcome Proof

The system SHOULD verify whether the intended technical outcome occurred rather than recording only tool-call success.

### BR-05 — Progressive Adoption

A customer MUST be able to deploy Flight Recorder before enabling blocking enforcement.

### BR-06 — Independent Authorization

Model prompts, `SOUL.md`, tool visibility and agent instructions MUST NOT be treated as security boundaries.

### BR-07 — Least Privilege

Agent credentials MUST be role-scoped, repository-scoped where possible, short-lived where possible and separated by role.

### BR-08 — Human Authority Retention

Merge and production authority remain human or separately controlled unless explicitly delegated through policy.

### BR-09 — Evidence Completeness

HermeTeam MUST expose whether a causal chain is complete, incomplete or unverifiable.

### BR-10 — Investigation

The buyer MUST be able to query execution by intent, agent, repository, time range and affected state.

### BR-11 — Non-bypassability for Enforcement Mode

When Evidence-Gated Execution is enabled, the protected action path MUST not be bypassable using alternate credentials available to the agent.

### BR-12 — GitHub-first Scope

The first production corridor targets GitHub repository/PR/Actions workflows. GitLab and broad cloud execution are roadmap items.

---

## 8. Existing Assets to Reuse

The current repository already provides important primitives:

- isolated Hermes roles;
- separate containers / Pods;
- separate inbound API keys;
- role-specific GitHub credentials;
- exact MCP tool allowlists;
- server-side OPA examples;
- protected branch/path model;
- immutable release candidate concept;
- no Kubernetes service-account tokens in agent Pods;
- read-only shared skills;
- GitHub API/MCP execution;
- orchestrator;
- local SQLite deduplication;
- dashboard;
- validation and smoke tests.

These are not discarded. They become the execution and control substrate under the evidence model.

---

## 9. Commercial Entry Sequence

### Entry A — Flight Recorder

Low-friction, observe-first deployment.

Expected sales motion:
- connect GitHub / MCP path;
- record execution for one or two agents;
- show evidence gaps and blast radius;
- prove incident/audit value.

### Expansion B — Authority Graph

Use the recorded traces to reconstruct actual delegated authority.

### Expansion C — Evidence-Gated Execution

Turn observed violations and evidence gaps into enforceable policies.

### Expansion D — Organisation-wide Governance

Expand across repositories, teams and execution systems.

---

## 10. Non-Goals for Initial MVP

The MVP is NOT:

- a general SIEM;
- an LLM observability product;
- a replacement for GitHub;
- a replacement for CI/CD;
- a generic IAM platform;
- a full GRC suite;
- a Kubernetes/cloud administration platform;
- blockchain-based audit storage;
- autonomous merge or production deployment.

---

## 11. Business Success Metrics

### Phase 1 metrics

- percentage of consequential agent actions captured;
- evidence completeness rate;
- percentage of events correlated to an intent;
- mean time to reconstruct an agent incident;
- number of evidence gaps detected;
- number of affected repositories/actions reconstructed per incident;
- number of teams moving from observe-only to enforcement.

### Phase 2/3 metrics

- percentage of actions with provable authority chain;
- temporary-grant usage;
- denied/brought-to-review unsafe actions;
- bypass attempts detected;
- reduction in standing agent privileges;
- time to answer audit/incident questions.

---

## 12. Product Positioning

### Category

**Agent Execution Evidence & Authority Control**

### One-line positioning

> **HermeTeam provides independent evidence and bounded authority for AI agents that change software systems.**

### Stronger technical positioning

> **HermeTeam is the evidence and authority layer between AI intent and consequential state change.**

### Entry-product positioning

> **Agent Flight Recorder for GitHub-first AI software teams.**

---

## 13. Strategic Moat

The target moat is the joined causal graph, not raw logging:

- human intent;
- delegated authority;
- exact runtime identity;
- action and policy decision;
- before/after state;
- verified outcome;
- independent evidence.

The product becomes more defensible as customers rely on this graph for investigation, policy authoring, approval history and auditor evidence.

---

## 14. Roadmap

### R1 — Flight Recorder MVP
- EvidenceEvent schema
- IDs propagated end-to-end
- GitHub consequential action capture
- runtime identity
- append-only evidence store
- state before/after
- evidence completeness
- investigation UI

### R2 — Authority Graph
- principals
- delegations
- grants
- expiry
- history

### R3 — Execution Evidence Gateway
- pre-capture
- policy
- exact authorization
- temporary GitHub App installation tokens
- execute
- post-capture
- approvals/revoke

### R4 — Governance & Scale
- scanner/inventory
- drift
- SIEM/export
- auditor packages
- additional adapters
- optional LLM intent-risk controller

---

## 15. Final Business Requirement

HermeTeam MUST be deployable first as an independent evidence layer and later as an enforcement layer using the same causal graph. The adoption path MUST NOT require the customer to trust HermeTeam with blocking authority before HermeTeam has demonstrated value through evidence and investigation.
