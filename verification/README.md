# HermeTeam AI E2E Verification Plane

This directory contains the first implementation slice of the AI-native E2E verification pipeline.

## Execution order

0. **Bootstrap HermeTeam from scratch** in an ephemeral runner.
1. Validate repository, policy, scenario and model contracts.
2. Probe the configured Qwen API models.
3. Start the full HermeTeam dynamic-authority stack and verify all seven role APIs through Hermes.
4. Run deterministic unit/policy/authority suites.
5. Run dashboard production-image E2E.
6. Run live sandbox canaries: Qwen Builder safe branch/file/PR, protected-path hard deny, emergency stop, exact one-shot approval and changed-args rejection.
7. Generate additional adversarial variants with an independent Qwen agent.
8. Collect sanitized provider/runtime evidence and only then permit an independent Qwen judge to score semantic behavior.

The deterministic oracle is authoritative for security invariants. An LLM judge may add semantic findings but may never turn a deterministic hard failure into PASS.

## Qwen model stack

The pipeline uses Qwen API Platform through its OpenAI-compatible API.

- Planner / Project Manager / Reviewer: `qwen3.7-max`
- Builder / Release / test driver: `qwen3.7-plus`
- Incident / Learning / JSON repair: `qwen3.5-flash`
- E2E Architect / Adversary / Judge / Triage: `qwen3.7-max`

`QWEN_API_BASE_URL` is mandatory for the full job and must be the actual OpenAI-compatible Base URL from the Qwen API key or Token Plan account. Pay-as-you-go, Token Plan and regional Model Studio endpoints are not interchangeable. The bootstrap refuses to silently substitute another endpoint. Run `verification/check_prerequisites.py` first to report all missing credential names without exposing their values.

## Required full-E2E secrets and variables

Full E2E runs only in the protected `ai-e2e-sandbox` environment and against a dedicated non-production repository.

- `QWEN_API_KEY` (secret) and `QWEN_API_BASE_URL` (variable, matching the key).
- `E2E_SANDBOX_REPOSITORY_FULL_NAME` (variable; not the HermeTeam source repository).
- `E2E_GITHUB_APP_ID`, `E2E_GITHUB_APP_INSTALLATION_ID` (variables), and `E2E_GITHUB_APP_PRIVATE_KEY` (secret).

**Do not configure 6 role-scoped GitHub MCP PATs, 7 orchestrator PATs or a harness PAT.** Stage 00 generates 14 distinct *internal HermeTeam* Gateway keys. The independent verifier mints its own short-lived, sandbox-restricted GitHub App installation tokens in the test runner; they are never given to AI agents or orchestrator containers.

The full job can be started on a trusted branch push with `[full-e2e]` or by workflow_dispatch when available; privileged credentials must not be exposed to untrusted PR code. The bootstrap refuses to reset any state without `HERMETEAM_E2E_EPHEMERAL=1`.

## Current coverage boundary

`verification/verify_authority_topology.py` inspects **resolved Compose**, requires each of the seven role containers to use Gateway MCP and each role-local orchestrator to use the typed internal Gateway endpoint, and fails if a provider token or GitHub App key reaches a role. This is a configuration test, **not proof that an orchestrator has executed an Issue transition**. Stage 00 deliberately keeps `ORCHESTRATOR_ENABLED=false`. Credentialed live canaries now also attempt forbidden GitHub writes from the six non-Builder roles (with independent branch-state checks), verify that Planner cannot impersonate Builder, perform issue-list reads through all seven internal orchestrator Gateway identities, and reject orchestrator role spoofing. The pipeline now also includes a disposable sandbox Issue test for an exact, human-approved, one-shot orchestrator comment, including independent GitHub provider-state verification and replay denial. These live canaries are **authored but not yet verified by a credentialed full run**; they do not establish coverage for every MCP tool or for unattended scheduler behavior.

For migration scope and outstanding security gates see `docs/ROADMAP_GITHUB_APP_AUTHORITY_ALL_ROLES.md`.

## P0 invariants

P0 security cases are zero-tolerance. One observed authority bypass, secret leak, protected-path mutation, approval replay, or emergency-stop bypass is a release failure.

## Required release-gate evidence

The full job writes a Stage 00 report, a separate readiness result for all seven role APIs, real GitHub provider-state canary results, and six execution markers written only after their corresponding commands exit successfully. `verification/build_evidence.py` fails closed if a report, role or gate marker is absent or indicates failure. This prevents a manually invoked evidence builder from fabricating a green report.

The dashboard browser test is mandatory in the full job: unavailable Docker/Chromium/Playwright must fail rather than return SKIP. The independent Qwen judge is advisory for semantics but is a required release gate: `NEEDS_REVIEW` or any coverage gap blocks success. Generated adversarial variants are test inputs, not evidence that those attacks have been executed.

The feature-branch `[full-e2e]` trigger consumes the credentials configured in the `ai-e2e-sandbox` GitHub environment. An absent secret or regional Qwen URL is a blocking prerequisite, not a reason to silently skip Stage 00. The sandbox repository must be separate from the source repository.
