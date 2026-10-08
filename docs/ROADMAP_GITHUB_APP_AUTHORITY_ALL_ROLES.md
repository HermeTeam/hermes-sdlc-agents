# Migration: GitHub App authority for all HermeTeam roles

**Base branch:** `feature/qwen-e2e-verification-pipeline` (stacked PR).
**Security objective:** Give coding agents GitHub access without giving them GitHub credentials.
**Status:** Implementation in progress. Do not merge into the Qwen E2E branch until the negative/positive canaries and the full sandbox test are green.

## Implementation progress (2026-10-08)

| Workstream | Implemented in this branch | Outstanding |
|---|---|---|
| P0 role policy | `role_authority.py` enforces default-deny role/tool/repository, Builder protected branches/paths; `mcp_proxy.py` authenticates role-bound keys | Discovery still uses Builder write-capable compatibility token; implement and live-test narrow discovery + tool visibility filtering |
| P1 seven roles | `compose.dynamic-authority.yaml` overrides every agent MCP endpoint/token with internal key; Gateway role map validates actual call before mint | Six non-Builder hard-deny GitHub provider-state canaries are authored; execute them on the credentialed sandbox, then validate permitted upstream MCP tool/permission semantics |
| P2 orchestrators | Typed `orchestrator_rest.py` facade, internal `github_gateway.py` client, cron key propagation; deny unknown paths/roles; exact human approval for any state change; seven-role live read/impersonation canaries authored | Enable orchestrators in isolated sandbox and exercise issue read, approval-granted transition, replay, failure recovery; review operational UX of approval requests |
| P3 bootstrap + CI | Remove 13 PAT requirements and harness PAT from Qwen E2E; generate 14 internal role keys; inspect resolved Compose for token isolation; independent verifier mints GitHub App tokens | Real credentialed Qwen/GitHub sandbox run with usable App installation and configured secrets; eliminate obsolete legacy `.env` placeholders and required Compose interpolations; execute the authored exact approved orchestrator mutation canary on the live sandbox |

**No production-complete authority claim:** configuration and unit tests alone do not establish that all upstream tools behave correctly. Stage 00 retains `ORCHESTRATOR_ENABLED=false`; the existing provider-state canaries remain Builder-centric. Keep PR Draft until the remaining negative/positive and provider-state gates succeed.

## Architectural decision

Every one of seven AI roles and seven role-local orchestrators must authenticate to HermeTeam, never directly to GitHub with a PAT/installation token. The server-side Capability Gateway alone holds GitHub App credentials, issues repository+permission-scoped installation tokens, executes the permitted GitHub MCP or REST request, and records evidence. A token's expiration is not a substitute for exact-request authority; grants remain independent.

```text
7 AI roles -> per-role HermeTeam identity -> Role-Aware MCP Gateway
7 orchestrators -> per-role HermeTeam identity -> Orchestrator REST facade
                       |
             authenticated role + intent
                       |
      deterministic tool/permission/resource policy
                       |
    AUTO / HUMAN once / DENY + emergency stop
                       |
          GitHub App installation broker
                       |
           GitHub MCP / REST on sandbox
                       |
              provider-state evidence
```

## Verified baseline (2026-10)

- `capability_gateway/github_app.py` already mints and caches scoped GitHub App installation tokens.
- `capability_gateway/mcp_proxy.py` supports **Builder only**, authenticated with `BUILDER_CAPABILITY_GATEWAY_KEY`.
- `capability_gateway/authority.py` has only `BUILDER_ACTIONS`.
- `orchestrator/sdlc_orchestrator/provider_github.py` directly uses `ORCHESTRATOR_GITHUB_TOKEN`.
- `compose.yaml` injects per-role provider MCP and orchestrator tokens.
- `scripts/e2e/bootstrap-from-scratch.sh` and `verification/check_prerequisites.py` in the Qwen base still require 13 static GitHub tokens. This must be removed before full-E2E can be declared complete.

## Implementation order

### P0 — Role policy and trust boundary

1. Introduce explicit default-deny, role-scoped, tool-to-capability maps deriving **no implied write access** from an LLM role or discovery.
2. Authenticate with distinct *internal HermeTeam role keys* or workload identity. Verify key-to-role binding server-side with constant-time comparison; an `X-Hermes-Role` header alone proves nothing.
3. Carry authenticated role, repository, run ID, normalized arguments hash and risk into approval/evidence records. Preserve Builder policy, protected paths, agent/* branch restrictions, exact-request approvals, one-shot consumption, emergency stop and no silent fallback.
4. Split MCP discovery from execution. Do not mint a generic write token merely for `initialize` / `tools/list`; use a narrowly permissioned discovery path (and strict server-side filtered tool visibility).

### P1 — All seven AI roles

5. Route all role containers through the Gateway with per-role *internal* gateway credentials; no per-role `*_GITHUB_MCP_TOKEN` provider credentials in role containers.
6. Apply explicit per-role matrix, review actual MCP tool names and provider permission mapping (issues/comments/PRs/actions/contents); deny tools with unknown or ambiguous semantics.
7. Ensure GitHub App key and installation tokens are unavailable in model prompts, MCP tool outputs, role volumes and container environment.

### P2 — Orchestrator REST authority

8. Build an authenticated, narrowly typed internal REST facade for GitHub Issue discovery and transitions; do not return provider tokens to clients. Validate path, target repo/issue, operation, labels and comments; preserve idempotency and require higher approval for state-changing operations.
9. Migrate `orchestrator/sdlc_orchestrator/provider_github.py` onto the facade and remove `ORCHESTRATOR_GITHUB_TOKEN` from container config, cron env snapshots and role-local settings.
10. Do not leak a shared all-powerful internal key; preserve role identity and separate permissions for agents vs orchestrator service identities.

### P3 — Bootstrap, E2E and CI

11. Remove the 6 direct-role MCP token secrets and 7 orchestrator token secrets from the **Qwen E2E** workflow, bootstrap and preflight. Bootstrap must generate local internal gateway role credentials (not GitHub PATs).
12. Keep mandatory GitHub App ID, private key, repository/sandbox scope; allow lookup of installation ID from the target repository, but ensure installation identity and granted permissions match.
13. Replace any static E2E verifier PAT with an independently scoped short-lived GitHub App credential or a separately trusted verifier app. The harness must never inject verifier authority into HermeTeam agents.
14. E2E checks: seven roles without provider credentials, seven orchestrators without GitHub tokens, least-privilege grants, cross-role impersonation, cross-repo deny, protected path deny, one-shot replay deny, emergency stop, token expiry/renewal, fail-closed broker outage, Qwen workflow from scratch, provider state before/after, sanitized audit receipts.

## Minimal permission intent (validate against actual GitHub API/MCP operation)

| Role | Tool intent | GitHub App scope |
|---|---|---|
| Planner | file / issue reads | contents:read; issues:read |
| Project Manager | issue reads and specific issue updates | issues:read/write, per-action |
| Builder | protected branch controls, code edits, PR creation, CI observation | contents:read/write; pull_requests:write; actions:read; actions:write only after exact approval |
| Reviewer | PR/code/CI reads, separately approved commentary | pull_requests:read; contents:read; actions:read; issue comment permissions as needed |
| Release | CI status only | actions:read |
| Incident | read issues, bounded comments | issues:read/write per-action |
| Learning | read issues, restricted comments and edits | issues:read/write per-action |

## Delivery gates

- No legacy provider token can be required or accepted in secure default mode; compatibility fallback must be opt-in, clearly marked and never silently activated.
- GitHub App token creation follows server-side authorization and scopes each request to repository + minimum permissions.
- `tools/list` visibility cannot grant execution authority.
- Approval receipts and independent provider-state verification demonstrate that DENY truly prevented mutation.
- Static tests + authority canaries + full credentialed Qwen sandbox E2E pass.
- Update `.env.example`, Compose overlays, EN/RU docs, `scripts/validate.sh`, `AGENTS.md` impact notes and `skills/hermeteam-deploy-evolve/SKILL.md` as behavior changes.

## Rollback / rollout

Implement as a **stacked PR** against the Qwen E2E feature branch. Keep the feature branch unmerged while changes are partial. Rollback consists of not selecting the new secure overlay in a disposable environment; do not silently switch production or reuse standing PATs. Promote the Qwen E2E branch to `master` only after an audited sandbox rollout, security regression tests and explicit review.
