# Builder OpenHands + LSP integration

HermeTeam builder can use OpenHands as a bounded coding executor and Hermes LSP post-edit diagnostics for Python and TypeScript without enabling the generic terminal tool or giving OpenHands repository/provider credentials.

## Architecture

```text
approved work item
      |
      v
Hermes Builder
  |   repository MCP/API (authoritative reads/writes)
  |
  +--> materialize task-relevant files
  |       under ./workspace/builder/<work-item>
  |              |
  |              +--> Pyright / TypeScript Language Server in builder
  |              +--> hermeteam-openhands bridge
  |                         |
  |                    Unix socket
  |                         |
  |                         v
  |              hermes-builder-openhands sidecar
  |              - separate container
  |              - separate secret file
  |              - no hermes-control network
  |              - no Git/provider/MCP credentials
  |              - OpenHands CLI + local Git metadata
  |
  +--> review local changes and diagnostics
  |
  +--> push_files/create_pull_request via repository MCP/API
  |
  +--> GitHub Actions evidence
```

The builder and runner share only the builder scratch workspace. The bridge communicates through `/opt/data/workspace/.hermeteam-openhands/runner.sock`; no TCP service is exposed.

## Images and dependencies

`Dockerfile.orchestrator` pins and installs the builder LSP dependencies:

- Pyright `1.1.414`;
- TypeScript `7.0.2`;
- TypeScript Language Server `6.0.0`.

`Dockerfile.openhands-runner` installs OpenHands CLI `1.16.0` with `uv` and Python 3.12. OpenHands is deliberately absent from the builder process namespace: this prevents a coding subprocess from inheriting or probing the builder's provider credentials.

All packages are installed at image build time because HermeTeam disables lazy runtime installs.

## Builder configuration

`profiles/hermes-builder/config.yaml` enables:

```yaml
plugins:
  enabled:
    - hermeteam-intent-action-gate
    - hermeteam-openhands-bridge
    - observability/langfuse

toolsets:
  - hermeteam-openhands

lsp:
  enabled: true
  install_strategy: manual
  wait_mode: document
  wait_timeout: 5
  servers:
    pyright:
      command: ["pyright-langserver", "--stdio"]
    typescript:
      command: ["typescript-language-server", "--stdio"]
```

`terminal` and Hermes' generic `delegation` toolsets remain disabled.

## Dedicated OpenHands credentials

Copy only the runner-specific example:

```bash
cp secrets/hermes-builder-openhands.env.example secrets/hermes-builder-openhands.env
```

Configure:

```dotenv
BUILDER_OPENHANDS_LLM_MODEL=openrouter/deepseek/deepseek-chat
BUILDER_OPENHANDS_LLM_API_KEY=CHANGE_ME_DEDICATED_OPENHANDS_KEY
BUILDER_OPENHANDS_LLM_BASE_URL=https://openrouter.ai/api/v1
```

Do not put GitHub/GitLab/MCP tokens, GitHub App private keys, or the builder's normal model credential in this file. `compose.openhands.yaml` attaches only this file to `hermes-builder-openhands`.

The runner maps these values to the OpenHands/LiteLLM variables `LLM_MODEL`, `LLM_API_KEY`, and `LLM_BASE_URL` only for the OpenHands child process.

## Start the integration

OpenHands is an opt-in deployment overlay so the base seven-role topology remains unchanged for installations that do not need an additional coding executor:

```bash
docker compose \
  -f compose.yaml \
  -f compose.openhands.yaml \
  up -d --build hermes-builder-openhands hermes-builder
```

The sidecar uses a dedicated `openhands-egress` bridge network for model API access and is not connected to `hermes-control`. Builder/runner communication uses the shared Unix socket, not the Docker network.

## Delegation workflow

1. Hermes reads the approved work item and task-relevant files from repository MCP/API.
2. Hermes materializes the minimum source/test files under `/opt/data/workspace/<work-item>`.
3. Hermes invokes `openhands_delegate` with a concrete task and relative workspace.
4. The builder plugin validates that the requested workspace stays under `/opt/data/workspace`, then sends bounded JSON over the Unix socket.
5. The runner validates the workspace again, initializes local Git metadata if needed, and rejects any existing Git remote.
6. The runner starts OpenHands headlessly with a minimal child environment derived only from its dedicated model credentials.
7. After OpenHands exits, the runner checks Git remotes again. Any remote added during the run is removed and reported as a security violation.
8. Hermes rereads every changed file, evaluates LSP diagnostics, protected paths, and requirement mapping.
9. Hermes applies reviewed provider changes only through role-allowed repository MCP/API tools.
10. GitHub Actions remains the authoritative final test evidence.

The local Git repository exists only because OpenHands and Hermes LSP need repository/worktree context. It is not a clone and has no provider remote.

## `openhands_delegate` contract

Parameters:

- `task` — required concrete coding task, maximum 12,000 characters;
- `workspace` — relative path below `/opt/data/workspace`, default `.`;
- `timeout_seconds` — 30-1800 seconds, default 900.

The runner invokes:

```text
openhands --headless --json --override-with-envs --exit-without-confirmation -t <task>
```

The result includes exit code, bounded stdout/stderr, and local `git status --porcelain` entries. Treat this as coding evidence only, never as authorization evidence.

## Security boundaries and limitations

- OpenHands is isolated from the builder's process environment and control-plane network in a separate container. The shared writable surface is the builder scratch workspace.
- The runner intentionally has outbound network access for its configured model endpoint. It must not receive general provider credentials or be attached to `hermes-control`.
- Generic terminal access stays disabled in the builder because the builder container contains repository/provider secrets needed by Hermes/orchestrator.
- OpenHands can edit only local materialized files. Provider state changes still pass through the existing HermeTeam Intent/Action Gate and repository MCP/API permissions.
- The runner's local Git remote checks are defense in depth; the principal provider-write boundary is absence of provider credentials in the runner.
- LSP diagnostics improve syntax/type feedback but do not replace unit/integration tests or GitHub Actions.
- `install_strategy: manual` is intentional: missing language-server binaries are an image/configuration failure, not permission to download software during an agent run.
- OpenHands CLI is pinned. Review upstream lifecycle/security before changing the pinned version.

## Verification

Minimum targeted checks:

```bash
python -m unittest discover -s hermes-plugins/tests -v
docker compose config --quiet
docker compose -f compose.yaml -f compose.openhands.yaml config --quiet
```

Build-time/runtime checks:

```bash
docker compose -f compose.yaml -f compose.openhands.yaml build hermes-builder hermes-builder-openhands

docker compose run --rm --entrypoint sh hermes-builder -ec '
  pyright --version &&
  typescript-language-server --version
'

docker compose -f compose.yaml -f compose.openhands.yaml run --rm --entrypoint sh hermes-builder-openhands -ec '
  openhands --version
'
```

Security canaries in `hermes-plugins/tests` verify:

- non-builder roles cannot call the bridge;
- workspace path traversal is rejected on both sides;
- missing runner socket fails closed;
- the OpenHands child environment excludes provider/MCP tokens;
- the OpenHands Compose overlay references only the dedicated runner secret file and contains no provider credential names.

A production-ready change must still pass repository-wide validation and the PR CI jobs required by `AGENTS.md`.
