# Hermes SDLC Agents

Готовый набор из шести изолированных Hermes Agent ролей для управляемого SDLC. В комплект входят реальные `config.yaml` и `SOUL.md`, Hermes profile distributions, Docker Compose, Kubernetes/Kustomize-шаблон, общий read-only superset skills, server-side policy для прямой GitHub/GitLab API/MCP интеграции, bootstrap, structural validation и smoke tests.

English version: [README.md](README.md).

## Главное архитектурное решение

`SOUL.md` управляет поведением модели, но не является границей безопасности. `tools.include` уменьшает видимую поверхность provider MCP, однако окончательное решение обязаны повторно принимать GitHub/GitLab API permissions, provider MCP policy layer, branch protection и CI rules. Поэтому полномочия фиксируются сразу в нескольких независимых слоях:

1. Отдельный Hermes profile/state для каждой роли.
2. Отдельный контейнер или Pod и отдельный входной API key.
3. Отдельный короткоживущий Git provider MCP token для каждой роли.
4. Exact allowlist GitHub/GitLab API/MCP tools в `config.yaml`.
5. Та же allowlist и argument constraints на сервере через OPA/эквивалент.
6. Отдельные upstream provider identities/scopes для ролей.
7. Server-side branch protection, protected paths, approvals и immutable release candidates.
8. Отсутствие Kubernetes service-account token у самих агентов.
9. Общий каталог skills монтируется read-only и используется через `skills.external_dirs`; skill writes остаются gated human approval.

Официальная документация Hermes прямо разделяет profile и sandbox: profile изолирует состояние, но сам по себе не ограничивает файловую систему. Отдельные контейнеры рекомендованы, когда нужны разные credentials, network segmentation и меньший blast radius. См. [Profiles](https://hermes-agent.nousresearch.com/docs/user-guide/profiles/) и [Docker](https://hermes-agent.nousresearch.com/docs/user-guide/docker/).

## Роли

| Роль              | Разрешено                                                                                          | Жёстко исключено                                                                                                      |
| ----------------- | -------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `hermes-planner`  | requirements/code/catalog/skills read; `spec` и `plan` create/update                               | code write, branch/change request, deployment, production, skill mutation                                             |
| `hermes-builder`  | skills read, repository read, task branch, patch/change-set, CI/workspace evidence, change request | local checkout, broad GitHub/GitLab credentials, merge, protected branch, production, quality-gate mutation, skill mutation |
| `hermes-reviewer` | skills/change request/diff/tests/findings read; comments, approve/request changes                  | author-branch mutation, merge, production, skill mutation                                                             |
| `hermes-release`  | skills/CI/quality/SLO read; promote или abort существующего candidate                              | arbitrary `kubectl`, code/config changes, direct traffic editing, skill mutation                                      |
| `hermes-incident` | skills/telemetry read; flag disable; approved runbook execute                                      | flag enable/retarget, arbitrary infrastructure operations, code, skill mutation                                       |
| `hermes-learning` | aggregated outcomes/docs/skills read; proposal/staged skill write                                  | independent activation/publication, direct docs/code/production write                                                 |

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

Репозитории не монтируются в agent containers. В MVP Hermes agents напрямую подключаются к role-scoped GitHub/GitLab API/MCP endpoint `GIT_PROVIDER_MCP_URL`. Hermes видит только узкие allowlisted repository tools: read/tree/search, task branch, patch/commit, change request, review comments и CI evidence.

Для builder это означает:

- нет `REPO_DIR` и `/workspace/repo`;
- нет broad GitHub/GitLab token в контейнере агента; используется только короткоживущий role-scoped provider MCP token;
- изменения передаются как bounded patch/change-set через `repo_apply_patch`/`repo_commit_changes`;
- task branch всегда имеет prefix `agent/<work-item-id>-`;
- Pull Request и GitLab Merge Request представлены в workflow как `change_request`;
- `PR_READY_FOR_REVIEW` допустим только после CI/workspace evidence.

Если для проекта нужны локальные проверки до открытия change request, запускайте их в отдельном ephemeral workspace worker или trusted CI с теми же repository scopes. Worker может клонировать репозиторий, применить patch, выполнить allowlisted checks и push-нуть task branch через role-scoped credentials, но Hermes получает только typed status/evidence.

Подробное описание флоу:

- [Repository API/MCP Flow — English](docs/REPOSITORY_API_MCP_FLOW_EN.md)
- [Флоу доступа к репозиториям через API/MCP — Русский](docs/REPOSITORY_API_MCP_FLOW_RU.md)

## Быстрый запуск через Docker Compose

Требования: Docker Engine с Compose v2, OpenAI-совместимый LLM gateway и Streamable HTTP GitHub/GitLab API/MCP endpoint по контракту из `docs/GIT_PROVIDER_INTEGRATION.md`. Compose предназначен для локального/single-host запуска; production egress ограничьте firewall/egress proxy или используйте Kubernetes NetworkPolicy из bundle.

```bash
cd hermes-sdlc-agents
scripts/bootstrap.sh
```

Затем:

1. В `.env` зафиксируйте `HERMES_IMAGE` по immutable digest.
2. Оставьте GitHub repository target `test-project/test-project` в `.env.example` и задайте `GIT_PROVIDER_MCP_URL` для прямого GitHub/GitLab API/MCP endpoint.
3. В каждом `secrets/hermes-*.env` замените все `CHANGE_ME`.
4. Выпустите шесть разных `GIT_PROVIDER_MCP_TOKEN`; один token нельзя использовать для двух ролей.
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

В MVP отдельный repository gateway не используется. Hermes roles подключаются напрямую к GitHub/GitLab API/MCP, а остальной control plane остаётся отдельными narrow integrations:

- GitHub или GitLab для repository/change request/review и branch protection через прямой provider API/MCP endpoint;
- OpenProject для work items/requirements;
- Backstage Catalog для сервисов, владельцев и зависимостей;
- Woodpecker CI, Tekton или Jenkins для CI evidence;
- Semgrep, Gitleaks, Trivy, OSV-Scanner, OpenSSF Scorecard, SonarQube Community Build и mutation tools для quality findings;
- Argo CD + Argo Rollouts для immutable candidate status, promote и abort;
- Prometheus, Loki, Tempo и OpenTelemetry для bounded telemetry queries;
- Unleash для one-way `flags_disable`;
- AWX или Rundeck Community для approved, versioned runbooks;
- OPA для authorisation и argument-level policy;
- OpenBao/SOPS/External Secrets Operator для выдачи и ротации секретов.

Не выдавайте Hermes broad GitHub/GitLab token, Kubernetes kubeconfig, Argo admin token, cloud credential или shell на runner. В MVP допустим только короткоживущий role-scoped provider token, ограниченный allowlisted repository operations.

## Перед включением автоматики

- Проведите negative canary для каждой роли: попросите planner изменить код, builder merge-нуть main, release выполнить `kubectl`, incident включить flag, learning активировать skill. Каждый запрос должен завершиться без изменяющей операции.
- Проверьте denial не только по ответу модели, но и по audit log provider MCP/upstream.
- Убедитесь, что `hermes-builder` не может изменить файл из `policies/protected-paths.txt` через `repo_apply_patch`/`repo_commit_changes` без отдельного server-side CI gate и human approval.
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
