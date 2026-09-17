---
name: openhands
description: Delegate bounded coding tasks to an isolated OpenHands runner through the HermeTeam builder bridge.
version: 0.2.0
platforms: [linux]
metadata:
  hermes:
    tags: [coding-agent, openhands, builder]
    requires_toolsets: [hermeteam-openhands]
---

# OpenHands delegation for HermeTeam Builder

Use this skill only for implementation/refactoring work that benefits from an autonomous coding loop inside the builder scratch workspace.

## Security contract

- Never enable or call the generic `terminal` tool for OpenHands.
- Call only `openhands_delegate`.
- The local workspace is scratch state, not repository authority.
- Materialize only task-relevant files from repository MCP into `/opt/data/workspace/<work-item>`.
- The builder plugin does not launch OpenHands inside the builder container. It sends a bounded JSON request over a Unix socket to `hermes-builder-openhands`.
- The isolated runner has a dedicated secret file `secrets/hermes-builder-openhands.env` and must not receive GitHub/GitLab/MCP/provider credentials.
- The runner is not attached to `hermes-control`; it uses its own egress-only bridge network for model API access.
- The runner refuses a workspace with a Git remote and removes any remote OpenHands tries to add.
- Repository writes remain exclusively through role-allowed repository MCP/API tools (`push_files`, create PR, Actions reads/runs). Never push from the local Git repository.

## Workflow

1. Read the approved work item/spec and relevant repository files through repository MCP.
2. Materialize the minimal files needed for the task under `/opt/data/workspace/<work-item>` using the allowed filesystem tool.
3. Call `openhands_delegate` with a concrete task and that relative workspace.
4. Review `changed`, `stdout`, and `stderr` from the tool. Do not trust success text alone.
5. Read every changed file locally and reconcile it against requirements and protected-path policy.
6. Use Hermes file writes/patches when additional corrections are needed. Hermes LSP post-edit diagnostics use the local Git worktree maintained in the scratch workspace.
7. Push the reviewed file contents to the task branch only through repository MCP/API.
8. Run repository CI through GitHub Actions MCP and attach the resulting evidence to the PR.

## LSP

The builder image preinstalls:

- `pyright` / `pyright-langserver` for Python;
- `typescript-language-server` plus `typescript` for TypeScript/JavaScript.

Hermes LSP is configured with `install_strategy: manual`, so no language-server package is downloaded at runtime. Diagnostics require the edited file to be under a Git worktree; the OpenHands runner initializes local Git metadata when needed.

## OpenHands invocation

The runner image installs OpenHands CLI with `uv` and Python 3.12. The runner invokes upstream headless automation flags:

`openhands --headless --json --override-with-envs --exit-without-confirmation -t <task>`

OpenHands is an executor, not an authority boundary. A successful OpenHands run does not authorize provider mutation, merging, deployment, or access expansion.

## Failure handling

- Missing runner socket: stop and report that `compose.openhands.yaml` is not active or the runner is unhealthy.
- Missing dedicated LLM credentials: stop and fix `secrets/hermes-builder-openhands.env`.
- Missing OpenHands/LSP binary: treat as an image build/configuration failure; do not lazy-install packages during the agent run.
- Timeout/non-zero exit: inspect bounded output, correct with Hermes or retry only with a narrower task.
- Git remote detected: treat as a security failure and do not publish local changes until reviewed.
