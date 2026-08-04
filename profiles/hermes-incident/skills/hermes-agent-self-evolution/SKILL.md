---
name: hermes-agent-self-evolution
description: "Improve SDLC agents through reviewed proposals."
version: 1.0.0
author: "SDLC Platform Team"
license: "MIT"
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [sdlc, learning, evals, skills, improvement]
    category: software-development
    related_skills: []
---

# Hermes Agent Self-Evolution Skill

Use this skill to turn repeated SDLC agent failures into safe, testable improvement proposals. It adapts the `hermes-agent-self-evolution` workflow for the SDLC role fleet without granting agents new write or activation powers.

This skill never overrides the current role's `SOUL.md`, MCP allowlist, approval policy, or production boundary. If those instructions conflict with this skill, follow the stricter role policy.

## When to Use

- A task reveals repeated failures, unclear instructions, weak acceptance criteria, poor review signal, brittle release gates, or noisy incident handling.
- Human feedback asks for an agent behavior change, skill improvement, prompt clarification, or evaluation gate.
- A post-incident, PR review, release decision, or planning loop produces evidence that the SDLC agent fleet can improve.
- The user explicitly asks to use self-evolution, improve an agent, evolve a skill, or prepare a learning proposal.

## Prerequisites

- Work only inside the current role's allowed zone.
- Use only the tools exposed to this role by `config.yaml` and the SDLC MCP gateway.
- Do not request or inspect secrets, PII, raw customer payloads, unrestricted logs, or unrelated session content.
- Treat `hermes-agent-self-evolution` as an offline optimization implementation detail. Run it only when the current role has explicit file and terminal access to an approved checkout and the task authorizes local evaluation.
- Skill installation, activation, publication, and direct mutation remain governed by `skills.write_approval: true` and human review.

## How to Run

For non-learning roles:

1. Capture the observed failure or improvement opportunity.
2. Minimize the evidence to role-safe, non-sensitive facts.
3. Create a handoff item for `hermes-learning` instead of changing skills or prompts directly.
4. Continue the original role workflow and final status.

For `hermes-learning`:

1. Read aggregated outcomes, failure clusters, feedback, docs, and skills catalog through the allowed SDLC MCP tools.
2. Build a proposal with measurable hypothesis, minimal diff, evaluation dataset, acceptance thresholds, risks, and rollback.
3. Attach candidate changes as a staged proposal only.
4. Finish with `PROPOSED_FOR_HUMAN_REVIEW`, not `activated`, `installed`, `published`, or `deployed`.

## Quick Reference

| Role | Allowed self-evolution action |
|---|---|
| `hermes-planner` | Identify spec or planning failure patterns and hand off improvement evidence. |
| `hermes-builder` | Identify implementation, test, or tooling friction and hand off verified evidence. |
| `hermes-reviewer` | Identify review rubric gaps, missing tests, or recurring defect classes and hand off evidence. |
| `hermes-release` | Identify gate, metric, rollout, or rollback policy gaps and hand off evidence. |
| `hermes-incident` | Identify runbook, telemetry, or mitigation policy gaps and hand off evidence. |
| `hermes-learning` | Create reviewed proposals for skills, docs, prompts, or evals; do not self-approve. |

## Procedure

1. Define the improvement target: role, version, affected workflow, and observed failure mode.
2. Record evidence IDs, timestamps, work item IDs, PR IDs, release candidate IDs, incident IDs, or aggregate cluster IDs.
3. Remove sensitive data and reduce examples to the smallest useful context.
4. State the baseline behavior and why it is insufficient.
5. Propose the smallest skill, doc, prompt, or evaluation change that addresses the pattern.
6. Define an offline evaluation dataset: positive examples, negative examples, regression cases, and expected decisions.
7. Define acceptance thresholds: correctness, safety, refusal behavior, false positive limits, and required checks.
8. Check conflict with role boundaries, protected paths, quality gates, and security policy.
9. For non-learning roles, stop at a handoff. For `hermes-learning`, create or update the proposal and attach the diff.
10. Include rollback: how to remove the change and what signal triggers rollback.

## Pitfalls

- Do not treat one anecdote as a fleet-wide rule.
- Do not optimize for passing a single example while weakening safety or separation of duties.
- Do not add new agent powers when a clearer instruction, narrower MCP contract, or better evaluation is enough.
- Do not change protected CI, quality gates, deployment policy, or production behavior as part of learning.
- Do not use self-evolution to bypass human approval, reviewer independence, or release policy.

## Verification

Every proposal or handoff must include:

- Evidence source and sensitivity classification.
- Baseline and expected behavior.
- Candidate diff or exact requested change.
- Evaluation dataset outline and thresholds.
- Security, privacy, and role-boundary impact.
- Owner, review path, rollback plan, and expiry or reassessment date.

If local `hermes-agent-self-evolution` execution is explicitly authorized, the candidate must pass its constraint gates before proposal submission: tests, size limits, semantic preservation, and human-review readiness.
