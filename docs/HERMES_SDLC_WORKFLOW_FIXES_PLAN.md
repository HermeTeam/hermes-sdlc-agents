# Hermes SDLC Workflow Fixes Plan

## Goal

Close the workflow risks found in `hermes-sdlc-agents` before enabling automatic provider transitions: prevent self-generated duplicate assignments, make timeout/invalid-output visible in provider state, make transitions retry-safe, expose transition flags in runtime, clarify comment-only canary semantics, and close the release terminal path.

## Scope

- Orchestrator runtime in `orchestrator/sdlc_orchestrator/*`.
- Compose, Kubernetes, and `.env.example` transition flag propagation.
- Unit tests in `orchestrator/tests/*`.
- Documentation updates for changed workflow semantics.

Out of scope: merge/deploy/production tools, broad provider permissions, enabling transition mutations by default, and full PR discovery without a real Hermes/GitHub payload fixture.

## Work Items

1. Fix assignment revision keys so issue revisions use semantic requirement content, not provider `updated_at`.
2. Add provider-visible failure transitions for local and upstream timeouts.
3. Add provider-visible failure transitions for invalid final JSON output.
4. Make GitHub transitions retry-safe with deterministic comment markers and idempotent missing-label removal.
5. Expose `ORCHESTRATOR_APPLY_TRANSITIONS` and `ORCHESTRATOR_TRANSITION_COMMENT_ONLY` in `.env.example`, Compose, Kubernetes, and validation.
6. Filter pending assignments by role to avoid cross-role starts if a DB is shared accidentally.
7. Detect stale active-run completions when the work item semantic revision changed before reconciliation.
8. Make `status` output show transition flags so operators can distinguish disabled, comment-only canary, and label-changing modes.
9. Add release terminal transitions for `NO_ACTION` and `BLOCKED_NO_ACTION`.
10. Add tests for revision keys, role-filtering, timeout/invalid/stale failure transitions, comment-only behavior, release terminal labels, and GitHub 404 label removal.

## Rollout

1. Keep `ORCHESTRATOR_APPLY_TRANSITIONS=false` and verify strict JSON reconciliation plus transition rows.
2. Enable `ORCHESTRATOR_APPLY_TRANSITIONS=true` with `ORCHESTRATOR_TRANSITION_COMMENT_ONLY=true`; this creates comments only and does not start downstream label-based agents.
3. After audit, enable `ORCHESTRATOR_TRANSITION_COMMENT_ONLY=false` on a non-production test repository.
4. Verify planner -> builder -> reviewer -> release -> terminal with idempotency evidence.

## Definition of Done

- No duplicate assignments from orchestrator comments/labels.
- Timeout, invalid output, and stale completions create transition rows and provider-visible comments when enabled.
- Provider transitions are safe to retry.
- Transition flags are present in runtime environments.
- Pending assignments are role-filtered.
- Release outcomes close or mark terminal provider state.
- Tests and structural validation pass.
