# Описание конфигураций

## Общая база

Все шесть `config.yaml` используют OpenAI-совместимый internal model endpoint:

```yaml
model:
  provider: custom
  default: "${HERMES_MODEL_ID}"
  base_url: "${HERMES_MODEL_BASE_URL}"
```

Credential берётся из `OPENAI_API_KEY`. Рекомендуется LLM proxy token с model allowlist, quota и отдельным subject для каждой роли.

Общие safety settings:

| Настройка | Значение | Зачем |
|---|---|---|
| `HERMES_MANAGED_DIR` | `/etc/hermes` | role config read-only и выше profile overrides |
| `security.redact_secrets` | `true` | redaction известных key/token patterns в output/logs |
| `security.allow_lazy_installs` | `false` | никаких runtime dependency installs |
| `memory.memory_enabled` | `false` | нет неконтролируемого cross-session drift |
| `skills.write_approval` | `true` | skill mutations staged до human approval |
| `skills.external_dirs` | `/etc/hermes/skills`, `/opt/hermes-shared-skills/current` | role-local и общий read-only каталог skills |
| `mcp_servers.sdlc.tools.include` | exact list | MCP surface без wildcard |
| MCP resources/prompts | `false` | исключена дополнительная server-controlled context surface |
| MCP sampling/elicitation | `false` | MCP server не инициирует LLM spend или user prompts |
| `direct_model_requests` | `false` | внешний API caller не меняет provider/model routing |
| `tool_loop_guardrails.hard_stop_enabled` | `true` | unattended loop прекращается, а не только предупреждается |
| `terminal.home_mode` | `profile` там, где terminal включён | внешние CLI credentials не наследуются из общего HOME |
| `API_SERVER_KEY` | отдельный per role | независимая inbound authentication и revoke |

## hermes-planner

Назначение: превратить требования и фактическую структуру системы в traceable `spec` и `plan`.

- Built-ins: `skills`, `todo`, `clarify`; `file` и `terminal` отключены.
- Read tools: requirements, repository read/search/tree, service catalog/dependencies, existing specs/plans.
- Write tools: только `spec_create/update`, `plan_create/update`.
- Runtime: repository вообще не mounted; production credentials отсутствуют.
- Exit states: `READY_FOR_BUILD` или `BLOCKED`.

Server-side обязательства: artifact type allowlist, repository/ref/work-item scope, idempotency и audit. Даже с украденным token нельзя вызвать repository write или deployment tool.

## hermes-builder

Назначение: реализовать одну утверждённую задачу как SDLC MCP patch/change-set и передать change request на независимое review.

Подробный workflow описан в двух отдельных документах: [Repository API/MCP Flow — English](REPOSITORY_API_MCP_FLOW_EN.md) и [Флоу доступа к репозиториям через API/MCP — Русский](REPOSITORY_API_MCP_FLOW_RU.md).

- Built-ins: `file`, `skills`, `todo`, `clarify`; `terminal` отключён.
- Репозиторий не mounted; GitHub/GitLab/Forgejo credentials отсутствуют в agent container.
- File safe roots: `/opt/data`.
- Checkpoints: включены, до 20 snapshots.
- MCP writes: create task branch, apply patch, commit changes, create/update change request, trigger CI.
- Нет MCP merge, deployment, flag, runbook или gate mutation tools.
- Exit states: `PR_READY_FOR_REVIEW` или `BLOCKED`.

Hard controls: task-branch prefix, expected revisions, protected branches, provider token без merge/admin, protected-path check до commit и в trusted CI за пределами ветки автора. `approvals.deny` не заменяет эти controls.

## hermes-reviewer

Назначение: независимая оценка fixed change request revision и evidence.

- Built-ins: `skills`, `todo`, `clarify`; нет filesystem/terminal mount.
- Read tools: change request, diff, file at revision, tests, coverage delta, mutation score, findings/gates.
- Write tools: только comments и review decision.
- Нет branch-content write и merge tools.
- Exit decision: `APPROVE` или `REQUEST_CHANGES`.

Gateway проверяет `independence_verified` по provenance: reviewer subject не должен совпадать с author/implementation subject.

## hermes-release

Назначение: принять fail-closed решение на следующем этапе progressive delivery.

- Built-ins: `skills`, `todo`; `terminal`, `file`, `clarify` и delegation отключены.
- Read tools: immutable candidate/policy, CI/tests/gates, bounded metrics/SLO, rollout analysis/status/audit.
- Единственные mutations: `deployment_promote`, `deployment_abort`.
- Нет Kubernetes service-account token, kubeconfig или исходного кода.
- Exit states: `PROMOTED`, `ABORTED`, `BLOCKED_NO_ACTION`.

Каждый action требует candidate ID, expected revision, policy evaluation ID и idempotency key. MCP adapter владеет узким Argo Rollouts credential и не публикует arbitrary traffic weight/manifests.

## hermes-incident

Назначение: диагностировать incident и применить только заранее утверждённую, обратимую mitigation.

- Built-ins: `skills`, `todo`; нет shell/filesystem/delegation.
- Read tools: incident, catalog/dependencies, bounded logs/traces/metrics/alerts/SLO, flags и approved runbooks.
- Mutations: incident timeline, `flags_disable`, `runbooks_execute_approved`.
- `flags_disable` поддерживает только `enabled -> disabled` с expected version.
- Runbook immutable, approved, versioned и schema-constrained.
- Exit states: `MITIGATED`, `MONITORING`, `ESCALATED`, `NO_ACTION`.

Никакой generic infrastructure operation не публикуется. Если mitigation отсутствует в allowlist, правильный результат — human escalation.

## hermes-learning

Назначение: превратить повторяемые outcomes/feedback в proposal с измеримым evaluation plan.

- Built-ins: `skills`, `todo`, `clarify`; file/terminal/delegation отключены.
- Native `skill_manage` остаётся gated: `guard_agent_created: true`, `write_approval: true`.
- Read tools: aggregated/redacted outcomes, docs и skills catalog.
- Write tools: proposal queue и attached diff.
- Нет `skills_activate/install/publish` и прямого docs write.
- Exit state: `PROPOSED_FOR_HUMAN_REVIEW`.

Human approver и activation pipeline являются отдельными identities. Learning agent не может одобрить собственный pending change.

## Shared skills superset

Все роли подключают общий каталог `/opt/hermes-shared-skills/current` через `skills.external_dirs`. Источник по умолчанию: `https://github.com/stanta/skills_superset.git`, ветка/refs `main`, подкаталог `skills/`.

Docker Compose обновляет каталог сервисом `skills-superset-sync` до запуска агентов. Kubernetes обновляет каталог initContainer-ом `sync-shared-skills` в каждом Pod. Основные agent containers монтируют результат read-only; изменения skills не должны писаться в общий каталог.

## Environment files

Каждый `secrets/hermes-<role>.env` содержит:

| Variable | Назначение |
|---|---|
| `HERMES_MODEL_ID` | model ID в разрешённом gateway catalog |
| `HERMES_MODEL_BASE_URL` | internal OpenAI-compatible endpoint |
| `OPENAI_API_KEY` | role-scoped LLM token |
| `SDLC_MCP_URL` | Streamable HTTP MCP endpoint |
| `SDLC_MCP_TOKEN` | short-lived role identity |
| `API_SERVER_KEY` | inbound Hermes API bearer key, минимум 8 символов |
| `API_SERVER_MODEL_NAME` | стабильное имя роли в `/v1/models` |

Не добавляйте `GATEWAY_ALLOW_ALL_USERS`, kubeconfig/cloud tokens или admin PAT. Для chat platforms задайте явные user allowlists отдельно; bundle рассчитан прежде всего на internal API orchestrator.
