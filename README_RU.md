#  HermeTeam - Hermes-based SDLC AI Agents Team

Готовый набор из шести изолированных Hermes Agent ролей для управляемого SDLC. В комплект входят реальные `config.yaml` и `SOUL.md`, Hermes profile distributions, Docker Compose, Kubernetes/Kustomize-шаблон, общий read-only superset skills, server-side policy для MVP на официальном GitHub MCP Server, bootstrap, structural validation и smoke tests.

English version: [README.md](README.md).

## Главное архитектурное решение

`SOUL.md` управляет поведением модели, но не является границей безопасности. `tools.include` уменьшает видимую поверхность official GitHub MCP, однако окончательное решение обязаны повторно принимать GitHub token scopes, branch protection, GitHub rulesets, CI rules и provider-side OPA layer. Поэтому полномочия фиксируются сразу в нескольких независимых слоях:

1. Отдельный Hermes profile/state для каждой роли.
2. Отдельный контейнер или Pod и отдельный входной API key.
3. Отдельный GitHub credential, принимаемый official GitHub MCP Server, для каждой роли.
4. Exact allowlist native GitHub MCP tools в `config.yaml`.
5. Та же allowlist и argument constraints на сервере через OPA/эквивалент.
6. Отдельные upstream GitHub identities/scopes для ролей.
7. Server-side branch protection, protected paths, approvals и immutable release candidates.
8. Отсутствие Kubernetes service-account token у самих агентов.
9. Общий каталог skills монтируется read-only и используется через `skills.external_dirs`; skill writes остаются gated human approval.

Официальная документация Hermes прямо разделяет profile и sandbox: profile изолирует состояние, но сам по себе не ограничивает файловую систему. Отдельные контейнеры рекомендованы, когда нужны разные credentials, network segmentation и меньший blast radius. См. [Profiles](https://hermes-agent.nousresearch.com/docs/user-guide/profiles/) и [Docker](https://hermes-agent.nousresearch.com/docs/user-guide/docker/).

## Роли

| Роль              | Разрешено                                                                                          | Жёстко исключено                                                                                                      |
| ----------------- | -------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `hermes-planner`  | GitHub repository/file/tree/search и issue reads                                                    | code write, branch/PR creation, deployment, production, skill mutation                                                |
| `hermes-builder`  | GitHub repository read, создание `agent/*` branch, `push_files`, PR creation, Actions evidence      | local checkout, broad GitHub credentials, merge, protected branch, production, quality-gate mutation, skill mutation  |
| `hermes-reviewer` | PR/file/Actions reads и issue/PR comments                                                           | author-branch mutation, merge, production, skill mutation                                                             |
| `hermes-release`  | GitHub Actions read-only evidence для MVP                                                           | deployment mutation, пока native release/deployment tools не обнаружены и не ограничены                              |
| `hermes-incident` | GitHub issue read/comment для MVP                                                                   | flags, runbooks, infrastructure operations, code, skill mutation                                                      |
| `hermes-learning` | GitHub issue read/comment/create для human-reviewed improvement proposals                            | independent activation/publication, direct docs/code/production write                                                 |

Точные разрешённые имена инструментов находятся одновременно в `profiles/*/config.yaml` и `policies/roles.yaml`. `scripts/validate.sh` завершится ошибкой, если списки разойдутся.

## Структура

```text
hermes-sdlc-agents/
├── compose.yaml                  # один контейнер на роль
├── kustomization.yaml            # Kubernetes deployment через Kustomize
├── profiles/
│   └── hermes-*/
│       ├── .gitignore            # исключает credentials и runtime state
│       ├── distribution.yaml     # Hermes profile distribution manifest
│       ├── config.yaml           # managed role config
│       ├── SOUL.md               # identity, process, stop conditions
│       └── skills/               # role-safe shared skills, including self-evolution
├── orchestrator/                  # role-local cron discovery issues и submitter в /v1/runs
├── policies/
│   ├── roles.yaml                # каноническая role/tool/constraint matrix
│   ├── mcp-policy.rego           # пример server-side OPA decision
│   └── protected-paths.txt       # quality/CI/prod paths для отдельного gate
├── secrets/*.env.example         # только шаблоны, без секретов
├── docs/
│   ├── REPOSITORY_API_MCP_FLOW_EN.md
│   ├── REPOSITORY_API_MCP_FLOW_RU.md
│   ├── GIT_PROVIDER_INTEGRATION.md
│   ├── SECURITY.md
│   └── OPERATIONS.md
├── kubernetes/
└── scripts/
```

## Общий superset skills

Каждая роль имеет включённый Hermes toolset `skills` и два external skill directories:

- `/etc/hermes/skills` — skills, поставляемые вместе с конкретным role profile;
- `/opt/hermes-shared-skills/current` — общий read-only superset из `https://github.com/stanta/skills_superset/tree/main/skills`.

В Docker Compose сервис `skills-superset-sync` перед запуском агентов обновляет named volume `shared-skills` из `SKILLS_SUPERSET_REPO_URL`/`SKILLS_SUPERSET_REF`; агенты ждут его успешного завершения и монтируют volume read-only. В Kubernetes каждый Pod использует initContainer `sync-shared-skills`, который клонирует тот же репозиторий в `emptyDir`, после чего основной контейнер видит каталог read-only.

Это даёт агентам динамический выбор релевантных skills через `skills_list`/`skill_view`, но не расширяет Git provider API/MCP allowlist. Мутации skills по-прежнему требуют `skills.write_approval: true`; роли, кроме `hermes-learning`, должны оформлять улучшения skills как handoff/proposal, а не менять их напрямую.

## Repository API/MCP flow

Репозитории не монтируются в agent containers. В GitHub MVP Hermes agents напрямую подключаются к official GitHub MCP endpoint `GIT_PROVIDER_MCP_URL=https://api.githubcopilot.com/mcp/`. Hermes видит только узкие allowlisted native GitHub MCP tools, подтверждённые runtime `tools/list`.

Для builder это означает:

- нет `REPO_DIR` и `/workspace/repo`;
- нет broad GitHub token в контейнере агента; Compose маппит role-specific token из `.env`, например `BUILDER_GITHUB_MCP_TOKEN`, во внутренний `GIT_PROVIDER_MCP_TOKEN` контейнера;
- изменения передаются через native GitHub MCP tools, например `create_branch`, `push_files` и `create_pull_request`;
- task branch всегда имеет prefix `agent/<work-item-id>-`;
- GitHub Pull Requests являются MVP-механизмом change request;
- `PR_READY_FOR_REVIEW` допустим только после CI/workspace evidence.

Если для проекта нужны локальные проверки до открытия change request, запускайте их в отдельном ephemeral workspace worker или trusted CI с теми же repository scopes. Worker может клонировать репозиторий, применить patch, выполнить allowlisted checks и push-нуть task branch через role-scoped credentials, но Hermes получает только typed status/evidence.

Подробное описание флоу:

- [Repository API/MCP Flow — English](docs/REPOSITORY_API_MCP_FLOW_EN.md)
- [Флоу доступа к репозиториям через API/MCP — Русский](docs/REPOSITORY_API_MCP_FLOW_RU.md)

## Role-local cron orchestrator

В bundle добавлен отключённый по умолчанию cron orchestrator в `orchestrator/`. Каждый role container запускает один и тот же wrapper, пишет минимальный cron env file в `/opt/data/sdlc-orchestrator/`, ищет provider issues своим read-only `ORCHESTRATOR_GITHUB_TOKEN`, дедуплицирует назначения в локальном SQLite и отправляет runs только в `http://127.0.0.1:8642/v1/runs` с собственным `API_SERVER_KEY` контейнера.

Compose собирает `Dockerfile.orchestrator` от зафиксированного `HERMES_IMAGE`, добавляет `supercronic` и монтирует `./orchestrator` read-only для локальной итерации. Kubernetes ожидает тот же код внутри image `hermes-sdlc-agent-orchestrator`. Держите `ORCHESTRATOR_ENABLED=false`, пока canary не пройдёт отдельно для каждой роли.

## Быстрый запуск через Docker Compose

Требования: Docker Engine с Compose v2, OpenAI-совместимый LLM gateway и GitHub credentials, принимаемые official GitHub MCP Server. Compose предназначен для локального/single-host запуска; production egress ограничьте firewall/egress proxy или используйте Kubernetes NetworkPolicy из bundle.

```bash
cd hermes-sdlc-agents
scripts/bootstrap.sh
```

Затем:

1. В `.env` зафиксируйте `HERMES_IMAGE` по immutable digest.
2. Оставьте GitHub repository target `test-project/test-project` в `.env.example` и `GIT_PROVIDER_MCP_URL=https://api.githubcopilot.com/mcp/` для GitHub MVP.
3. В каждом `secrets/hermes-*.env` замените все `CHANGE_ME`, включая role-local read-only `ORCHESTRATOR_GITHUB_TOKEN` перед включением cron.
4. Задайте шесть разных GitHub MCP tokens в основном `.env`: `PLANNER_GITHUB_MCP_TOKEN`, `BUILDER_GITHUB_MCP_TOKEN`, `REVIEWER_GITHUB_MCP_TOKEN`, `RELEASE_GITHUB_MCP_TOKEN`, `INCIDENT_GITHUB_MCP_TOKEN` и `LEARNING_GITHUB_MCP_TOKEN`. Один token нельзя использовать для двух ролей.
5. Проверьте конфигурацию:

```bash
scripts/validate.sh
```

6. Запустите:

```bash
docker compose up -d
scripts/smoke-test.sh
```

API по умолчанию доступен только на loopback хоста:

| Роль     | URL                         |
| -------- | --------------------------- |
| planner  | `http://127.0.0.1:18642/v1` |
| builder  | `http://127.0.0.1:18643/v1` |
| reviewer | `http://127.0.0.1:18644/v1` |
| release  | `http://127.0.0.1:18645/v1` |
| incident | `http://127.0.0.1:18646/v1` |
| learning | `http://127.0.0.1:18647/v1` |

Hermes API требует Bearer key и поддерживает `/v1/responses`, `/v1/runs`, `/health` и authenticated `/health/detailed`; см. [официальный API Server reference](https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server/).

Пример canary-вызова planner:

```bash
set -a
source secrets/hermes-planner.env
set +a
curl --fail http://127.0.0.1:18642/v1/responses \
  -H "Authorization: Bearer ${API_SERVER_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{"model":"hermes-planner","input":"Прочитай REQ-123 и создай только черновик spec; не меняй код."}'
```

Не передавайте через внешний request поле `provider`: в конфигурациях отключён `direct_model_requests`, чтобы клиент не мог выбрать иной provider/model route.

## Установка как локальных Hermes profiles

Каждая директория в `profiles/` является Hermes profile distribution. Для разработки их можно установить в уже существующий Hermes:

```bash
scripts/install-profiles.sh
```

Или одну роль:

```bash
hermes profile install ./profiles/hermes-reviewer --alias --yes
```

Такой режим удобен, но не даёт жёсткой OS/network isolation. Для production используйте отдельные контейнеры/Pods. Формат distributions описан в [Hermes Profile Distributions](https://hermes-agent.nousresearch.com/docs/user-guide/profile-distributions).

## Почему конфиг монтируется в `/etc/hermes`

Compose и Kubernetes устанавливают `HERMES_MANAGED_DIR=/etc/hermes` и монтируют role config read-only. Managed scope имеет приоритет над пользовательским `config.yaml`, поэтому агент не может включить terminal или расширить MCP allowlist через обычный `hermes config set`. Это дополнительный control plane, но не самостоятельный sandbox; окончательные запреты остаются на MCP/upstream сторонах. См. [Managed Scope](https://hermes-agent.nousresearch.com/docs/user-guide/managed-scope).

## Необходимый open-source control plane

В GitHub MVP отдельный repository gateway не используется. Hermes roles подключаются напрямую к official GitHub MCP Server. GitLab support является future work и требует отдельного tool mapping. Возможности вне GitHub repository, issue, PR и Actions tools остаются отдельными integrations или blocked для MVP:

- GitHub для repository/Pull Request/review и branch protection через official GitHub MCP endpoint;
- OpenProject для work items/requirements;
- Backstage Catalog для сервисов, владельцев и зависимостей;
- Woodpecker CI, Tekton или Jenkins для CI evidence;
- Semgrep, Gitleaks, Trivy, OSV-Scanner, OpenSSF Scorecard, SonarQube Community Build и mutation tools для quality findings;
- Argo CD + Argo Rollouts для immutable candidate status, promote и abort;
- Prometheus, Loki, Tempo и OpenTelemetry для bounded telemetry queries;
- Unleash для feature flags через отдельную future integration, не через GitHub MCP allowlist;
- AWX или Rundeck Community для approved, versioned runbooks через отдельную future integration;
- OPA для authorisation и argument-level policy;
- OpenBao/SOPS/External Secrets Operator для выдачи и ротации секретов.

Не выдавайте Hermes broad GitHub token, Kubernetes kubeconfig, Argo admin token, cloud credential или shell на runner. В MVP допустим только role-specific GitHub credential, ограниченный allowlisted repository operations.

## Перед включением автоматики

- Проведите negative canary для каждой роли: попросите planner изменить код, builder merge-нуть main, release выполнить `kubectl`, incident включить flag, learning активировать skill. Каждый запрос должен завершиться без изменяющей операции.
- Проверьте denial не только по ответу модели, но и по audit log provider MCP/upstream.
- Убедитесь, что `hermes-builder` не может изменить файл из `policies/protected-paths.txt` через `push_files` без отдельного server-side CI gate и human approval.
- Убедитесь, что tokens имеют разные `sub`, `role`, `jti`, TTL ≤ 1 час и аудит связывает tool call с Hermes run/session/work item.
- Зафиксируйте image digest; `latest` оставлен только как удобное значение для первого локального запуска.

Подробности:

- [Repository API/MCP Flow — English](docs/REPOSITORY_API_MCP_FLOW_EN.md)
- [Флоу доступа к репозиториям через API/MCP — Русский](docs/REPOSITORY_API_MCP_FLOW_RU.md)
- [Configuration reference](docs/CONFIGURATION_REFERENCE.md)
- [Git provider integration contract](docs/GIT_PROVIDER_INTEGRATION.md)
- [Security model](docs/SECURITY.md)
- [Operations runbook](docs/OPERATIONS.md)
- [Official sources](docs/SOURCES.md)
