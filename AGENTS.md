# HermeTeam Repository Agent Contract

This file applies repository-wide to every human-assisted or autonomous coding agent working in `HermeTeam/hermes-sdlc-agents`.

Nested instructions may add stricter rules for a subtree, but they must not weaken the security, authority, documentation, or `master` merge requirements defined here.

## Repository invariants

- Model behavior is not an authorization boundary.
- Preserve role separation, least privilege, protected-path constraints, branch constraints, human approval boundaries, one-shot grant semantics, credential isolation, emergency-stop behavior, and provider-state verification.
- Do not replace a bounded capability with a broader one merely to make a test or deployment pass.
- Do not expose provider credentials, private keys, governance keys, dashboard secrets, or resolved secret-bearing configuration in logs, PR descriptions, issues, documentation, or learning artifacts.
- Treat `master` as the canonical integration branch. Repository documentation and operational skills must describe the behavior that will exist on `master` after the merge, not an older architecture.

## Required sources before changing behavior

Before modifying runtime, deployment, security, authority, orchestration, observability, or agent behavior, inspect the current relevant sources rather than relying on cached knowledge. At minimum consider:

- `README.md` / `README_RU.md`;
- relevant files under `docs/`;
- `compose.yaml` and applicable `compose.*.yaml` overlays;
- `.env.example` and component-specific environment examples;
- `profiles/hermes-*/config.yaml` and `SOUL.md` where role behavior changes;
- `policies/roles.yaml`, `policies/mcp-policy.rego`, and `policies/protected-paths.txt` where authority changes;
- `scripts/validate.sh`, smoke/canary scripts, and CI workflows;
- `skills/hermeteam-deploy-evolve/SKILL.md` for deployment, recovery, canary, authority, observability, and self-evolution behavior.

Current executable code and effective rendered configuration are stronger evidence than stale prose documentation.

# Mandatory merge-to-master functionality review

Every pull request targeting `master` that adds, removes, or changes repository functionality MUST perform a functionality-impact review before merge.

This is a merge gate, not an optional documentation cleanup.

## 1. Compare the PR with current master

Review the complete diff against the current `master` head, including conflict-resolution changes made immediately before merge.

Identify all user-visible, agent-visible, operator-visible, security-relevant, deployment-relevant, API, configuration, policy, workflow, and operational behavior that is new or changed.

Do not limit the review to files named in the original task. Follow transitive effects across services, overlays, policies, tests, docs, and role contracts.

## 2. Build a functionality change inventory

For each changed behavior record, at minimum:

- component/service/role affected;
- previous behavior;
- new behavior;
- configuration or environment changes;
- authority/security impact;
- deployment/upgrade/rollback impact;
- API/UI/CLI/operator impact;
- tests/canaries used to verify the change;
- documentation that must change;
- `hermeteam-deploy-evolve` skill impact.

A PR with functional changes is not merge-ready until this inventory has been considered, even when implementation tests are green.

## 3. Verify the changed functionality

Run the narrowest sufficient tests plus the repository-wide checks required by the affected surface.

Common checks include:

```bash
scripts/validate.sh
python3 -m unittest discover -s capability_gateway/tests -v
npm --prefix dashboard ci
npm --prefix dashboard run check
docker compose config --quiet
```

When Compose overlays are affected, render the applicable combinations, for example:

```bash
docker compose \
  -f compose.yaml \
  -f compose.capability-gateway.yaml \
  -f compose.dynamic-authority.yaml \
  config --quiet
```

Add or update targeted positive and negative tests/canaries for new behavior. Security-sensitive changes require provider-state verification where applicable; a model saying that it refused an action is not sufficient evidence.

Never weaken or delete a failing security check merely to make the merge gate pass.

## 4. Update corresponding documentation in the same PR

If functionality changed, update every document whose description, setup instructions, architecture, permissions, API, canary, recovery procedure, limitation, or operational expectation is no longer accurate.

Typical targets include:

- `README.md` and `README_RU.md` for product/architecture statements;
- `docs/bootstrap.md` and `docs/bootstrap_ru.md` for deployment changes;
- `docs/DYNAMIC_REQUEST_AUTHORITY.md` for authority-path changes;
- component READMEs for component contracts;
- operations, provider integration, dashboard, policy, and architecture docs as applicable;
- environment examples when variables/defaults/contracts change.

Do not merge known documentation drift with a promise to fix it later unless the PR is an emergency security remediation and the follow-up is explicitly tracked and approved.

## 5. Reconcile `hermeteam-deploy-evolve` in the same PR

Every functional PR MUST assess the effect on:

```text
skills/hermeteam-deploy-evolve/SKILL.md
```

Update the skill in the same PR whenever the change affects any of the following:

- bootstrap prerequisites or host requirements;
- repository discovery/source precedence;
- environment variables, secrets, credentials, or identity setup;
- Compose services, overlays, ports, networks, health checks, volumes, or startup order;
- role count, role boundaries, tool surfaces, provider permissions, or protected paths;
- Capability Gateway, Dynamic Authority, approval semantics, risk policy, GitHub App authority, or emergency stop;
- dashboard/governance workflows used during deployment or verification;
- Flight Recorder, Langfuse, or other observability used by the deployment canary;
- validation commands, CI checks, smoke tests, positive/negative canaries, or expected evidence;
- orchestrator enablement, run-once behavior, retries, deduplication, or lifecycle controls;
- shutdown, rollback, recovery, incident response, or credential-rotation behavior;
- known limitations or the criteria for declaring a deployment successful;
- any repository change that makes a current skill statement or branch decision stale.

When the skill changes:

1. make the smallest correct change;
2. update its version when behavior changes materially;
3. preserve the parent security invariants;
4. add/update regression scenarios for the changed branch;
5. keep self-evolution proposal-driven — the active skill must not self-approve or self-activate a learned candidate.

If a functional PR truly has no effect on the deployment skill, the PR must state:

```text
HermeTeam Deploy & Evolve skill impact: NONE — <specific reason>
```

Do not use `NONE` when the change modifies a command, required dependency, configuration contract, authority boundary, canary expectation, or deployment-visible behavior.

## 6. Merge-readiness declaration

Before merge to `master`, the PR description or final review note must include a compact declaration covering:

```text
Functionality reviewed: YES
Changed behavior: <summary>
Validation: <commands/checks and result>
Documentation impact: UPDATED | NONE (<reason>)
HermeTeam Deploy & Evolve skill impact: UPDATED | NONE (<reason>)
Security/authority impact: <summary>
Known limitations / follow-ups: <summary or none>
```

If any required line is unknown, stale, or unsupported by evidence, the PR is not ready to merge.

## 7. Re-check after conflict resolution or last-minute changes

If the PR head changes after the functionality review — including conflict resolution, rebase, merge-from-master, generated-file refresh, or last-minute fix — re-run the impact review for the new head before merging.

A review of an older commit does not satisfy this gate.

# Deployment skill ownership and evolution

The repository-owned operator skill lives at:

```text
skills/hermeteam-deploy-evolve/
```

It is an operator/deployment skill, not an implicit grant of host or provider authority to normal HermeTeam SDLC roles.

Its active version is immutable during a deployment session. Deployment evidence may produce a candidate patch or specialized fork, but activation/publication/merge of a learned version requires human review. Normal HermeTeam roles remain constrained by their own `SOUL.md`, tool allowlists, approval policy, and provider authority.

When repository behavior changes, prefer updating the base skill when the new behavior is generally true. Create a specialized fork only when the behavior is genuinely environment-specific or version-specific.

# Protected merge principle

A green implementation test suite alone does not make a functional change merge-ready.

For `master`, code, effective configuration, tests/canaries, documentation, and the deployment/self-evolution skill must describe the same system.
