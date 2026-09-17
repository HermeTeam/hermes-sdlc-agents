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
  |       under /opt/data/workspace/<work-item>
  |              |
  |              +--> local Git metadata (no remote)
  |              +--> Pyright / TypeScript Language Server
  |              +--> hermeteam-openhands bridge
  |                        |
  |                        +--> OpenHands CLI
  |                             sanitized env only
  |                             BUILDER_OPENHANDS_LLM_*
  |
  +--> review local changes and diagnostics
  |
  +--> push_files/create_pull_request via repository MCP/API
  |
  +--> GitHub Actions evidence
```

OpenHands does not receive `GIT_PROVIDER_MCP_TOKEN`, orchestrator GitHub/GitLab tokens, the builder's normal model key, or other inherited container secrets. The bridge creates a fresh subprocess environment containing only basic process variables plus the dedicated OpenHands model settings.

## Image dependencies

`Dockerfile.orchestrator` pins and installs:

- OpenHands CLI `1.16.0` using `uv tool install ... --python 3.12`;
- Pyright `1.1.414`;
- TypeScript `7.0.2`;
- TypeScript Language Server `6.0.0`.

They are installed at image build time because HermeTeam disables lazy runtime installs. The shared image contains these binaries, but only the builder profile enables `hermeteam-openhands-bridge` and exposes the `hermeteam-openhands` toolset.

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

## Dedicated OpenHands model credentials

Configure the builder-specific environment file from `secrets/hermes-builder.env.example`:

```dotenv
BUILDER_OPENHANDS_ENABLED=true
BUILDER_OPENHANDS_LLM_MODEL=openrouter/deepseek/deepseek-chat
BUILDER_OPENHANDS_LLM_API_KEY=CHANGE_ME_DEDICATED_OPENHANDS_KEY
BUILDER_OPENHANDS_LLM_BASE_URL=https://openrouter.ai/api/v1
```

Use a dedicated model key. Do not reuse repository/provider credentials. The bridge maps these values to the standard OpenHands/LiteLLM variables `LLM_MODEL`, `LLM_API_KEY`, and `LLM_BASE_URL` inside the child process.

## Delegation workflow

1. Hermes reads the approved work item and task-relevant files from repository MCP/API.
2. Hermes materializes the minimum required source/test files under `/opt/data/workspace/<work-item>`.
3. Hermes invokes `openhands_delegate` with a concrete task and relative workspace.
4. The bridge ensures the path stays under `/opt/data/workspace`, initializes local Git metadata if needed, and rejects an existing Git remote.
5. The bridge starts OpenHands headlessly with a sanitized environment.
6. After OpenHands exits, the bridge checks Git remotes again. Any newly configured remote is removed and the call is reported as a security violation.
7. Hermes rereads every changed file, evaluates LSP diagnostics, protected paths, and requirement mapping.
8. Hermes applies reviewed provider changes only through role-allowed repository MCP/API tools.
9. GitHub Actions remains the authoritative final test evidence.

The local Git repository exists only because OpenHands and Hermes LSP need repository/worktree context. It is not a clone and has no provider remote.

## `openhands_delegate` contract

Parameters:

- `task` — required concrete coding task, maximum 12,000 characters;
- `workspace` — relative path below `/opt/data/workspace`, default `.`;
- `timeout_seconds` — 30-1800 seconds, default 900.

The bridge invokes:

```text
openhands --headless --json --override-with-envs --exit-without-confirmation -t <task>
```

The result includes the exit code, bounded stdout/stderr, and local `git status --porcelain` entries. Treat this as coding evidence only, never as authorization evidence.

## Security boundaries and limitations

- OpenHands runs as a subprocess in the builder container, not as a separate Docker sandbox. The important enforced boundary in this integration is credential/environment isolation plus workspace/root and Git-remote checks. Do not describe it as a full kernel/container sandbox.
- Generic terminal access stays disabled because the builder container itself contains repository/provider secrets needed by Hermes/orchestrator. Enabling terminal would make those credentials reachable to arbitrary shell subprocesses.
- OpenHands may edit only local materialized files. Provider state changes still pass through the existing HermeTeam Intent/Action Gate and repository MCP/API permissions.
- LSP diagnostics improve syntax/type feedback but do not replace unit/integration tests or GitHub Actions.
- `install_strategy: manual` is intentional: missing language-server binaries are a build/configuration failure, not permission to download software during an agent run.
- Upstream OpenHands CLI lifecycle should be reviewed when upgrading the pinned version; upgrades require the same authority/security regression checks.

## Verification

Minimum targeted checks:

```bash
python -m unittest discover -s hermes-plugins/tests -v
docker compose config --quiet
```

After building the agent image:

```bash
docker compose build hermes-builder
docker compose run --rm --entrypoint sh hermes-builder -ec '
  openhands --version &&
  pyright --version &&
  typescript-language-server --version
'
```

For a security canary, run the unit tests that verify:

- non-builder roles cannot use the bridge;
- workspace path traversal is rejected;
- dedicated LLM credentials are required;
- provider/MCP tokens are absent from the OpenHands subprocess environment.

A production-ready change must still pass repository-wide validation and the PR CI jobs required by `AGENTS.md`.
