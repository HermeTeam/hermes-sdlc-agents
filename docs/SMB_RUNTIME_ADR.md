# ADR — Separate subscribed Safe Builder runtime for SMB

**Status:** Proposed for `master` in PR #12. Implemented as a pilot runtime; not a production-ready subscription self-service release.

## Context

The seven-role SDLC Compose requires role-specific GitHub MCP and orchestrator credentials and the full suite of role configuration even when the buyer needs one safe coding agent. Small teams (3–30 developers) need one bounded PR workflow with little operational setup. Product subscription already determines model provider and model; requiring users to select Qwen/OpenAI or bring their own provider key is a business-requirement violation.

## Decision

Keep full SDLC Compose intact. Add a separate `compose.smb.yaml` running one Builder, mandatory existing Dynamic Authority Gateway/GitHub App token broker, Dashboard, Docker read-only proxy and a fixed-model subscription relay. Pin only five relevant read-only skills from `skills_superset`. Reserve provider key and upstream model/URL exclusively for HermeTeam operator subscription provisioning; the agent receives a local relay credential and fixed alias. Do not silently replace subscription with a direct credential or broader GitHub PAT.

Keep unattended orchestration and OpenHands off during Phase 1. Require digest-pinned Hermes base image and separate sandbox GitHub App installation. Generate independent internal secrets automatically, protect operator files and preserve state on restart.

## Trade-offs and limitations

- An additional small relay service is necessary to prevent upstream provider credentials reaching an agent; it adds a local hop and an operational dependency.
- Dashboard's canonical seven-role contract remains intact internally. Absent roles are explicitly DISABLED and hidden in SMB UI, rather than marked as outages.
- This runtime depends on **external subscription/account provisioning**. The product-level issuance endpoint, billing/authenticated entitlements and GitHub App installation wizard are later deliverables, not simulated here.
- The existing dynamic gateway is a Builder canary, not general enforcement for arbitrary tools. Do not call the pilot production-ready without external security canaries and a successful live provider-state test.
- The SMB-specific Builder image/profile avoids optional OpenHands/Langfuse/LSP and non-GitHub MCP integrations. Local builds remain until release images are available. Digest-pinned base image avoids silently pulling mutable `latest`.

## Verification

Offline tests assert no provider selection/secret in Builder, only one agent role, sole loopback UI, read-only mounted skills, role isolation and fixed model mapping. CI renders Compose with fake secrets; real subscription and GitHub tests require pre-provisioned separate sandbox and cannot be declared passing by offline CI alone.
