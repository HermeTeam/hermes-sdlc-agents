# HermeTeam SMB — subscribed Safe Builder runtime (Phase 1)

For AI-forward teams with 3–30 developers, this is an independent, small runtime rather than a seven-role SDLC deployment. Use **only** `compose.smb.yaml`; never merge it with the full `compose.yaml`.

The stack contains a single `hermes-builder` using a slim dedicated image/profile (no OpenHands, Langfuse SDK, LSP toolchain or third-party MCP servers), mandatory Dynamic Authority `capability-gateway`, `subscription-relay`, local Dashboard, restricted Docker socket proxy and pinned read-only skills sync. Planner, PM, Reviewer, Release, Incident, Learning, OpenHands, Langfuse and unattended orchestration are not required.

## Subscription-owned model (not user-configurable)

The HermeTeam subscription provisioner, **not the customer**, supplies `secrets/smb-subscription.env` with `SMB_SUBSCRIPTION_BASE_URL` and `SMB_SUBSCRIPTION_MODEL`, plus `secrets/smb-subscription.token`. Those files are owner-only (mode `0600`) and accessible only to the relay. The actual upstream token is a Docker secret, never an agent environment variable. The builder and judge use only the fixed `hermeteam-subscribed` model alias at a local relay and a separate internal key.

The subscription entitlement and out-of-band bundle issuer are **not implemented in this repository**. Phase 1 requires operator-provisioned subscription files; it must fail closed without them and never prompt the customer for a personal Qwen/OpenAI/provider key. A complete automated subscription onboarding flow belongs to Phase 2.

The GitHub App private key goes in `secrets/smb-github-app.pem` (mode `0600`), mounted only into the capability gateway. No role-scoped GitHub PAT or standing Builder provider token is required. GitHub App installation and its least-privilege permissions must be configured separately during Phase 1.

## Start

Requirements: Linux/Docker Engine and Compose v2, Python 3.12+, three pre-provisioned secret files above, a GitHub App bound to a dedicated sandbox repository, and an immutable digest-pinned Hermes image.

```bash
export SMB_GITHUB_REPOSITORY_FULL_NAME="my-org/my-sandbox-repo"
export SMB_GITHUB_APP_ID="123456"
export SMB_GITHUB_APP_INSTALLATION_ID="987654"
export SMB_HERMES_BASE_IMAGE="registry.example/hermes@sha256:<64-hex-digest>"
python3 scripts/smb/bootstrap.py
python3 scripts/smb/doctor.py
bash scripts/smb/up.sh
```

`.env.smb` is generated idempotently with independent internal credentials and is ignored by Git. The full SDLC `.env` is untouched. Dashboard: `http://127.0.0.1:9130` only. `bash scripts/smb/down.sh` stops services and preserves persistent state.

The smoke script probes subscription-backed model inference, dynamic gateway readiness and Builder/Dashboard health. A successful smoke is **not** proof of protected-path or grant enforcement: validate real GitHub sandbox provider-state negative and positive canaries before production usage. Unattended orchestration remains off and the gateway's current dynamic execution path covers Builder only.

Phase 2 will add the subscription provisioning UX, one-click GitHub App installation, prebuilt signed image releases, onboarding wizard and measured 30-minute first verified PR. Those are not claimed as complete here.
