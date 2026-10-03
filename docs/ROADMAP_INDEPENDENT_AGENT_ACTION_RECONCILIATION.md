# HermeTeam Roadmap — Independent Agent Action Reconciliation

**Status:** Directional implementation roadmap  
**Date:** 2026-10-03  
**Repository:** `HermeTeam/hermes-sdlc-agents`  
**Primary scope:** GitHub-first independent verification of actual AI-agent actions  
**Product direction:** Independent Agent Action Reconciliation / Evidence Receipt

---

## 1. Purpose

This roadmap defines a separate HermeTeam development track for one specific problem:

> **Independently determine whether the actual external-system effects of an AI-agent action matched the approved intent, policy and authority.**

The target control loop is:

```text
Declared intent / policy
        ↓
Authorized exact request
        ↓
Agent / tool execution
        ↓
Independent provider observation
        ↓
Actual state transition
        ↓
Reconciliation
        ↓
Evidence receipt
```

The direction complements, rather than replaces, the existing HermeTeam Authority Gate.

The Authority Gate answers:

> "Was this exact action allowed to execute?"

Independent reconciliation answers:

> "What actually changed, and did that real change remain inside the approved intent and authority?"

The long-term product boundary is therefore:

> **Intent → Authority → Execution → Independent Observation → Reconciliation → Evidence**

---

## 2. Why this is a separate roadmap

The general HermeTeam roadmap already covers Flight Recorder, capability resolution, Dynamic Authority, GitHub App token brokering, governance and evidence concepts.

This track isolates the post-action verification problem because it has different security properties:

- tool success is not provider-state proof;
- agent-generated telemetry is useful correlation data, but is not independent evidence;
- an authorized request can still have an unexpected or broader effect;
- a real provider change may occur through another credential or path and never appear in the agent trace;
- absence of an observed violation is not proof when evidence collection is incomplete;
- a Git commit does not prove a production deployment, database mutation or business-side effect.

The roadmap therefore treats **provider truth** as a separate source from agent/runtime truth.

---

## 3. Starting point on current `master`

As of 2026-10-03, HermeTeam already has several required primitives.

### Implemented foundations

**Intent / Action Flight Recorder**

`hermes-plugins/hermeteam-intent-action-gate/` records:

- LLM request/response metadata;
- proposed tool calls;
- actual tool requests;
- proposal/action mismatches;
- risk classification;
- tool completion/result hashes;
- structured `HERMETEAM_EVENT` JSONL evidence.

This is useful runtime evidence, but it is generated inside the managed agent runtime and is therefore not sufficient as the only proof of external state.

**Capability / Action Gateway**

`capability_gateway/` already provides a Builder canary with:

- canonical capability mapping;
- deterministic risk;
- repository/branch/path checks;
- exact normalized-argument SHA-256;
- one-shot execution grants;
- emergency stop;
- server-side GitHub App token brokering;
- provider credentials kept out of the agent.

This creates a strong pre-action authority boundary.

**Evidence architecture**

`docs/TRD_EXECUTION_EVIDENCE_GATEWAY.md` already defines:

- `state_before`;
- `state_after`;
- provider-state capture;
- evidence completeness;
- outcome records;
- independent Evidence & Authority Plane.

### Main missing capability

The code does not yet complete the following security loop:

```text
approved exact invocation
      ↓
upstream execution
      ↓
read provider state independently
      ↓
derive actual state change
      ↓
compare actual vs approved
      ↓
persist reconciliation result
```

Closing this gap is the purpose of this roadmap.

---

## 4. Core security invariants

All implementation work in this track must preserve the following invariants.

### IAR-1 — Provider truth is independent

A reconciliation result MUST NOT rely only on:

- model output;
- Hermes hook output;
- MCP tool return payload;
- agent-written logs;
- agent-declared success.

At least one provider-side or independently collected evidence source must support every verified consequential effect.

### IAR-2 — Observer authority is read-only where possible

The independent observer must use separate read-only provider authority from the executor.

The observing identity must not be able to perform the mutation it is verifying.

### IAR-3 — Agent cannot rewrite evidence

The managed agent must not have credentials allowing update/delete of canonical reconciliation evidence or receipts.

### IAR-4 — Unknown is not safe

Missing, stale, ambiguous or inaccessible provider evidence is:

`UNVERIFIABLE`

—not implicitly compliant.

### IAR-5 — Correlation is evidence, not proof of causality

Matching timestamps, branches, run IDs or tool-call IDs can support attribution but do not by themselves prove causation.

Where attribution is not sufficiently supported, use:

`UNATTRIBUTED`

rather than assigning the change to the nearest agent run.

### IAR-6 — Verify the resulting state, not only the API response

For supported mutations, HermeTeam must verify provider state after execution.

### IAR-7 — Production proof requires production evidence

A GitHub commit or merged PR does not prove deployment.

A production claim requires an independent deployment/runtime source such as CI/CD, Kubernetes/cloud control plane, database audit log or another target-system source.

### IAR-8 — Security decision remains deterministic

LLMs may normalize, classify or explain semantic differences, but deterministic policy and evidence rules decide:

- evidence completeness;
- exact-scope matching;
- protected-path violations;
- unexpected resource changes;
- missing provider proof;
- hard reconciliation status.

---

## 5. Canonical reconciliation model

The roadmap introduces four logical records. They may initially live in relational storage; a graph database is not required.

### 5.1 `ProviderObservation`

Represents independently observed provider facts.

Minimum fields:

```text
observation_id
provider
observer_identity
observed_at
resource_type
resource_id
source_reference
source_revision
canonical_hash
completeness
raw_reference
```

Examples:

- GitHub branch ref and commit SHA;
- pull request head/base SHA;
- changed-file set;
- workflow run/check status;
- deployment revision.

### 5.2 `ObservedStateChange`

Represents a normalized before/after effect.

Minimum fields:

```text
change_id
provider
resource
state_before_ref
state_after_ref
change_type
changed_scope
change_hash
observed_at
evidence_refs[]
```

### 5.3 `ReconciliationResult`

Compares declared/authorized action with actual provider effects.

Minimum fields:

```text
reconciliation_id
intent_id
run_id
agent_id
execution_grant_id
tool_call_id
approved_scope
observed_change_ids[]
status
violations[]
unverifiable_dimensions[]
confidence_basis
created_at
```

Canonical statuses:

- `MATCH`
- `PARTIAL_MATCH`
- `OUT_OF_SCOPE`
- `UNATTRIBUTED`
- `UNVERIFIABLE`
- `NO_EFFECT_OBSERVED`

### 5.4 `EvidenceReceipt`

A stable user/auditor-facing artifact that binds:

```text
agent identity
→ intent
→ policy / authority decision
→ exact approved request hash
→ provider observations
→ observed state change
→ reconciliation result
→ outcome evidence
```

The receipt should be hashable, exportable and reproducible from source references.

---

# 6. Roadmap phases

## R0 — Reconciliation contracts and deterministic fixtures

### Goal

Create a stable contract before adding more telemetry or UI.

### Deliverables

1. Add canonical schemas for:
   - provider observation;
   - observed state change;
   - reconciliation result;
   - evidence receipt.
2. Define deterministic reconciliation statuses and rule precedence.
3. Define provider evidence trust levels:
   - authoritative;
   - supporting;
   - runtime-only;
   - unavailable.
4. Define correlation keys:
   - `intent_id`;
   - `run_id`;
   - `agent_id`;
   - `tool_call_id`;
   - `execution_grant_id`;
   - repository/ref/commit identifiers.
5. Build deterministic GitHub fixtures for:
   - exact expected change;
   - additional file changed;
   - wrong branch;
   - protected path changed;
   - tool reports success but state unchanged;
   - provider change without matching agent action;
   - missing observer permission;
   - concurrent unrelated commit.

### Exit gate

R0 is complete when the same fixture always produces the same reconciliation status without calling an LLM.

---

## R1 — Independent GitHub Observer MVP

### Goal

Establish provider-side evidence outside the agent runtime.

### Initial scope

GitHub only:

- branch refs;
- commit SHAs;
- commit/tree/file metadata;
- pull requests;
- changed files;
- GitHub Actions/check evidence where available.

### Architecture

Use a separate observer identity from the execution GitHub App token path.

Preferred model:

```text
Agent
  │
  ▼
Capability Gateway
  │ mutation credential
  ▼
GitHub
  │
  ├──────────────► agent/runtime telemetry
  │
  └──────────────► independent read-only observer
                         │
                         ▼
                 ProviderObservation
```

The observer must not reuse agent credentials.

### Ingestion paths

Support two complementary paths:

1. **Active read-after-write verification**
   - gateway schedules/requests provider reads immediately after a consequential mutation;
   - provider state is read using observer authority.

2. **Asynchronous provider event ingestion**
   - GitHub webhook or equivalent event source;
   - used to detect changes that did not pass through the managed action path.

Neither path alone is sufficient for all cases.

### First supported operations

#### Branch creation

Verify:

- branch did not exist or expected pre-state;
- resulting ref exists;
- resulting head SHA equals expected source/base SHA.

#### File push / commit

Verify:

- prior branch head;
- resulting branch head;
- commit SHA;
- changed path set;
- blob/tree refs where available;
- diff/change hash.

#### Pull request creation/update

Verify:

- PR number;
- head/base branches;
- head/base SHAs;
- changed-file hash;
- current state.

### Required failure behavior

- missing observer permission → `UNVERIFIABLE`;
- provider read timeout → `UNVERIFIABLE`;
- result payload says success but provider state unchanged → `NO_EFFECT_OBSERVED`;
- provider state changes beyond approved scope → candidate `OUT_OF_SCOPE`.

### Exit gate

A Builder mutation can be independently reconstructed from provider state without trusting the MCP result payload.

---

## R2 — GitHub Reconciliation Engine

### Goal

Compare actual provider effects with the exact approved scope.

### Inputs

**Intended/authorized state**

From existing HermeTeam components:

- intent;
- normalized tool;
- canonical capability;
- repository;
- branch/ref;
- path scope;
- arguments hash;
- policy result;
- one-shot grant;
- provider permission scope.

**Actual state**

From R1:

- provider observations;
- derived state change;
- changed resource/path set;
- resulting commit/ref/PR state.

### Deterministic MVP rules

At minimum detect:

1. expected repository differs from observed repository;
2. expected branch differs from observed ref;
3. observed changed path not present in approved scope;
4. protected path changed;
5. expected mutation produced no observable state change;
6. more resources changed than approved;
7. observed commit cannot be linked to the authorized request;
8. agent action completed but provider proof is missing;
9. provider mutation appeared with no matching HermeTeam execution record;
10. multiple candidate agent actions make attribution ambiguous.

### Semantic intent comparison

Do **not** make LLM semantic judgement a required security boundary in R2.

Optional shadow-mode semantic analysis may answer:

> "Does this diff still appear consistent with the higher-level task intent?"

Its output is advisory and separate from deterministic scope reconciliation.

### Exit gate

For a supported GitHub mutation, HermeTeam can state one of:

`MATCH / PARTIAL_MATCH / OUT_OF_SCOPE / UNATTRIBUTED / UNVERIFIABLE / NO_EFFECT_OBSERVED`

and list the evidence used to reach that status.

---

## R3 — Evidence Receipt and investigation surface

### Goal

Turn reconciliation into a usable security/audit artifact.

### Receipt contents

Each consequential action receipt should show:

- initiating principal/task where available;
- agent and runtime identity;
- declared intent;
- selected capability/tool;
- authority source;
- exact normalized request hash;
- provider token scope/fingerprint reference without exposing the token;
- provider observations;
- actual commit/ref/PR effects;
- approved-vs-observed comparison;
- missing evidence;
- reconciliation status;
- receipt hash;
- source references.

### Dashboard

Add an investigation view separate from aggregate Langfuse monitoring.

Minimum views:

**Action timeline**

```text
Intent
  ↓
Proposal
  ↓
Requested action
  ↓
Authority decision
  ↓
Execution
  ↓
Provider observation
  ↓
Observed state change
  ↓
Reconciliation
```

**Violation view**

Show:

- approved scope;
- observed scope;
- exact difference;
- evidence source;
- why the result was classified;
- whether the evidence is complete.

### Export

Support a machine-readable JSON receipt first.

Human-readable Markdown/PDF export can follow, but must be derived from the same canonical receipt rather than a separate manually assembled report.

### Exit gate

An operator can reconstruct a supported action without reading raw agent logs.

---

## R4 — Evidence completeness and bypass detection

### Goal

Detect when HermeTeam cannot safely claim that it observed the whole action chain.

### Required completeness dimensions

At minimum:

```text
principal
intent
runtime_identity
tool_call
policy_decision
authority
provider_observation
state_before
state_after
outcome
artifact_integrity
```

### Bypass / drift scenarios

Detect or surface:

- provider mutation not correlated to a managed agent action;
- mutation using a credential path outside Capability Gateway;
- missing webhook sequence / stale observer cursor;
- expected provider event never observed;
- observer permissions insufficient for required resource;
- mismatched GitHub App installation/repository scope;
- multiple independent mutations inside one reconciliation window;
- provider-state read inconsistent with event stream.

### Important semantics

`NO VIOLATION FOUND` and `VERIFIED MATCH` are different states.

Only a complete enough evidence chain may produce `VERIFIED MATCH`.

### Exit gate

HermeTeam can explicitly distinguish:

- verified compliant action;
- verified violation;
- unattributed provider change;
- incomplete evidence;
- unverifiable provider state.

---

## R5 — Shadow-mode product pilot

### Goal

Prove customer value before making reconciliation part of the blocking path.

### Operating mode

The system observes and reconciles but does not block the agent based on post-action findings.

This is the preferred first commercial/adoption mode.

### Pilot scope

Start with:

- one repository;
- Builder role;
- GitHub branch/commit/PR actions;
- one independent observer identity;
- deterministic reconciliation only.

### Canonical demo

Approved action:

> Modify `src/api.py` on `agent/fix-123`.

Actual provider state:

```text
src/api.py                       changed
.github/workflows/deploy.yml     changed
```

Expected HermeTeam result:

```text
status: OUT_OF_SCOPE

approved:
  repository: org/repo
  branch: agent/fix-123
  paths:
    - src/api.py

observed:
  paths:
    - src/api.py
    - .github/workflows/deploy.yml

violations:
  - unexpected_path
  - protected_path_changed
```

The evidence must include real GitHub commit/tree references, not only agent telemetry.

### Pilot success metrics

Track:

- consequential actions observed;
- percentage independently reconciled;
- `MATCH` rate;
- `OUT_OF_SCOPE` findings;
- `UNATTRIBUTED` provider mutations;
- `UNVERIFIABLE` rate and reasons;
- reconciliation latency;
- false-positive investigations;
- time to reconstruct one agent action.

### Exit gate

The pilot demonstrates at least one real or controlled mismatch that is visible from provider evidence and not dependent on the agent self-report.

---

## R6 — Feedback into Authority / Enforce Mode

### Goal

Use observed violations to improve future authority decisions without conflating observation with authorization.

### Additions

1. Policy suggestions from repeated reconciliation findings.
2. Optional tighter path/resource constraints for future grants.
3. Automatic escalation to human approval when prior evidence shows unstable scope.
4. Deny known bypass paths when enforcement coverage is complete.
5. Evidence-required postconditions for selected high-risk actions.

### Example

```text
historical reconciliation:
  tool push_files repeatedly changes generated CI file

future request:
  same action pattern
        ↓
  require human approval
        or
  narrow execution mechanism
```

### Constraint

Post-action findings may inform future policy, but a model-generated explanation must never silently rewrite authorization policy.

### Exit gate

A previously observed out-of-scope pattern can be converted into a deterministic preventive control with explicit operator approval.

---

## R7 — CI/CD and production-state reconciliation

### Goal

Extend the proof chain beyond repository state.

GitHub alone can prove source-control effects, but cannot prove production outcome.

### Next adapters

Priority order:

1. GitHub Actions / CI execution;
2. deployment system;
3. Kubernetes/cloud control plane;
4. database audit logs;
5. selected external business systems.

### Target chain

```text
approved source change
      ↓
commit / PR
      ↓
CI artifact
      ↓
deployment revision
      ↓
production resource state
      ↓
verified outcome
```

### Example

Intent:

> Deploy release SHA X to staging.

Independent verification must prove:

- workflow/deployment was actually triggered;
- deployed revision is X;
- target environment is staging;
- resulting workload revision matches X;
- no unexpected production target changed.

### Exit gate

HermeTeam can distinguish:

- source change;
- release action;
- deployment;
- verified production effect.

---

## R8 — Cross-system Agent Action Reconciliation

### Goal

Generalize the architecture only after the GitHub/CI model is proven.

Potential providers:

- cloud APIs;
- Kubernetes;
- SQL databases;
- CRM/ERP;
- payment systems;
- messaging systems;
- external SaaS APIs.

### Generic abstraction

```text
ActionIntent
    ↓
ApprovedCapability
    ↓
ExternalExecution
    ↓
ProviderObservation[]
    ↓
ObservedStateChange[]
    ↓
ReconciliationResult
    ↓
EvidenceReceipt
```

The provider adapter owns evidence normalization; the reconciliation engine owns generic comparison semantics.

### Rule

Do not build a generic "AI security platform" abstraction before GitHub reconciliation has demonstrated reliable provider-state proof.

---

# 7. Implementation order

The recommended implementation sequence is:

```text
R0 contracts + deterministic fixtures
        ↓
R1 independent GitHub observer
        ↓
R2 reconciliation engine
        ↓
R3 evidence receipt + investigation UI
        ↓
R4 completeness / bypass detection
        ↓
R5 shadow pilot
        ↓
R6 authority feedback
        ↓
R7 CI/CD + production state
        ↓
R8 cross-system adapters
```

Do not reverse this sequence by starting with a broad cross-system event bus or generic agent-security dashboard.

The first proof must be:

> **HermeTeam independently detects that the real GitHub state differs from what the agent was authorized to change.**

---

# 8. Relationship to existing HermeTeam components

| Existing component | Role in this roadmap |
| --- | --- |
| `hermeteam-intent-action-gate` | Runtime/proposal/action correlation evidence |
| Langfuse | LLM trace and performance context; not provider-state proof |
| `capability_gateway` | Pre-action capability/risk/authority boundary |
| Dynamic Authority | Exact invocation grant and provider credential containment |
| GitHub App broker | Execution credential source; must remain separate from observer identity |
| `policies/*` | Declared policy and protected scope |
| Dashboard | Investigation and receipt UX |
| Existing TRD evidence model | Canonical architectural basis for state-before/state-after/outcome |
| Orchestrator | Workflow correlation source; not canonical evidence owner |

---

# 9. Recommended service boundaries

The exact folder layout may evolve, but responsibilities should remain separated.

### Capability / Action Gateway

Owns:

- pre-action request normalization;
- deterministic authorization;
- exact execution grant;
- credential brokering;
- upstream execution.

Must not become the only evidence source.

### Provider Observer

Owns:

- provider events;
- independent provider reads;
- canonical provider observations;
- observer cursors/completeness metadata.

Must not hold mutation authority.

### Evidence & Reconciliation Core

Owns:

- immutable/append-oriented evidence;
- state-change derivation;
- correlation;
- reconciliation;
- completeness;
- receipt generation.

### Dashboard / API

Owns:

- investigation;
- difference visualization;
- receipt rendering/export;
- operator drill-down.

It must not contain the authoritative reconciliation logic.

---

# 10. Test strategy

Every supported mutation type needs positive and negative provider-state tests.

### Positive

- exact approved branch created;
- exact approved files changed;
- expected PR created;
- expected commit observed;
- exact state produces `MATCH`.

### Negative

- extra changed path;
- protected file changed;
- wrong branch;
- wrong repository;
- no provider effect despite tool success;
- provider change without tool record;
- tool record without provider proof;
- ambiguous concurrent commits;
- observer permission removed;
- stale/missed webhook;
- attempt to attribute unrelated human commit to agent.

### Adversarial principle

Tests must assert provider state independently.

A mocked model refusal, agent log line or MCP `success=true` alone does not satisfy a reconciliation test.

---

# 11. Product metrics

The roadmap should be evaluated with evidence-quality metrics, not only event volume.

Primary:

- **Independent reconciliation coverage** — % of consequential actions with provider evidence.
- **Verified match rate** — % of actions with sufficiently complete evidence that reconcile to approved scope.
- **Unverifiable rate** — % where evidence is insufficient.
- **Unattributed mutation rate** — provider mutations not confidently tied to a managed action.
- **Out-of-scope detection rate** — verified actions with effects outside approved scope.
- **Evidence latency** — execution to completed receipt.
- **Investigation time** — time for an operator to explain one consequential agent action.

Secondary:

- observer API cost;
- webhook loss/recovery rate;
- false-positive reconciliation rate;
- receipt generation latency;
- storage growth per consequential action.

---

# 12. Non-goals for the first implementation

Do not make the GitHub reconciliation MVP into:

- a generic SIEM;
- a generic IAM product;
- a full cloud security platform;
- a universal event-sourcing framework;
- a blockchain evidence store;
- an LLM-based causal oracle;
- an automatic incident-response system;
- a production deployment attestation product before source-control reconciliation works;
- a replacement for GitHub audit logs, SIEM or provider-native controls.

---

# 13. Productization path

The natural adoption path is:

```text
OBSERVE
independent provider evidence
        ↓
RECONCILE
approved vs actual
        ↓
PROVE
evidence receipt
        ↓
INVESTIGATE
timeline / blast radius
        ↓
GOVERN
policy refinement
        ↓
ENFORCE
prevent repeated patterns
```

This gives HermeTeam a low-friction entry mode while preserving the stronger Authority Gate expansion path.

---

# 14. Definition of the first complete MVP

The Independent Agent Action Reconciliation MVP is complete when all of the following are true:

1. Builder performs a real supported GitHub mutation through the managed path.
2. HermeTeam records the approved exact request and authority decision.
3. A separate read-only observer independently reads the resulting GitHub state.
4. HermeTeam derives the actual changed scope from provider evidence.
5. The deterministic reconciliation engine compares actual scope with approved scope.
6. An intentionally injected extra/out-of-scope change is detected.
7. The result is persisted as an Evidence Receipt with provider references.
8. The dashboard can show approved vs actual differences.
9. Missing provider evidence produces `UNVERIFIABLE`, not `MATCH`.
10. A provider-side mutation without a matching agent record is surfaced as `UNATTRIBUTED`.
11. No agent credential can update/delete the canonical receipt.
12. The same result can be reconstructed from persisted evidence and source references.

The first MVP explicitly does **not** need to block the action.

Its primary proof is:

> **HermeTeam can independently prove whether a real AI-agent GitHub action stayed inside its authorized intent and scope.**

---

# 15. Strategic outcome

If this roadmap is completed, HermeTeam evolves from:

> a system that controls what an AI agent is allowed to request

into:

> **a system that independently proves whether the real-world effect of an AI-agent action matched the authority that was granted.**

That creates a stronger joined model:

```text
INTENT
  ↓
CAPABILITY
  ↓
AUTHORITY
  ↓
EXECUTION
  ↓
PROVIDER TRUTH
  ↓
RECONCILIATION
  ↓
EVIDENCE RECEIPT
```

The durable product asset is not raw telemetry. It is the continuously accumulated mapping between:

- what an agent intended;
- what authority it had;
- what it requested;
- what the external system actually changed;
- whether those facts match;
- and the evidence proving the result.
