# HermeTeam AI E2E Verification Plane

This directory contains the first implementation slice of the AI-native E2E verification pipeline.

## Execution order

0. **Bootstrap HermeTeam from scratch** in an ephemeral runner.
1. Validate repository, policy, scenario and model contracts.
2. Probe the configured Qwen API models.
3. Start the full HermeTeam stack and verify all seven role APIs through Hermes.
4. Run deterministic unit/policy/authority suites.
5. Run dashboard production-image E2E.
6. Run P0 scenario and adversarial suites as they are promoted from manifests to executable harnesses.
7. Collect evidence and only then permit an LLM judge to score semantic behavior.

The deterministic oracle is authoritative for security invariants. An LLM judge may add semantic findings but may never turn a deterministic hard failure into PASS.

## Qwen model stack

The pipeline uses Qwen API Platform through its OpenAI-compatible API.

- Planner / Project Manager / Reviewer: `qwen3.7-max`
- Builder / Release / test driver: `qwen3.7-plus`
- Incident / Learning / JSON repair: `qwen3.5-flash`
- E2E Architect / Adversary / Judge / Triage: `qwen3.7-max`

The default endpoint is the international compatible-mode endpoint, but `QWEN_API_BASE_URL` is configurable so the runner can use the correct regional endpoint.

## Required full-E2E secrets

The workflow expects:

- `QWEN_API_KEY`
- `E2E_SANDBOX_REPOSITORY_FULL_NAME`
- seven distinct `E2E_<ROLE>_GITHUB_MCP_TOKEN` values
- seven distinct read-only `E2E_ORCHESTRATOR_<ROLE>_GITHUB_TOKEN` values

The sandbox repository must not be a production repository. The bootstrap script refuses to reset state unless `HERMETEAM_E2E_EPHEMERAL=1`.

## P0 invariants

P0 security cases are zero-tolerance. One observed authority bypass, secret leak, protected-path mutation, approval replay, or emergency-stop bypass is a release failure.
