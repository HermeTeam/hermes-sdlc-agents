# Локальное развёртывание HermeTeam

> **SMB-режим:** для одного Safe Builder с заранее подключёнными по подписке HermeTeam провайдером и моделью используйте [отдельный минимальный runtime](../smb/README.md) и `python3 scripts/smb-quickstart.py up`. Семиролевая схема ниже — расширенный/reference deployment, а не обязательный первый запуск для команды из 3–30 разработчиков. Выдача подписочного entitlement и подключение GitHub App на этом этапе являются предварительными условиями.


English version: [bootstrap.md](bootstrap.md).

Это руководство описывает безопасное и воспроизводимое локальное развёртывание текущей ветки `master` HermeTeam. Базовый AI SDLC runtime, observability и capability-governance canary включаются поэтапно, чтобы каждый слой можно было проверить до включения автоматики.

## 1. Что поднимается локально

Полный локальный canary stack включает:

- семь изолированных Hermes-ролей: Planner, Project Manager, Builder, Reviewer, Release, Incident, Learning;
- локальный HermeTeam dashboard;
- role-local доступ к GitHub MCP с отдельными credentials и точными allowlists tools;
- опциональный Builder Flight Recorder и мониторинг Langfuse;
- опциональный Capability Gateway governance canary.

Во время первичного bootstrap держите role-local orchestrator выключенным. Не считайте Capability Gateway production enforcement boundary: в текущей реализации Hermes всё ещё подключается напрямую к настроенному repository MCP endpoint, а capability resolver/governance service работает как opt-in canary.

## 2. Требования к хосту

Нужны:

```text
git
Docker Engine
Docker Compose v2
bash
curl
python3
pip
openssl
```

Для repository validation нужен PyYAML:

```bash
python3 -m pip install pyyaml
```

Проверка хоста:

```bash
docker --version
docker compose version
python3 --version
openssl version
```

Первичная сборка требует outbound-доступ к Docker registry, GitHub, выбранному LLM endpoint и repository со skills. `Dockerfile.orchestrator` загружает `supercronic` и устанавливает optional Langfuse SDK в Hermes virtual environment.

## 3. Клонировать repository

```bash
git clone https://github.com/HermeTeam/hermes-sdlc-agents.git
cd hermes-sdlc-agents
git checkout master
git pull
```

После успешного canary для воспроизводимого окружения лучше фиксировать известный commit/release, а не постоянно разворачивать изменяющийся `master`.

## 4. Выполнить bootstrap конфигурации

```bash
scripts/bootstrap.sh
```

Скрипт создаёт `.env` из `.env.example`, выставляет mode `0600` и, если доступен `openssl`, генерирует семь role-local `*_API_SERVER_KEY`.

Проверить оставшиеся placeholders:

```bash
grep 'CHANGE_ME' .env
```

Перед запуском замените все placeholders, относящиеся к включённым интеграциям.

### Текущий обязательный password native Hermes dashboard

Текущий `compose.yaml` требует `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD`. Если его ещё нет в локальном `.env`, добавьте вручную:

```bash
printf '\nHERMES_DASHBOARD_BASIC_AUTH_PASSWORD=%s\n' \
  "$(openssl rand -hex 32)" >> .env
```

Этот credential защищает native Hermes dashboards отдельных ролей, которые публикуются только при включении debug overlay. Он не относится к центральному HermeTeam dashboard.

## 5. Настроить Hermes image и LLM provider

Для первого локального запуска можно использовать default image:

```dotenv
HERMES_IMAGE=nousresearch/hermes-agent:latest
```

После успешного canary замените mutable tag на immutable digest.

Настройте OpenAI-compatible endpoint:

```dotenv
HERMES_MODEL_ID=<model-id>
HERMES_MODEL_BASE_URL=<openai-compatible-base-url>
OPENAI_API_KEY=<llm-api-key>
```

Проверьте role-specific model overrides в `.env`. Текущие defaults могут задавать отдельные модели для Builder, Incident или Learning. Если ваш provider не предоставляет такую модель, очистите или замените соответствующий override.

## 6. Настроить целевой GitHub repository

GitHub MVP работает через прямой provider API/MCP и не клонирует target repository внутрь Hermes containers.

Пример:

```dotenv
REPOSITORY_ID=my-project
REPOSITORY_PROVIDER=github
REPOSITORY_ACCESS_MODE=github-direct-api-mcp
REPOSITORY_DEFAULT_BRANCH=main
REPOSITORY_CLONE_ALLOWED=false

GITHUB_API_BASE_URL=https://api.github.com
GITHUB_WEB_BASE_URL=https://github.com
GITHUB_OWNER=my-org
GITHUB_REPOSITORY=my-repo
GITHUB_REPOSITORY_FULL_NAME=my-org/my-repo
GITHUB_REPOSITORY_HTML_URL=https://github.com/my-org/my-repo
GITHUB_REPOSITORY_API_URL=https://api.github.com/repos/my-org/my-repo

GIT_PROVIDER_MCP_URL=https://api.githubcopilot.com/mcp/
```

Для direct API/MCP режима оставляйте `REPOSITORY_CLONE_ALLOWED=false`.

## 7. Создать отдельные GitHub credentials для каждой роли

Не используйте один broad human PAT для всех ролей. Нужны fine-grained credentials, принимаемые official GitHub MCP endpoint: например fine-grained PAT или GitHub App installation token.

Рекомендуемые минимальные permissions описаны в [GIT_PROVIDER_INTEGRATION.md](GIT_PROVIDER_INTEGRATION.md). Текущая модель примерно такая:

| Роль | Минимальные provider permissions |
| --- | --- |
| Planner | Contents read, Issues read, Pull Requests read, Metadata read |
| Project Manager | Contents read, Issues read/write, Pull Requests read, Metadata read |
| Builder | Contents read/write, Pull Requests read/write, Actions read/write только если действительно нужен trigger, Metadata read |
| Reviewer | Contents read, Pull Requests read/write для review/comments, Issues write при необходимости, Actions read |
| Release | Actions read, Metadata read |
| Incident | Issues read/write, Metadata read |
| Learning | Issues read/write, Pull Requests read, Contents read, Metadata read |

Установите role credentials:

```dotenv
PLANNER_GITHUB_MCP_TOKEN=...
PROJECT_MANAGER_GITHUB_MCP_TOKEN=...
BUILDER_GITHUB_MCP_TOKEN=...
REVIEWER_GITHUB_MCP_TOKEN=...
RELEASE_GITHUB_MCP_TOKEN=...
INCIDENT_GITHUB_MCP_TOKEN=...
LEARNING_GITHUB_MCP_TOKEN=...
```

Не выдавайте Hermes organization-admin, repository-admin, branch-protection mutation, merge, Kubernetes, cloud-admin или runner-shell authority, пока отдельная enforced-интеграция явно этого не требует.

## 8. Оставить автоматизацию выключенной

Сохраняйте безопасные defaults:

```dotenv
ORCHESTRATOR_ENABLED=false
ORCHESTRATOR_APPLY_TRANSITIONS=false
ORCHESTRATOR_TRANSITION_COMMENT_ONLY=true
```

Если позже планируется проверка orchestrator, подготовьте отдельные read-only discovery credentials:

```dotenv
ORCHESTRATOR_PLANNER_GITHUB_TOKEN=...
ORCHESTRATOR_PROJECT_MANAGER_GITHUB_TOKEN=...
ORCHESTRATOR_BUILDER_GITHUB_TOKEN=...
ORCHESTRATOR_REVIEWER_GITHUB_TOKEN=...
ORCHESTRATOR_RELEASE_GITHUB_TOKEN=...
ORCHESTRATOR_INCIDENT_GITHUB_TOKEN=...
ORCHESTRATOR_LEARNING_GITHUB_TOKEN=...
```

Они отделены от role MCP credentials.

## 9. Проверить optional MCP integrations

Role profiles содержат дополнительные MCP integrations: например DuckDuckGo Search, PostgreSQL, MongoDB, Context7 и browser-oriented MCP servers.

Настраивайте только реально нужные интеграции. Если интеграция не используется, лучше отключить её в соответствующем role profile, чем оставлять фиктивные credentials и считать поверхность безвредной. Активный tool surface должен быть минимальным.

## 10. Выполнить static validation до запуска containers

Запустите structural validation:

```bash
scripts/validate.sh
```

Validator проверяет structure ролей/profiles, YAML, repository settings, exact GitHub MCP allowlists, drift между policy и profiles, security defaults и ряд role-specific invariants.

Проверьте rendering base Compose:

```bash
docker compose config --quiet
```

И debug Compose:

```bash
docker compose \
  -f compose.yaml \
  -f compose.debug.yaml \
  config --quiet
```

Не продолжайте, пока обе команды не проходят успешно.

## 11. Сначала запустить low-risk роли

Для первого runtime canary поднимите lower-risk роли и центральный dashboard:

```bash
docker compose up -d --build \
  hermes-planner \
  hermes-reviewer \
  hermes-learning \
  hermeteam-dashboard
```

Проверка:

```bash
docker compose ps
```

При необходимости посмотрите startup logs:

```bash
docker compose logs --tail=100 hermes-planner
docker compose logs --tail=100 hermes-reviewer
docker compose logs --tail=100 hermes-learning
```

Все запущенные role containers должны перейти в `healthy` до следующего шага.

## 12. Проверить центральный HermeTeam dashboard

Secure default Compose публикует только центральный dashboard и только на loopback:

```text
http://127.0.0.1:9130
```

Проверка:

```bash
curl -fsS http://127.0.0.1:9130/health
curl -fsS http://127.0.0.1:9130/api/overview
```

Не меняйте bind dashboard на `0.0.0.0`. Для доверенного remote-доступа используйте SSH tunnel или trusted VPN, как описано в [DASHBOARD_RU.md](DASHBOARD_RU.md).

## 13. Запустить все семь ролей

После успешного canary первых ролей:

```bash
docker compose up -d --build
```

Проверить:

```bash
docker compose ps
```

Compose допускает заметный resource limit на один agent container. На developer laptop лучше поднимать роли постепенно, если возникает CPU или memory pressure.

## 14. Включить debug overlay для локального smoke-test

Base Compose намеренно не публикует role API ports. `scripts/smoke-test.sh` проверяет именно loopback-порты ролей, поэтому для этого шага нужен debug overlay:

```bash
docker compose \
  -f compose.yaml \
  -f compose.debug.yaml \
  up -d --build

scripts/smoke-test.sh
```

Debug overlay публикует role APIs только на loopback:

| Роль | API port |
| --- | ---: |
| Planner | 18642 |
| Builder | 18643 |
| Reviewer | 18644 |
| Release | 18645 |
| Incident | 18646 |
| Learning | 18647 |
| Project Manager | 18648 |

Также native Hermes dashboards ролей становятся доступны только на loopback ports `9119`–`9125`.

После диагностики debug overlay лучше убрать.

## 15. Провести negative security canaries до positive mutations

До включения unattended automation убедитесь, что запрещённые действия завершаются без изменения provider state.

Минимальный набор negative canaries:

- Planner: попросить изменить source code;
- Builder: попросить записать в `main` или `master`;
- Builder: попросить изменить protected path, например `.github/workflows/`;
- Builder: попросить merge pull request;
- Reviewer: попросить `push_files` или другую repository mutation;
- Release: попросить `kubectl`, deploy или production mutation;
- Incident: попросить infrastructure mutation;
- Learning: попросить самостоятельно активировать/опубликовать skill.

Фраза модели «я не могу это сделать» не является доказательством. Проверяйте фактическое состояние GitHub/provider и, где доступно, MCP/provider audit evidence.

Только после прохождения negative canaries запускайте bounded positive canaries, например создание Builder-ом `agent/*` branch и pull request.

## 16. Опционально: включить Flight Recorder и Langfuse

Добавьте Langfuse settings в root `.env`:

```dotenv
HERMES_LANGFUSE_PUBLIC_KEY=pk-lf-...
HERMES_LANGFUSE_SECRET_KEY=sk-lf-...
HERMES_LANGFUSE_BASE_URL=https://cloud.langfuse.com
HERMES_LANGFUSE_ENV=development
HERMES_LANGFUSE_SAMPLE_RATE=1.0
HERMES_LANGFUSE_CAPTURE=sanitized

HERMETEAM_GATE_MODE=shadow
HERMETEAM_GATE_BLOCK_LEVEL=critical

LANGFUSE_MONITOR_WINDOW_MINUTES=60
LANGFUSE_MONITOR_TIMEOUT_MS=3000
```

Запуск observability overlay:

```bash
docker compose \
  -f compose.yaml \
  -f compose.observability.yaml \
  up -d --build
```

Во время накопления реальных traces оставляйте `HERMETEAM_GATE_MODE=shadow`. Builder пишет structured intent/action events и при наличии конфигурации экспортирует LLM traces в Langfuse; HermeTeam dashboard может server-side получать агрегированные Langfuse metrics.

## 17. Опционально: включить Capability Gateway canary

Добавьте в root `.env` значения из `capability_gateway/.env.example`:

```dotenv
CAPABILITY_ADMIN_KEY=<long-random-secret>
DASHBOARD_GOVERNANCE_KEY=<different-long-random-secret>
CAPABILITY_MAX_AUTO_RISK=MEDIUM

CAPABILITY_JUDGE_BASE_URL=<openai-compatible-base-url>
CAPABILITY_JUDGE_API_KEY=<judge-key>
CAPABILITY_JUDGE_MODEL=<judge-model>
```

Сгенерируйте два разных governance secrets, например:

```bash
openssl rand -hex 32
openssl rand -hex 32
```

До запуска проверьте rendering overlay:

```bash
docker compose \
  -f compose.yaml \
  -f compose.capability-gateway.yaml \
  config --quiet
```

Запуск:

```bash
docker compose \
  -f compose.yaml \
  -f compose.capability-gateway.yaml \
  up -d --build
```

Для combined observability + capability-governance canary:

```bash
docker compose \
  -f compose.yaml \
  -f compose.observability.yaml \
  -f compose.capability-gateway.yaml \
  up -d --build
```

Capability service остаётся только в private network `hermes-control` и не публикуется на host port.

Проверить health изнутри service container:

```bash
docker compose exec capability-gateway \
  python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8787/health').read().decode())"
```

После этого governance UI центрального dashboard может показывать pending risky-tool requests и действия `Allow once`, tool exception, capability risk override и emergency stop.

### Текущее ограничение enforcement

Capability Gateway пока является canary resolver/governance service, а не mandatory MCP execution boundary. Hermes role profiles всё ещё напрямую используют `GIT_PROVIDER_MCP_URL` и role-specific `GIT_PROVIDER_MCP_TOKEN`. Поэтому governance decision или emergency stop в этом canary нельзя считать гарантированным блокированием любой реальной provider mutation.

## 18. Включать orchestrator только после canaries

Оставляйте:

```dotenv
ORCHESTRATOR_ENABLED=false
```

пока не выполнены все условия:

- role health стабилен;
- фактический MCP `tools/list` проверен для каждого role credential;
- negative role canaries проходят;
- bounded positive canaries проходят;
- фактический provider state соответствует ожидаемому результату;
- observability достаточна для расследования failed run.

После этого выполняйте staged rollout по [OPERATIONS.md](OPERATIONS.md): начните с одной low-risk роли, вручную выполните orchestrator run, проверьте SQLite deduplication и только затем включайте periodic scheduling role-by-role.

## 19. Shutdown и recovery

Остановить stack без удаления role state:

```bash
docker compose down
```

Не используйте `--volumes`, если вы не хотите намеренно удалить role-local state.

Перезапуск одной роли или dashboard:

```bash
docker compose restart hermes-builder
docker compose restart hermeteam-dashboard
```

При security incident остановите затронутую роль и отзовите её provider/API credentials. Одной остановки container недостаточно, если credential мог утечь. Подробнее: [OPERATIONS.md](OPERATIONS.md).

## 20. Checklist локального развёртывания

### Host

- [ ] Docker Engine работает.
- [ ] Docker Compose v2 работает.
- [ ] Python 3 и PyYAML установлены.
- [ ] `git`, `curl`, `openssl`, `bash` доступны.
- [ ] Нужный outbound network access работает.

### Configuration

- [ ] `scripts/bootstrap.sh` выполнен.
- [ ] `.env` приватный и не содержит обязательных unresolved `CHANGE_ME`.
- [ ] `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD` задан.
- [ ] LLM endpoint, model и key корректны.
- [ ] Параметры целевого GitHub repository корректны.
- [ ] `REPOSITORY_CLONE_ALLOWED=false`.
- [ ] Настроены семь отдельных role GitHub MCP credentials.
- [ ] Orchestrator credentials отделены от MCP credentials.
- [ ] На initial validation `ORCHESTRATOR_ENABLED=false`.

### Static validation

- [ ] `scripts/validate.sh` проходит.
- [ ] `docker compose config --quiet` проходит.
- [ ] Debug overlay rendering проходит.
- [ ] Каждый optional overlay проходит rendering до включения.

### Runtime

- [ ] Сначала healthy становятся low-risk роли.
- [ ] Затем healthy становятся все семь ролей.
- [ ] Central dashboard доступен только на loopback.
- [ ] `/health` и `/api/overview` отвечают.
- [ ] Smoke-test с debug overlay проходит.

### Security canaries

- [ ] Planner mutation запрещена/no-op.
- [ ] Builder write в protected branch запрещён.
- [ ] Builder write в protected path запрещён.
- [ ] Builder merge недоступен/запрещён.
- [ ] Reviewer mutation недоступна/запрещена.
- [ ] Release production mutation недоступна/запрещена.
- [ ] Learning autonomous activation недоступна/запрещена.
- [ ] После каждого negative canary проверен фактический provider state.

### Observability

- [ ] Langfuse credentials настроены, если observability включена.
- [ ] Builder traces появляются в Langfuse.
- [ ] HermeTeam dashboard получает Langfuse monitor data.
- [ ] Intent/action gate остаётся в `shadow` до калибровки.

### Capability Gateway

- [ ] `CAPABILITY_ADMIN_KEY` и `DASHBOARD_GOVERNANCE_KEY` различаются.
- [ ] Judge endpoint настроен.
- [ ] Capability Gateway healthy.
- [ ] Governance UI доступен через central dashboard.
- [ ] Оператор понимает, что текущий gateway пока не mandatory execution boundary.

### Automation

- [ ] Automation выключена, пока role canaries не завершены.
- [ ] Первый orchestrator rollout выполняется только для одной роли.
- [ ] Deduplication и retry behaviour проверены до расширения rollout.

Успешный первый локальный deployment выглядит так:

```text
7 healthy Hermes roles
        +
local HermeTeam dashboard
        +
verified negative role canaries
        +
optional Builder Flight Recorder / Langfuse
        +
optional Capability Gateway governance canary
        +
ORCHESTRATOR_ENABLED=false
```

Только после стабилизации этой базы стоит включать unattended role-local automation.
