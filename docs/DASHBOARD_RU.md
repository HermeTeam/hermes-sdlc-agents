# Эксплуатация HermeTeam dashboard

Руководство предназначено для локальных операторов и разработчиков упрощённого dashboard. English version: [DASHBOARD.md](DASHBOARD.md).

## Назначение и границы MVP

Dashboard показывает текущее состояние семи Hermes role containers и их локальных очередей orchestrator: состояние Docker, активные/ожидающие/заблокированные назначения и ссылки на work items провайдера.

MVP работает только локально на одном хосте, доступен только для чтения, не хранит собственное состояние, не имеет аутентификации и опрашивает Docker Compose и существующие role-local SQLite очереди каждые пять секунд. В нём нет dashboard database, истории, audit trail, пользователей/RBAC, управляющих действий, transcript/log viewer, proxy к native Hermes dashboard, SSE/WebSocket и Kubernetes/multi-host deployment.

## Требования и запуск

Нужны Docker Engine, Docker Compose v2 и доступ хоста к `/var/run/docker.sock`; обычные параметры HermeTeam в `.env`; Node.js 22.6+ и npm для локальных dashboard checks; Python 3.11+ и PyYAML для repository validation. Команды выполняются из корня репозитория.

```bash
scripts/bootstrap.sh
scripts/validate.sh
docker compose up --build -d
```

Откройте <http://127.0.0.1:9130>. Default Compose публикует только central dashboard и только на loopback. Docker proxy и status endpoints ролей остаются в private network `hermes-control`.

Другой локальный порт задаётся без изменения bind address:

```bash
HERMETEAM_DASHBOARD_PORT=9131 docker compose up --build -d
```

Проверка:

```bash
curl --fail http://127.0.0.1:9130/health
curl --fail http://127.0.0.1:9130/api/overview
docker compose ps
```

`/health` проверяет только процесс dashboard. Состояние зависимостей смотрите в `/api/overview` или UI.

## Локальная диагностика

Hermes API и native dashboard ролей в secure default не опубликованы. Включайте их только явным loopback-only override:

```bash
docker compose -f compose.yaml -f compose.debug.yaml up --build -d
```

Override публикует role APIs на `127.0.0.1:18642`–`18648` и native dashboards на `127.0.0.1:9119`–`9125`. Точное соответствие ролей и port overrides находится в [compose.debug.yaml](../compose.debug.yaml). Role API требует Bearer key, native dashboard — настроенную basic authentication.

Status API dashboard — отдельный private interface. Wrapper каждой роли обслуживает `GET /health` и `GET /status` на internal port `8650`. `ORCHESTRATOR_STATUS_BIND` и `ORCHESTRATOR_STATUS_PORT` настраивают listener, но ни основной Compose, ни debug override не публикуют его на хост. Central dashboard обращается к canonical service names через `hermes-control`.

Контейнеры ролей имеют labels `hermeteam.agent=true` и уникальный `hermeteam.role`. Dashboard выбирает только семь canonical labels. Restricted Docker proxy разрешает только container list/inspect reads, запрещает `POST` и другие секции Docker API, не имеет host port. Docker socket никогда не монтируется в dashboard.

## Обновление и статусы

Browser poll выполняется каждые пять секунд, останавливается в hidden tab и немедленно возобновляется после возврата. Доступен manual refresh. Во время запроса сохраняются предыдущие успешные данные. Если refresh завершился ошибкой, они помечаются как stale, а не выдаются за новый snapshot.

`partial` означает ошибку или timeout хотя бы одного Docker/status source. Успешные роли остаются видимыми.

Docker и agent state показываются отдельно:

- Docker: `RUNNING`, `STARTING`, `UNHEALTHY`, `RESTARTING`, `PAUSED`, `STOPPED`, `MISSING` или `UNKNOWN`.
- Agent `UNAVAILABLE`: container missing/stopped/unhealthy/restarting либо status API running-роли недоступен.
- `BLOCKED`: есть blocked/failed item; `WORKING`: есть active assignment; `QUEUED`: есть due assignment; `WAITING`: остался delayed retry.
- `DISABLED`: orchestrator выключен; `IDLE`: running role имеет читаемую пустую очередь; `UNKNOWN`: известное состояние вывести нельзя, включая starting/paused/unknown container.

Running container не означает работающего агента.

## Диагностика проблем

| Симптом                             | Проверка и действие                                                                                                                                     |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `MISSING`                           | Выполните `docker compose ps -a`, проверьте наличие role service и canonical label, при необходимости пересоздайте service.                             |
| `STOPPED`                           | Проверьте `docker compose logs <service>`, устраните причину и выполните `docker compose start <service>` или `docker compose up -d <service>`.         |
| `UNHEALTHY`                         | Проверьте healthcheck и logs роли; agent останется unavailable до восстановления Docker health.                                                         |
| Docker running, agent `UNAVAILABLE` | Проверьте logs роли на ошибку status server, общую network `hermes-control` и internal port `8650`.                                                     |
| `sqlite_busy`                       | Дождитесь следующего poll. Если ошибка постоянная, исключите сторонних/concurrent writers; не запускайте две replicas на одном `/opt/data`.             |
| Queue кратковременно stale          | Immutable reader не создаёт WAL sidecars и при concurrent write может увидеть слегка устаревший snapshot. Дождитесь следующего poll.                    |
| Docker state недоступен у всех      | Запустите `scripts/test-docker-socket-proxy.sh`, проверьте logs proxy и доступ host socket. Не монтируйте socket в dashboard.                           |
| Dashboard/API недоступен            | Проверьте `docker compose ps`, logs `hermeteam-dashboard` и `/health`; при stale image выполните `docker compose build --no-cache hermeteam-dashboard`. |
| Ошибка build                        | Выполните `npm --prefix dashboard ci`, затем `npm --prefix dashboard run check` и `npm --prefix dashboard run build`.                                   |
| Port занят                          | Задайте свободный `HERMETEAM_DASHBOARD_PORT`; debug ports имеют per-role overrides в `compose.debug.yaml`.                                              |
| Partial/stale page                  | Посмотрите source message и `/api/overview`, затем исправьте только отказавшую dependency.                                                              |

## Граница безопасности

> **Предупреждение:** не публикуйте no-auth MVP в LAN/Internet, через public reverse proxy или на `0.0.0.0`. Loopback — обязательная граница безопасности.

Для доступа с доверенной машины не меняйте Compose: используйте SSH tunnel или trusted VPN. Пример на клиенте:

```bash
ssh -N -L 9130:127.0.0.1:9130 operator@dashboard-host
```

После этого откройте `http://127.0.0.1:9130` на клиенте. Не публикуйте proxy/status ports и не добавляйте dashboard socket mount. API намеренно не возвращает secrets, env, prompts, issue bodies, transcripts, logs, raw DB rows и raw upstream errors.

Remote/multi-user access, auth/RBAC, history/audit, native Hermes drill-down, retained evidence, control actions, realtime быстрее polling, Kubernetes или multi-host operation требуют перехода к полной архитектуре, а не ослабления MVP.

## Restart, shutdown и recovery

```bash
docker compose restart hermeteam-dashboard
docker compose down
docker compose up --build -d
```

Dashboard stateless: migration, backup и restore ему не нужны. `docker compose down` сохраняет role volumes. Не добавляйте `--volumes`, если не собираетесь намеренно удалить role-local state.

## Проверки для разработки и release

```bash
npm --prefix dashboard ci
npm --prefix dashboard run check
npm --prefix dashboard run build
python3 -m unittest discover -s orchestrator/tests -p 'test*.py' -v
bash orchestrator/tests/test_wrapper_lifecycle.sh
scripts/validate.sh
scripts/test-docker-socket-proxy.sh
```

Production browser E2E включается отдельно, потому что собирает images и создаёт isolated temporary Compose project:

```bash
npm --prefix dashboard run test:e2e
DASHBOARD_E2E=true scripts/smoke-test.sh
```

Нужны Docker/Compose, установленные npm dependencies и local Chromium/Chrome. Cleanup trap удаляет containers, network, volumes и probe. После аварийного прерывания выполните `docker compose -p <project> down --volumes --remove-orphans`, затем проверьте `docker ps -a` и `docker network ls`.

Render validation без запуска:

```bash
docker compose config --quiet
docker compose -f compose.yaml -f compose.debug.yaml config --quiet
docker compose -f dashboard/tests/e2e/compose.e2e.yaml config --quiet
```

После `npm ci` запускайте `npm audit`, фиксируйте и оценивайте каждую advisory относительно production dependency path. Не скрывайте transitive advisories и не применяйте непроверенный breaking upgrade.

## Известные ограничения

- Polling может пропустить короткие промежуточные состояния; stopped role не отдаёт queue details.
- Immutable SQLite read может отстать на один poll от concurrent WAL write.
- Нет global queue ordering, history, metrics, audit, acknowledgements, native drill-down и multi-user access.
- Docker proxy остаётся high-trust private digest-pinned dependency.
- Base image tags dashboard version-pinned, но не зафиксированы registry digest; при upgrade требуется повторная проверка.
