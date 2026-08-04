# Источники конфигурационной схемы

Пакет собран по официальной документации, проверенной 2026-07-31:

- [Hermes Configuration](https://hermes-agent.nousresearch.com/docs/user-guide/configuration/) — `model`, terminal, toolsets, worktree, memory/skills approvals, security, command deny rules, checkpoints и loop guardrails.
- [Hermes Toolsets Reference](https://hermes-agent.nousresearch.com/docs/reference/toolsets-reference) — имена built-in/dynamic toolsets и `mcp-<server>`.
- [Hermes MCP Config Reference](https://hermes-agent.nousresearch.com/docs/reference/mcp-config-reference/) — HTTP server, env substitution, exact include/exclude, resources/prompts и TLS.
- [Hermes MCP Guide](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp) — sampling, elicitation, parallel calls и security behavior.
- [Hermes Profiles](https://hermes-agent.nousresearch.com/docs/user-guide/profiles/) — profile/state semantics и предупреждение, что profile не является sandbox.
- [Hermes Profile Distributions](https://hermes-agent.nousresearch.com/docs/user-guide/profile-distributions) — `distribution.yaml`, `env_requires`, install/update и hard-excluded runtime data.
- [Hermes Docker](https://hermes-agent.nousresearch.com/docs/user-guide/docker/) — official image, `/opt/data`, `gateway run`, one-container-per-role cases, ports и liveness.
- [Hermes API Server](https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server/) — bearer auth, `/v1/responses`, `/v1/runs`, `/health` и configuration variables.
- [Hermes Managed Scope](https://hermes-agent.nousresearch.com/docs/user-guide/managed-scope) — `/etc/hermes`, precedence и ограничения enforcement model.
- [Hermes Security](https://hermes-agent.nousresearch.com/docs/user-guide/security/) — write-safe root, secret filtering, approvals, container and gateway security.
- [OPA Policy Language](https://www.openpolicyagent.org/docs/policy-language) и [Policy Testing](https://www.openpolicyagent.org/docs/policy-testing) — Rego v1 policy/test syntax.

Перед обновлением Hermes image запустите validation на новой версии и просмотрите upstream schema/release notes: этот bundle намеренно pin-ит ожидаемые имена config keys и MCP tools.
