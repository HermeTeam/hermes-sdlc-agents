# HermeTeam — Business Requirements Document (BRD)
## Version 2.1 — Agent Action Evidence / Authority / Secure Execution / Governance

**Status:** Updated canonical business requirements  
**Date:** 2026-09-07  
**Product:** HermeTeam  
**Repository:** `HermeTeam/hermes-sdlc-agents`

---

## 1. Executive Summary

HermeTeam is the evidence and authority layer between AI intent and consequential software state change.

The commercial entry point is no longer only “prevent an AI coding agent from exceeding its authority.” The first adoption wedge is:

> **Independently record, reconstruct and prove what an AI agent actually did before asking the customer to put HermeTeam in the blocking path.**

The product therefore evolves in four technical phases:

1. **Flight Recorder** — OBSERVE → RECORD → PROVE → INVESTIGATE.
2. **Authority Graph** — WHO DELEGATED WHAT → TO WHICH AGENT → WITH WHAT SCOPE → FOR HOW LONG.
3. **Evidence-Gated Execution** — PRE-CAPTURE → POLICY/AUTHORITY → EXECUTE → POST-CAPTURE.
4. **Governance & Scale** — inventory, drift, permission editing, auditor packages, additional systems and organisation-wide policy.

HermeTeam remains GitHub-first. Existing Safe Builder / bounded Issue → PR automation remains the operational substrate for teams that already want controlled autonomy. Flight Recorder is the lower-friction entry mode because it can start observe-first. The same underlying evidence and authority plane is then packaged commercially as **SDLC Agent Authority Audit**, **Secure GitHub Execution Corridor**, and **AI Coding Agent Governance**.

---

## 2. Business Problem

AI agents are moving from recommendation to execution in software delivery systems. A single human instruction can produce multiple sub-agents, tool calls, repository mutations, CI actions and downstream state changes.

Existing systems expose fragments:

- GitHub knows repository actions;
- CI knows test/build results;
- identity systems know principals and credentials;
- LLM observability products know prompts/traces;
- SIEM platforms know security events;
- policy engines know allow/deny decisions.

The buyer still cannot reliably answer the full causal question:

> **Who intended the change, who delegated authority, which agent acted, through which tool and policy decision, what state changed, and what was the verified outcome?**

Nor can the buyer reliably answer the operational authority question:

> **Which AI agents can change which repositories today, which effective GitHub controls actually constrain them, and where does effective authority exceed declared policy?**

This is the business gap HermeTeam addresses.

---

## 3. Core Business Thesis

The durable control layer is not only authorization. It is the complete chain:

`Intent → Principal → Delegation → Agent Identity → Tool Call → Policy Decision → Authorization → State Before → State Change → State After → Outcome → Evidence`

The product must support three orthogonal questions:

1. **Evidence:** What did the agent actually do and can we independently prove it?
2. **Authority:** Was this agent allowed to perform this action at that time?
3. **Effective control:** Could the agent have done more than policy intended because provider credentials, repository rules or runtime paths were broader than declared authority?

The evidence layer must sit outside the agent's write authority. In enforcement mode, the protected execution path must also sit outside the agent's ability to bypass or reconfigure it.

---

## 4. Target Customers

### 4.1 Initial ICP

Engineering organisations using AI coding or autonomous SDLC agents against real repositories and CI/CD.

Initial characteristics:

- GitHub is the primary source-code platform;
- at least one AI coding agent can create branches, commits or pull requests;
- security or platform teams need bounded autonomy;
- the organisation is unwilling to hand agents broad human PATs or production credentials;
- auditability, incident response or governance is becoming material;
- the team needs to understand or reduce the blast radius of coding-agent credentials and repository permissions.

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
- Engineering manager / AI-agent operator
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

### JTBD-6 — Authority audit

“Show me every managed coding agent, its effective repository authority, and concrete gaps between declared policy and GitHub reality.”

### JTBD-7 — Permission operations

“Let an authorized operator change, temporarily expand or revoke supported coding-agent authority without editing several YAML files and credentials manually.”

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
- GitHub effective-control scanner;
- declared-vs-effective authority comparison;
- deterministic findings;
- permission/policy editor;
- temporary grants and expiry;
- revoke / kill access;
- drift detection;
- multi-repository policy;
- SIEM/export;
- auditor packages;
- additional adapters beyond GitHub/MCP;
- optional LLM intent/risk controller.

---

## 7. Commercial Product Surfaces

The technical phases above are not required to be sold as separate products. HermeTeam SHOULD expose three coherent commercial packages over one shared Evidence & Authority Core.

### 7.1 SDLC Agent Authority Audit

A read-mostly security product built from Flight Recorder + Authority Graph + GitHub control scanning.

It answers:

- which agents/roles exist;
- which repositories they can reach;
- which tools/actions policy declares;
- which provider permissions and repository controls are effective;
- what the agents actually did;
- where declared and effective authority differ;
- which authority gaps are critical/high/medium.

This is the broadest low-friction commercial entry after Flight Recorder because it can demonstrate value before the customer delegates blocking authority to HermeTeam.

### 7.2 Secure GitHub Execution Corridor

An enforcement package for customers ready to route managed-agent GitHub mutations through HermeTeam.

The business promise is:

> **A managed coding agent can create bounded GitHub changes, but cannot escape its repository/tool/branch/path authority even if the model is compromised, hallucinating or prompt-injected.**

The corridor MUST retain GitHub-native branch protection/rulesets and CI as independent controls; HermeTeam does not replace them.

### 7.3 AI Coding Agent Governance

A control-plane package over the same evidence/authority model.

It adds:

- policy versions;
- supported permission editing;
- temporary permissions;
- revoke / kill access;
- decision history;
- drift findings;
- authenticated governance UX.

The packages share one identity, policy, evidence, GitHub App, scanner and audit model. They MUST NOT become three independent implementations.

---

## 8. Business Requirements

### BR-01 — Independent Evidence

Evidence required to prove agent actions MUST be stored outside the agent's ability to update or delete.

### BR-02 — Causal Traceability

Every consequential action MUST be linkable to an `intent_id`, `trace_id`, `agent_id`, and where applicable a `delegation_id`.

### BR-03 — State Proof

For supported consequential operations, HermeTeam MUST record sufficient information to establish the relevant before and after state.

### BR-04 — Outcome Proof

The system SHOULD verify whether the intended technical outcome occurred rather than recording only tool-call success.

### BR-05 — Progressive Adoption

A customer MUST be able to deploy Flight Recorder / Authority Audit before enabling blocking enforcement.

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

When Evidence-Gated Execution / Secure Corridor is enabled, the protected action path MUST not be bypassable using alternate credentials or direct provider paths available to the managed agent.

### BR-12 — GitHub-first Scope

The first production corridor targets GitHub repository/PR/Actions workflows. GitLab and broad cloud execution are roadmap items.

### BR-13 — Effective Authority Inventory

HermeTeam MUST be able to represent, per managed agent/role/repository, declared permissions, credential source, provider repository scope, branch/path controls and relevant GitHub protection state.

### BR-14 — Declared-vs-Effective Audit

HermeTeam MUST identify material cases where effective GitHub authority is broader or materially less protected than declared HermeTeam policy.

### BR-15 — Governable Authority

An authorized operator MUST be able to inspect and, for supported dimensions, version, temporarily grant and revoke coding-agent authority. Governance decisions MUST become evidence.

### BR-16 — Credential Containment

In enforcement mode, managed agent containers MUST NOT hold reusable GitHub PATs or GitHub App private-key material. Short-lived provider credentials are brokered server-side.

### BR-17 — Separation of Workflow and Security Evidence

Role-local orchestrator workflow state and cross-role authority/evidence state are different business lifecycles. The security/evidence plane MUST be independently retainable and MUST NOT be deletable as a side effect of queue/runtime lifecycle operations.

### BR-18 — Product Interoperability

Flight Recorder, Authority Audit, Secure Corridor and Governance MUST use the same canonical identity, policy-decision and evidence model so that customers can move from observe → audit → govern/enforce without re-onboarding agents or losing historical evidence.

---

## 9. Existing Assets to Reuse

The current repository already provides important primitives:

- isolated Hermes roles;
- separate containers / Pods;
- separate inbound API keys;
- role-specific GitHub credentials as the current baseline;
- exact MCP tool allowlists;
- server-side OPA/Rego policy definitions;
- protected branch/path model;
- immutable release candidate concept;
- no Kubernetes service-account tokens in agent Pods;
- read-only shared skills;
- GitHub API/MCP execution;
- orchestrator;
- local SQLite work-item/run/deduplication state;
- read-only runtime dashboard;
- validation and smoke tests.

These are not discarded. They become the workflow/runtime substrate under the evidence and authority model.

---

## 10. Commercial Entry Sequence

### Entry A — Flight Recorder / Authority Audit

Low-friction, observe-first deployment.

Expected sales motion:

- connect GitHub / supported execution evidence source;
- record execution for one or two agents;
- scan actual repository/App controls;
- show evidence gaps, authority findings and blast radius;
- prove incident/audit value.

### Expansion B — Authority Graph

Use recorded traces and declared policy to reconstruct delegated authority.

### Expansion C — Secure GitHub Execution Corridor

Turn observed violations and authority gaps into enforceable policies and short-lived execution credentials.

### Expansion D — AI Coding Agent Governance

Add permission operations, temporary grants, revoke, version history and drift response across repositories/teams.

### Expansion E — Cross-system Evidence-Gated Execution

Extend the same model to CI/CD, infrastructure and production state attestation.

---

## 11. Non-Goals for Initial MVP

The initial Flight Recorder / Authority Audit MVP is NOT:

- a general SIEM;
- an LLM observability product;
- a replacement for GitHub;
- a replacement for CI/CD;
- a generic IAM platform;
- a full GRC suite;
- a Kubernetes/cloud administration platform;
- blockchain-based audit storage;
- autonomous merge or production deployment;
- exact PR-SHA / changeset one-shot authorization as a mandatory Phase-1 feature;
- post-execution production-state attestation outside GitHub.

---

## 12. Business Success Metrics

### Evidence / Audit

- percentage of consequential agent actions captured;
- evidence completeness rate;
- percentage of events correlated to an intent;
- mean time to reconstruct an agent incident;
- number of evidence gaps detected;
- number of authority findings by severity;
- percentage of managed agents/repositories with current effective-authority snapshots;
- time to produce an audit/evidence package.

### Corridor / Governance

- percentage of actions with provable authority chain;
- percentage of managed GitHub mutations with persisted policy decision;
- zero successful forbidden mutation canaries;
- reduction in standing/reusable agent credentials;
- temporary-grant usage and expiry correctness;
- denied/brought-to-review unsafe actions;
- bypass attempts detected/blocked;
- number of teams moving from observe-only to enforcement;
- time to revoke an agent's future mutation authority.

---

## 13. Product Positioning

### Category

**Agent Execution Evidence & Authority Control**

### One-line positioning

> **HermeTeam provides independent evidence and bounded authority for AI agents that change software systems.**

### Stronger technical positioning

> **HermeTeam is the evidence and authority layer between AI intent and consequential state change.**

### Entry-product positioning

> **Agent Flight Recorder and Authority Audit for GitHub-first AI software teams.**

### Enforcement positioning

> **Secure GitHub Execution Corridor for managed AI coding agents.**

---

## 14. Strategic Moat

The target moat is the joined causal and authority graph, not raw logging and not a single approval primitive:

- human intent;
- delegated authority;
- exact runtime identity;
- action and policy decision;
- declared vs effective provider authority;
- before/after state;
- verified outcome;
- independent evidence;
- grant/decision history;
- drift over time.

The product becomes more defensible as customers rely on this graph for investigation, policy authoring, approval history, blast-radius analysis, permission operations and auditor evidence.

---

## 15. Roadmap

### R1 — Flight Recorder MVP
- EvidenceEvent schema
- IDs propagated end-to-end
- GitHub consequential action capture
- runtime identity
- append-only evidence store
- state before/after
- evidence completeness
- investigation UI

### R1.5 — SDLC Agent Authority Audit
- managed agent/repository inventory
- GitHub App/repository effective-control scanner
- declared-vs-effective comparison
- deterministic authority findings
- Activity/Evidence view
- audit export

### R2 — Authority Graph
- principals
- delegations
- grants
- expiry
- history

### R3 — Secure GitHub Execution Corridor / Execution Evidence Gateway
- mandatory gateway for protected managed-agent mutations
- server-side OPA enforcement
- GitHub App/token broker
- removal of direct GitHub credentials from managed agents
- pre-capture
- exact authorization where supported
- execute
- post-capture
- adversarial no-bypass tests

### R4 — AI Coding Agent Governance
- authenticated policy editor
- versioned policies
- temporary grants
- revoke
- scanner/inventory
- drift detection
- decision history
- multi-repository policy

### R5 — Cross-system Governance & Scale
- CI/CD / Terraform / Kubernetes / cloud adapters
- production-state attestation
- SIEM/export
- auditor packages
- optional LLM intent-risk controller

---

## 16. Final Business Requirement

HermeTeam MUST be deployable first as an independent evidence/audit layer and later as an enforcement/governance layer using the same causal graph and policy model. The adoption path MUST NOT require the customer to trust HermeTeam with blocking authority before HermeTeam has demonstrated value through evidence and investigation; when enforcement is enabled, the protected path MUST become technically non-bypassable for managed agents.