# HermeTeam — Safe AI SDLC на базе Hermes Agents

**HermeTeam — reference implementation подхода Safe AI SDLC: security-first архитектуры автономной разработки ПО, в которой AI-агенты могут планировать, писать код, ревьюить и участвовать в эксплуатации, но их identity, authority и consequential actions остаются независимо контролируемыми.**

Проект начинался как практическая multi-agent SDLC-команда на базе Hermes Agent. Эта основа сохраняется: Planner, Project Manager, Builder, Reviewer, Release, Incident и Learning выполняют реальную работу через раздельные profiles, containers, credentials и tool surfaces. По мере роста автономности HermeTeam добавляет control plane, который делает эту автономность наблюдаемой, ограниченной и управляемой.

> **Больше автономности требует больше контроля, а не больше доверия.**

English version: [README.md](README.md).

## Safe AI SDLC

Обычная AI-assisted разработка часто развивается так:

```text
более способная модель
        ↓
больше tools
        ↓
больше permissions
        ↓
больше autonomy
```

HermeTeam использует другую модель:

```text
больше capability
       +
больше observability
       +
более узкая authority
       +
независимая verification
       ↓
больше safe autonomy
```

Подход строится вокруг шести принципов:

1. **Identity и authority разделяются по ролям.** Planner, Builder, Reviewer, Release и другие роли не должны использовать одну human identity или broad credential.
2. **Intent не равен execution.** То, что модель предлагает сделать, и то, какой tool call реально выполняет runtime, рассматриваются как разные security-relevant события.
3. **Сначала observe, потом enforce.** Сначала собираются evidence и shadow-mode сигналы, затем blocking включается только там, где реальный риск это оправдывает.
4. **Агент не авторизует сам себя.** Prompt и `SOUL.md` формируют поведение; credentials, provider controls и policy определяют полномочия.
5. **Автоматизируются reversible actions, consequential transitions контролируются отдельно.** Human approval нужен около merge, production, permission escalation и других high-impact границ, а не на каждом низкорисковом шаге.
6. **Проверяется outcome, а не только intent.** Зрелая Safe AI SDLC система проверяет состояние, возникшее после execution, а не только model response или `success=true` от tool.

## Направление архитектуры

HermeTeam развивается от реального AI SDLC runtime к control plane для governed autonomy:

```text
GitHub Issue / Requirement
          │
          ▼
┌─────────────────────────────┐
│ AI SDLC Team                │
│ Planner · PM · Builder      │
│ Reviewer · Release          │
│ Incident · Learning         │
└─────────────┬───────────────┘
              │
              ▼
        Flight Recorder
   что агент видел и делал?
              │
              ▼
          Intent Risk
     что он намерен сделать?
              │
              ▼
          Action Gate
 что он реально пытается вызвать?
              │
              ▼
       Authority Policy
      разрешено ли действие?
              │
              ▼
          GitHub / CI
              │
              ▼
        Verify Outcome
      что реально изменилось?
```

Текущий `master` реализует **AI SDLC foundation и defense-in-depth role controls**. Flight Recorder, intent/action correlation, runtime risk assessment и более жёсткий inline enforcement — следующие control-plane слои, которые должны вводиться и проверяться инкрементально, а не считаться уже полностью готовыми.

## Что реализовано сейчас

Репозиторий содержит готовую GitHub-first Hermes SDLC среду с:

- семью изолированными Hermes Agent ролями;
- отдельным profile/state для каждой роли;
- отдельными containers или Kubernetes Pods и отдельными inbound API keys;
- role-specific GitHub credentials;
- точными allowlists native GitHub MCP tools;
- каноническими role/tool constraints в `policies/roles.yaml`;
- примерами server-side OPA policy в `policies/mcp-policy.rego`;
- protected-path и branch-boundary controls;
- role-local orchestrator с SQLite workflow state;
- Docker Compose и Kubernetes/Kustomize deployment;
- общим read-only superset skills;
- structural validation и smoke tests;
- локальным read-only dashboard для operational visibility.

В GitHub MVP репозитории не монтируются внутрь agent containers. Агенты работают через scoped provider API/MCP operations, а Builder намеренно ограничен `agent/*` branches и созданием pull request — без merge и production authority.

## Главное security-решение

`SOUL.md` управляет поведением модели, но **не является границей безопасности**. `tools.include` уменьшает видимую поверхность official GitHub MCP, однако final authorization должен дополнительно обеспечиваться upstream credentials, branch protection, GitHub rulesets, CI rules и provider-side policy.

Поэтому полномочия распределены по независимым слоям:

1. Отдельный Hermes profile/state для каждой роли.
2. Отдельный container или Pod и отдельный inbound API key.
3. Отдельный GitHub credential для каждой роли.
4. Exact allowlist native GitHub MCP tools в `config.yaml`.
5. Та же allowlist и argument constraints на серверной стороне через OPA или эквивалент.
6. Отдельные upstream GitHub identities/scopes.
7. Server-side branch protection, protected paths, approvals и immutable release candidates.
8. Отсутствие Kubernetes service-account token у самих агентов.
9. Shared skills монтируются read-only; skill writes остаются gated human approval.

Hermes разделяет profile isolation и sandboxing: profile изолирует состояние, но сам по себе не ограничивает filesystem. Для разных credentials, network segmentation и меньшего blast radius используются отдельные containers/Pods. См. [Profiles](https://hermes-agent.nousresearch.com/docs/user-guide/profiles/) и [Docker](https://hermes-agent.nousresearch.com/docs/user-guide/docker/).

## Роли

| Роль | Разрешено | Жёстко исключено |
| --- | --- | --- |
| `hermes-planner` | GitHub repository/file/tree/search и issue reads | code write, branch/PR creation, deployment, production, skill mutation |
| `hermes-project-manager` | repository/file/tree/search и issue read/comment/create для PM artifacts, reports и flow governance | code write, branch/PR creation, merge, deployment, production, budget/access mutation, skill mutation |
| `hermes-builder` | repository read, создание `agent/*` branch, `push_files`, PR creation, Actions evidence | broad GitHub credentials, merge, protected branch, production, quality-gate mutation, skill mutation |
| `hermes-reviewer` | PR/file/Actions reads и issue/PR comments | author-branch mutation, merge, production, skill mutation |
| `hermes-release` | GitHub Actions read-only evidence для MVP | deployment mutation, пока native release/deployment tools явно не ограничены |
| `hermes-incident` | GitHub issue read/comment для MVP | flags, runbooks, infrastructure operations, code, skill mutation |
| `hermes-learning` | issue read/comment/create для human-reviewed improvement proposals | independent activation/publication, direct docs/code/production write |

Точные allowed tool names находятся одновременно в `profiles/*/config.yaml` и `policies/roles.yaml`. `scripts/validate.sh` завершится ошибкой, если эти списки разойдутся.

## Граница safe autonomy

Проект намеренно не строится вокруг идеи «доверять prompt». Полезная автономная работа отделяется от consequential authority.

Например Builder может:

```text
читать repository context
создавать agent/* branch
писать bounded changes
читать CI evidence
открывать pull request
```

но не должен владеть irreversible transition:

```text
писать в main/master/release/*
merge-ить pull request
изменять protected security/CI paths без independent gate
использовать Kubernetes/cloud production credentials
```

Базовое правило Safe AI SDLC:

> **Агент может предложить действие. Агент не должен сам решать, имеет ли он право его выполнить.**

## Repository API/MCP flow

В GitHub MVP Hermes agents подключаются к official GitHub MCP endpoint через role-specific credentials и узкие allowlists native tools, обнаруженные через runtime `tools/list`.

Для Builder:

- нет `REPO_DIR` и writable `/workspace/repo`;
- нет shared human PAT;
- изменения выполняются через native tools вроде `create_branch`, `push_files` и `create_pull_request`;
- task branches используют prefix `agent/<work-item-id>-`;
- GitHub Pull Request является MVP change-request boundary;
- `PR_READY_FOR_REVIEW` допустим только после необходимых CI/workspace evidence.

Если до открытия change request нужны локальные проверки, их следует выполнять в отдельном ephemeral workspace worker или trusted CI с теми же repository scopes. Hermes должен получать typed status/evidence, а не broad shell или production credential.

Подробный flow:

- [Repository API/MCP Flow — English](docs/REPOSITORY_API_MCP_FLOW_EN.md)
- [Repository API/MCP Flow — Русский](docs/REPOSITORY_API_MCP_FLOW_RU.md)

## Role-local orchestrator

В репозитории есть отключённый по умолчанию cron orchestrator в `orchestrator/`. Каждый role container запускает одинаковый wrapper, обнаруживает provider issues своим read-only orchestrator token, дедуплицирует назначения в локальном SQLite и отправляет runs только в локальный Hermes API своего контейнера.

Держите `ORCHESTRATOR_ENABLED=false`, пока canary не пройдёт отдельно для каждой роли.

## Быстрый запуск

Требования: Docker Engine с Compose v2, OpenAI-compatible LLM gateway и GitHub credentials, принимаемые official GitHub MCP Server.

```bash
cd hermes-sdlc-agents
scripts/bootstrap.sh
```

Затем:

1. Зафиксируйте `HERMES_IMAGE` по immutable digest в `.env`.
2. Замените все `CHANGE_ME`.
3. Настройте разные role-specific GitHub MCP tokens. Не используйте один token для нескольких ролей.
4. Держите repository MCP toolsets узкими, а каждой роли показывайте только её exact allowlist.
5. Проверьте конфигурацию:

```bash
scripts/validate.sh
```

6. Запустите:

```bash
docker compose up -d
scripts/smoke-test.sh
```

Secure default Compose публикует только локальный read-only central dashboard на loopback. Role APIs наружу не публикуются. Для диагностики используйте explicit loopback-only debug override:

```bash
docker compose -f compose.yaml -f compose.debug.yaml up -d
scripts/smoke-test.sh
```

## Структура репозитория

```text
hermes-sdlc-agents/
├── compose.yaml
├── compose.debug.yaml
├── dashboard/
├── orchestrator/
├── profiles/
│   └── hermes-*/
│       ├── distribution.yaml
│       ├── config.yaml
│       ├── SOUL.md
│       └── skills/
├── policies/
│   ├── roles.yaml
│   ├── mcp-policy.rego
│   └── protected-paths.txt
├── secrets/*.env.example
├── kubernetes/
├── kustomization.yaml
├── scripts/
└── docs/
```

## Roadmap: от AI SDLC к governed autonomy

Развитие должно идти инкрементально:

```text
01 OBSERVE  → Flight Recorder
02 ASSESS   → Intent / target / risk classification
03 CONTROL  → Intent ↔ actual action comparison и policy gate
04 VERIFY   → Наблюдение resulting repository/production state
05 GOVERN   → Управление agent authority, grants, revoke и drift
```

Проект не должен сразу превращаться в giant governance platform. Предпочтительный путь — сначала наблюдать реальное поведение агентов, проверять controls в shadow/canary mode и только затем помещать consequential mutations за mandatory enforcement.

## Перед включением автоматики

- Проведите negative canary для каждой роли: попросите Planner изменить код, Builder merge-нуть `main`, Release выполнить `kubectl`, Incident включить flag, Learning активировать skill. Каждый request должен завершиться без запрещённой mutation.
- Проверяйте denial через provider/upstream evidence, а не только по model response.
- Убедитесь, что `hermes-builder` не может менять protected paths без отдельного server-side gate и human approval.
- Держите role credentials раздельными и short-lived там, где это поддерживает provider.
- Для production фиксируйте image digests.

## Документация

- [Configuration reference](docs/CONFIGURATION_REFERENCE.md)
- [Git provider integration contract](docs/GIT_PROVIDER_INTEGRATION.md)
- [Security model](docs/SECURITY.md)
- [Operations runbook](docs/OPERATIONS.md)
- [Dashboard operations — English](docs/DASHBOARD.md)
- [Dashboard operations — Русский](docs/DASHBOARD_RU.md)
- [Repository API/MCP Flow — English](docs/REPOSITORY_API_MCP_FLOW_EN.md)
- [Repository API/MCP Flow — Русский](docs/REPOSITORY_API_MCP_FLOW_RU.md)
- [Official sources](docs/SOURCES.md)

## Позиционирование

HermeTeam — не ещё одна coding model и не просто multi-agent demo. Это попытка определить и реализовать **как должна быть устроена автономная AI-разработка ПО, когда агенты получают реальные tools и реальные полномочия**.

AI SDLC Team — execution foundation. Safe AI SDLC — подход. Flight Recorder, Intent Risk, Action Gate и authority governance — control layers, которые позволяют постепенно увеличивать автономность, не отдавая контроль самому агенту.
