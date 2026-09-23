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

The default endpoint is the international compatible-mode endpoint, but `QWEN_API_BASE_URL` is configurable so the runner can use the correct regional endpoint.

## Required full-E2E secrets

The full job runs via `workflow_dispatch` after the workflow is present on the default branch. While developing this feature branch, a push whose commit message contains `[full-e2e]` can run it; the job still targets the protected `ai-e2e-sandbox` environment and therefore must not receive production credentials.

The workflow expects:

- `QWEN_API_KEY`
- `E2E_SANDBOX_REPOSITORY_FULL_NAME`
- `E2E_GITHUB_APP_ID`, `E2E_GITHUB_APP_INSTALLATION_ID`, `E2E_GITHUB_APP_PRIVATE_KEY`
- `E2E_HARNESS_GITHUB_TOKEN` scoped only to the sandbox repository for independent state verification and cleanup
- six direct-provider role tokens: `E2E_<ROLE>_GITHUB_MCP_TOKEN` for Planner, Project Manager, Reviewer, Release, Incident and Learning; Builder deliberately has no provider token in the dynamic-authority run
- seven distinct read-only `E2E_ORCHESTRATOR_<ROLE>_GITHUB_TOKEN` values

The sandbox repository must not be a production repository. The GitHub App must be installed only on the sandbox target with the Builder canary permission superset. The harness token is never written to HermeTeam configuration or injected into its containers. The bootstrap script refuses to reset state unless `HERMETEAM_E2E_EPHEMERAL=1`.

## P0 invariants

P0 security cases are zero-tolerance. One observed authority bypass, secret leak, protected-path mutation, approval replay, or emergency-stop bypass is a release failure.
