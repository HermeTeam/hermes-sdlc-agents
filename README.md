# Hermes SDLC Agents

Готовый набор из шести изолированных Hermes Agent ролей для управляемого SDLC. В комплект входят реальные `config.yaml` и `SOUL.md`, Hermes profile distributions, Docker Compose, Kubernetes/Kustomize-шаблон, server-side policy для MCP gateway, bootstrap, structural validation и smoke tests.

## Главное архитектурное решение

`SOUL.md` управляет поведением модели, но не является границей безопасности. `tools.include` уменьшает видимую поверхность MCP, однако окончательное решение обязан повторно принимать MCP gateway. Поэтому полномочия фиксируются сразу в нескольких независимых слоях:

1. Отдельный Hermes profile/state для каждой роли.
2. Отдельный контейнер или Pod и отдельный входной API key.
3. Отдельный короткоживущий MCP token с claim `role`.
4. Exact allowlist MCP tools в `config.yaml`.
5. Та же allowlist и argument constraints на сервере через OPA/эквивалент.
6. Отдельные upstream service accounts у MCP gateway.
7. Server-side branch protection, protected paths, approvals и immutable release candidates.
8. Отсутствие Kubernetes service-account token у самих агентов.

Официальная документация Hermes прямо разделяет profile и sandbox: profile изолирует состояние, но сам по себе не ограничивает файловую систему. Отдельные контейнеры рекомендованы, когда нужны разные credentials, network segmentation и меньший blast radius. См. [Profiles](https://hermes-agent.nousresearch.com/docs/user-guide/profiles/) и [Docker](https://hermes-agent.nousresearch.com/docs/user-guide/docker/).

## Роли

| Роль | Разрешено | Жёстко исключено |
|---|---|---|
| `hermes-planner` | requirements/code/catalog read; `spec` и `plan` create/update | code write, branch/PR, deployment, production |
| `hermes-builder` | task worktree, code/tests, local checks, task-branch push, PR | merge, protected branch, production, quality-gate mutation |
| `hermes-reviewer` | PR/diff/tests/findings read; comments, approve/request changes | author-branch mutation, merge, production |
| `hermes-release` | CI/quality/SLO read; promote или abort существующего candidate | arbitrary `kubectl`, code/config changes, direct traffic editing |
| `hermes-incident` | telemetry read; flag disable; approved runbook execute | flag enable/retarget, arbitrary infrastructure operations, code |
| `hermes-learning` | aggregated outcomes/docs/skills read; proposal/staged skill write | independent activation/publication, direct docs/code/production write |

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
│       └── SOUL.md               # identity, process, stop conditions
├── policies/
│   ├── roles.yaml                # каноническая role/tool/constraint matrix
│   ├── mcp-policy.rego           # пример server-side OPA decision
│   └── protected-paths.txt       # quality/CI/prod paths для отдельного gate
├── secrets/*.env.example         # только шаблоны, без секретов
├── docs/
│   ├── MCP_CONTRACT.md
│   ├── SECURITY.md
│   └── OPERATIONS.md
├── kubernetes/
└── scripts/
```

## Быстрый запуск через Docker Compose

Требования: Docker Engine с Compose v2, writable clone проекта для builder, OpenAI-совместимый LLM gateway и Streamable HTTP SDLC MCP gateway с контрактом из `docs/MCP_CONTRACT.md`. Compose предназначен для локального/single-host запуска; production egress ограничьте firewall/egress proxy или используйте Kubernetes NetworkPolicy из bundle.

```bash
cd hermes-sdlc-agents
scripts/bootstrap.sh
```

Затем:

1. В `.env` укажите абсолютный `REPO_DIR` и зафиксируйте `HERMES_IMAGE` по immutable digest.
2. В каждом `secrets/hermes-*.env` замените все `CHANGE_ME`.
3. Выпустите шесть разных MCP tokens; один token нельзя использовать для двух ролей.
4. Проверьте конфигурацию:

```bash
scripts/validate.sh
```

5. Запустите:

```bash
docker compose up -d
scripts/smoke-test.sh
```

API по умолчанию доступен только на loopback хоста:

| Роль | URL |
|---|---|
| planner | `http://127.0.0.1:18642/v1` |
| builder | `http://127.0.0.1:18643/v1` |
| reviewer | `http://127.0.0.1:18644/v1` |
| release | `http://127.0.0.1:18645/v1` |
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

SDLC MCP gateway должен быть вашим тонким типизированным фасадом. Его можно собрать поверх:

- Forgejo для repository/PR/review и branch protection;
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

Не выдавайте Hermes прямой токен Forgejo admin, Kubernetes kubeconfig, Argo admin token, cloud credential или shell на runner. MCP gateway хранит upstream credentials у себя и выдаёт агенту только узкие операции.

## Перед включением автоматики

- Проведите negative canary для каждой роли: попросите planner изменить код, builder merge-нуть main, release выполнить `kubectl`, incident включить flag, learning активировать skill. Каждый запрос должен завершиться без изменяющей операции.
- Проверьте denial не только по ответу модели, но и по audit log MCP/upstream.
- Убедитесь, что `hermes-builder` не может изменить файл из `policies/protected-paths.txt` без отдельного server-side CI gate и human approval.
- Убедитесь, что tokens имеют разные `sub`, `role`, `jti`, TTL ≤ 1 час и аудит связывает tool call с Hermes run/session/work item.
- Зафиксируйте image digest; `latest` оставлен только как удобное значение для первого локального запуска.

Подробности находятся в [configuration reference](docs/CONFIGURATION_REFERENCE.md), [MCP contract](docs/MCP_CONTRACT.md), [security model](docs/SECURITY.md), [operations runbook](docs/OPERATIONS.md) и [списке официальных источников](docs/SOURCES.md).
