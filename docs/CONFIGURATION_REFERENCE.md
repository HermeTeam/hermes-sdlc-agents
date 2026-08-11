# Описание конфигураций

## Общая база

Все семь `config.yaml` используют OpenAI-совместимый internal model endpoint:

```yaml
model:
  provider: custom
  default: "${HERMES_MODEL_ID}"
  base_url: "${HERMES_MODEL_BASE_URL}"
```

Credential берётся из общего `OPENAI_API_KEY` в `.env` и прокидывается в контейнеры через `compose.yaml`. Рекомендуется LLM proxy/OpenRouter token с model allowlist и quota. Если нужны отдельные ключи per role, это должно быть сделано отдельным orchestration profile, а не дублированием в `secrets/hermes-*.env`.

Общие safety settings:

| Настройка                                | Значение                                                  | Зачем                                                      |
| ---------------------------------------- | --------------------------------------------------------- | ---------------------------------------------------------- |
| `HERMES_MANAGED_DIR`                     | `/etc/hermes`                                             | role config read-only и выше profile overrides             |
| `security.redact_secrets`                | `true`                                                    | redaction известных key/token patterns в output/logs       |
| `security.allow_lazy_installs`           | `false`                                                   | никаких runtime dependency installs                        |
| `memory.memory_enabled`                  | `false`                                                   | нет неконтролируемого cross-session drift                  |
| `skills.write_approval`                  | `true`                                                    | skill mutations staged до human approval                   |
| `skills.external_dirs`                   | `/etc/hermes/skills`, `/opt/hermes-shared-skills/current` | role-local и общий read-only каталог skills                |
| `mcp_servers.repository.tools.include`   | exact list                                                | provider API/MCP surface без wildcard                      |
| MCP resources/prompts                    | `false`                                                   | исключена дополнительная server-controlled context surface |
| MCP sampling/elicitation                 | `false`                                                   | MCP server не инициирует LLM spend или user prompts        |
| `direct_model_requests`                  | `false`                                                   | внешний API caller не меняет provider/model routing        |
| `tool_loop_guardrails.hard_stop_enabled` | `true`                                                    | unattended loop прекращается, а не только предупреждается  |
| `terminal.home_mode`                     | `profile` там, где terminal включён                       | внешние CLI credentials не наследуются из общего HOME      |
| `API_SERVER_KEY`                         | отдельный per role                                        | независимая inbound authentication и revoke                |

## GitHub MCP MVP Scope

`GIT_PROVIDER_MCP_URL` is the official GitHub MCP endpoint for the MVP:

```env
GIT_PROVIDER_MCP_URL=https://api.githubcopilot.com/mcp/
```

The active `mcp_servers.repository.tools.include` lists contain native GitHub MCP tools. They must be confirmed against runtime `tools/list`; GitLab requires a separate future mapping. The old abstract `repo_*`, `ci_*`, `quality_*`, `work_item_*`, `spec_*`, and `plan_*` facade tools are not active runtime tools.

Every active role profile sets this repository MCP header:

```yaml
X-MCP-Toolsets: "repos,issues,pull_requests,actions,git,code_security,dependabot"
```

The header only enables official GitHub MCP server-side tool discovery. Effective exposure remains the role-specific `mcp_servers.repository.tools.include` allowlist.

## Container cron orchestrator

Каждый role container содержит один локальный cron-compatible orchestrator, который по умолчанию отключён:

```env
ORCHESTRATOR_ENABLED=false
ORCHESTRATOR_PROVIDER=github
ORCHESTRATOR_CRON_SCHEDULE=*/5 * * * *
ORCHESTRATOR_MAX_STARTS_PER_TICK=1
ORCHESTRATOR_RUN_TIMEOUT_SECONDS=5400
```

Wrapper `/opt/hermes-sdlc-orchestrator/bin/hermes-with-orchestrator.sh` запускает cron runner и затем `hermes gateway run`. Cron вызывает `/opt/hermes-sdlc-orchestrator/bin/orchestrator-run-once.sh`, который пишет JSON summaries в `/opt/data/sdlc-orchestrator/orchestrator.log` и хранит SQLite dedupe state в `/opt/data/sdlc-orchestrator/orchestrator.sqlite`.

Оркестратор передаёт задания только в локальный API конкретной роли:

```env
ORCHESTRATOR_HERMES_URL=http://127.0.0.1:8642
ORCHESTRATOR_DB_PATH=/opt/data/sdlc-orchestrator/orchestrator.sqlite
ORCHESTRATOR_LOCK_PATH=/opt/data/sdlc-orchestrator/run_once.lock
```

`ORCHESTRATOR_HERMES_URL` намеренно валидируется как localhost-only. Issue title/body считаются untrusted input и попадают только в фиксированный role prompt template; они не могут менять role, endpoint, token или command.

## hermes-planner

Назначение: превратить требования и фактическую структуру системы в traceable `spec` и `plan`.

- Built-ins: `skills`, `todo`, `clarify`; `file` и `terminal` отключены.
- Read tools: GitHub file contents, repository tree, code search, issues.
- Write tools: none through the repository MCP in the GitHub MVP.
- Runtime: repository вообще не mounted; production credentials отсутствуют.
- Exit states: `READY_FOR_BUILD` или `BLOCKED`.
- Orchestrator final response: strict JSON object with `assignment_key`, `role`, `final_status`, `summary`, `evidence`, `next_handoff`, and `block_reason`; free-text status extraction is rejected.

Server-side обязательства: repository/ref scope, GitHub token scopes, deny repository write/deployment tools, and audit.

## hermes-project-manager

Назначение: управлять IT-проектом через BRD/PRD governance, измеримые цели, Funnel/Discovery separation, roadmap/backlog, WIP, риски, weekly decision reporting, flow/health metrics, статусы, решения и evidence gates.

- Built-ins: `skills`, `todo`, `clarify`; `file` и `terminal` отключены.
- Read tools: GitHub file contents, repository tree, code search, issues.
- Write tools: GitHub issue comments and issue creation for PM artifacts only.
- Runtime: repository не mounted; code/branch/deployment/production credentials отсутствуют.
- Exit states: `CHARTER_READY`, `ROADMAP_READY`, `READY_FOR_ITERATION`, `IN_PROGRESS`, `REVIEW`, `DONE`, `BLOCKED`, `REPLAN_REQUIRED`, `PAUSED`, or `KILLED` depending on project state and evidence.
- Orchestrator labels may use `ORCHESTRATOR_PROJECT_MANAGER_LABELS` and `ORCHESTRATOR_PROJECT_MANAGER_ASSIGNEES` because role names are normalized from `project-manager` to `PROJECT_MANAGER` for env vars.
- Governance: every material charter/roadmap/status/decision references BRD/PRD when available; changes to vision, scope, constraints, requirements, success metrics, budget, deadlines, guardrails, or authority boundaries become `CHANGE_REQUEST` decision packets.
- Workflow: `FUNNEL -> DISCOVERY -> READY -> IN_PROGRESS -> REVIEW/VALIDATION -> DONE`, with `PARKING_LOT / NOT_NOW` for off-goal ideas.
- Reporting: `/weekly-report` follows the PM decision report format and includes outcome status, completed evidence, WIP/throughput/aging/cycle-time trend, quality/incidents, blockers, forecast changes, risks, and next coherent result.
- Metrics: tracks outcome, flow, quality/reliability, and team/system health metrics including SLE, blocked time, queue time, decision waiting time, unplanned work, and bus factor where data exists.
- Execution boundary: PM owns route integrity, dependencies, risk, flow, forecast, and governance; Sponsor/PO/Tech Lead/Delivery Team keep their decision rights and implementation ownership.

Server-side обязательства: repository scope, issue mutation audit, deny code/branch/deployment tools, human approval for material commitment changes, and prompt-injection treatment of ticket/document content as data.

## hermes-builder

Назначение: реализовать одну утверждённую задачу через native GitHub MCP branch/file/PR tools и передать Pull Request на независимое review.

Подробный workflow описан в двух отдельных документах: [Repository API/MCP Flow — English](REPOSITORY_API_MCP_FLOW_EN.md) и [Флоу доступа к репозиториям через API/MCP — Русский](REPOSITORY_API_MCP_FLOW_RU.md).

- Built-ins: `file`, `skills`, `todo`, `clarify`; `terminal` отключён.
- Репозиторий не mounted; broad GitHub credentials отсутствуют в agent container, используется только role-specific GitHub MCP token.
- File safe roots: `/opt/data`.
- Checkpoints: включены, до 20 snapshots.
- MCP writes: `create_branch`, `push_files`, `create_pull_request`, `actions_run_trigger`.
- Нет MCP merge, deployment, flag, runbook или gate mutation tools.
- Exit states: `PR_READY_FOR_REVIEW` или `BLOCKED`.
- `PR_READY_FOR_REVIEW` triggers the canonical transition to reviewer only after strict JSON validation.

Hard controls: `agent/*` branch prefix, protected branches, provider token без merge/admin, protected-path check for `push_files` and in trusted CI outside the author branch. `approvals.deny` не заменяет эти controls.

## hermes-reviewer

Назначение: независимая оценка fixed change request revision и evidence.

- Built-ins: `skills`, `todo`, `clarify`; нет filesystem/terminal mount.
- Read tools: Pull Request metadata, file contents, Actions evidence and job logs.
- Write tools: `add_issue_comment` only in the GitHub MVP.
- Нет branch-content write и merge tools.
- Exit decision: `APPROVE`, `REQUEST_CHANGES`, or `BLOCKED`. Tool/evidence unavailability must be represented as `BLOCKED` with `block_reason`, not a separate status.

Provider policy или внешний orchestrator проверяет `independence_verified` по provenance: reviewer subject не должен совпадать с author/implementation subject.

## hermes-release

Назначение: принять fail-closed решение на следующем этапе progressive delivery.

- Built-ins: `skills`, `todo`; `terminal`, `file`, `clarify` и delegation отключены.
- Read tools: GitHub Actions evidence only in the GitHub MVP.
- Mutations: none until native release/deployment tools are discovered and scoped.
- Нет Kubernetes service-account token, kubeconfig или исходного кода.
- Exit states: `NO_ACTION` or `BLOCKED_NO_ACTION` in the GitHub MVP.

Deployment promotion/abort requires a separate policy-enforced integration outside the current GitHub-only MCP allowlist.

## hermes-incident

Назначение: диагностировать incident и применить только заранее утверждённую, обратимую mitigation.

- Built-ins: `skills`, `todo`; нет shell/filesystem/delegation.
- Read tools: GitHub issues.
- Mutations: GitHub issue comments only in the GitHub MVP.
- Feature flags and runbooks require separate policy-enforced integrations outside the current GitHub-only MCP allowlist.
- Exit states: `MONITORING`, `ESCALATED`, `NO_ACTION`.

Никакой generic infrastructure operation не публикуется. Если mitigation отсутствует в allowlist, правильный результат — human escalation.

## hermes-learning

Назначение: превратить повторяемые outcomes/feedback в proposal с измеримым evaluation plan.

- Built-ins: `skills`, `todo`, `clarify`; file/terminal/delegation отключены.
- Native `skill_manage` остаётся gated: `guard_agent_created: true`, `write_approval: true`.
- Read tools: GitHub issues.
- Write tools: GitHub issue comment/create for human-reviewed proposals.
- Нет `skills_activate/install/publish` и прямого docs write.
- Exit state: `PROPOSED_FOR_HUMAN_REVIEW`.
- Learning may also return `NO_ACTION` when no safe proposal is justified by the evidence.

## Orchestrator state machine

The role-local orchestrator uses canonical runtime status enums and revision-aware assignment keys (`v2:<revision>`). Issue revisions are based on semantic content, not provider `updated_at`, so orchestrator comments and labels do not create new assignments by themselves. Completed Hermes runs must return strict JSON; regex/free-text status extraction is not part of the reconciliation path. Valid final statuses are stored in SQLite, and the transition layer records the next handoff. Provider issue label/comment mutations are controlled by `ORCHESTRATOR_APPLY_TRANSITIONS` and default to disabled; `ORCHESTRATOR_TRANSITION_COMMENT_ONLY=true` is a canary mode that writes comments only and does not start downstream label-based roles.

`sdlc_orchestrator status` includes `apply_transitions` and `transition_comment_only` so operators can identify disabled, comment-only canary, and label-changing modes.

Human approver и activation pipeline являются отдельными identities. Learning agent не может одобрить собственный pending change.

## Shared skills superset

Все роли подключают общий каталог `/opt/hermes-shared-skills/current` через `skills.external_dirs`. Источник по умолчанию: `https://github.com/stanta/skills_superset.git`, ветка/refs `main`, подкаталог `skills/`.

Docker Compose обновляет каталог сервисом `skills-superset-sync` до запуска агентов. Kubernetes обновляет каталог initContainer-ом `sync-shared-skills` в каждом Pod. Основные agent containers монтируют результат read-only; изменения skills не должны писаться в общий каталог.

## Environment files

`.env` содержит общие runtime-параметры и repository target:

| Variable                         | Назначение                                                     |
| -------------------------------- | -------------------------------------------------------------- |
| `OPENAI_API_KEY`                 | общий LLM/OpenRouter token, передаётся всем Hermes containers  |
| `GIT_PROVIDER_MCP_URL`           | official GitHub MCP endpoint, `https://api.githubcopilot.com/mcp/` |
| `PLANNER_GITHUB_MCP_TOKEN`       | GitHub MCP credential for `hermes-planner`; mapped to container `GIT_PROVIDER_MCP_TOKEN` |
| `PROJECT_MANAGER_GITHUB_MCP_TOKEN` | GitHub MCP credential for `hermes-project-manager`; mapped to container `GIT_PROVIDER_MCP_TOKEN` |
| `BUILDER_GITHUB_MCP_TOKEN`       | GitHub MCP credential for `hermes-builder`; mapped to container `GIT_PROVIDER_MCP_TOKEN` |
| `REVIEWER_GITHUB_MCP_TOKEN`      | GitHub MCP credential for `hermes-reviewer`; mapped to container `GIT_PROVIDER_MCP_TOKEN` |
| `RELEASE_GITHUB_MCP_TOKEN`       | GitHub MCP credential for `hermes-release`; mapped to container `GIT_PROVIDER_MCP_TOKEN` |
| `INCIDENT_GITHUB_MCP_TOKEN`      | GitHub MCP credential for `hermes-incident`; mapped to container `GIT_PROVIDER_MCP_TOKEN` |
| `LEARNING_GITHUB_MCP_TOKEN`      | GitHub MCP credential for `hermes-learning`; mapped to container `GIT_PROVIDER_MCP_TOKEN` |
| `HERMES_ORCHESTRATOR_IMAGE`      | derived image with supercronic/wrapper/orchestrator code for Compose |
| `ORCHESTRATOR_ENABLED`           | глобальный default, должен оставаться `false` до canary rollout       |
| `ORCHESTRATOR_PROVIDER`          | provider discovery adapter, `github` или `gitlab`                     |
| `ORCHESTRATOR_CRON_SCHEDULE`     | cron schedule для `run-once`, default `*/5 * * * *`                   |
| `ORCHESTRATOR_MAX_STARTS_PER_TICK` | максимум новых Hermes runs за один tick                             |
| `ORCHESTRATOR_RUN_TIMEOUT_SECONDS` | timeout budget, сохраняется как config для reconciliation policy     |
| `REPOSITORY_ID`                  | стабильный repository ID для provider API/MCP calls            |
| `REPOSITORY_PROVIDER`            | provider, сейчас `github`                                      |
| `REPOSITORY_ACCESS_MODE`         | режим доступа, сейчас `github-direct-api-mcp`                  |
| `REPOSITORY_DEFAULT_BRANCH`      | default branch, используемый как expected base                 |
| `REPOSITORY_CLONE_ALLOWED`       | должно быть `false`; Hermes не клонирует repo                  |
| `GITHUB_API_BASE_URL`            | GitHub API base URL                                            |
| `GITHUB_WEB_BASE_URL`            | GitHub web base URL                                            |
| `GITHUB_OWNER`                   | GitHub owner/org, сейчас `test-project`                        |
| `GITHUB_REPOSITORY`              | GitHub repository name, сейчас `test-project`                  |
| `GITHUB_REPOSITORY_FULL_NAME`    | `owner/repo`, сейчас `test-project/test-project`               |
| `GITHUB_REPOSITORY_HTML_URL`     | web URL репозитория                                            |
| `GITHUB_REPOSITORY_API_URL`      | API URL репозитория                                            |

Каждый `secrets/hermes-<role>.env` содержит role-scoped secrets:

| Variable                | Назначение                                        |
| ----------------------- | ------------------------------------------------- |
| `HERMES_MODEL_ID`       | model ID в разрешённом gateway catalog            |
| `HERMES_MODEL_BASE_URL` | internal OpenAI-compatible endpoint               |
| `API_SERVER_KEY`        | inbound Hermes API bearer key, минимум 8 символов |
| `API_SERVER_MODEL_NAME` | стабильное имя роли в `/v1/models`                |
| `ORCHESTRATOR_GITHUB_TOKEN` | role-local read-only token для issue discovery |
| `ORCHESTRATOR_GITLAB_TOKEN` | role-local read-only token для GitLab discovery, пусто если не используется |

Не добавляйте `OPENAI_API_KEY`, `GIT_PROVIDER_MCP_TOKEN`, `GATEWAY_ALLOW_ALL_USERS`, kubeconfig/cloud tokens, admin PAT или broad GitHub PAT в role env-файлы. `OPENAI_API_KEY` и role-specific `*_GITHUB_MCP_TOKEN` берутся из `.env` и передаются контейнерам через Compose environment. `ORCHESTRATOR_GITHUB_TOKEN` должен быть read-only для поиска issues и не заменяет GitHub MCP credential агента. Для chat platforms задайте явные user allowlists отдельно; bundle рассчитан прежде всего на internal API orchestrator.
