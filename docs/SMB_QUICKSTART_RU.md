# HermeTeam SMB — отдельный Safe Builder runtime (этап 1)

**Для кого:** CTO/технический основатель команды из 3–30 разработчиков, которой нужен один защищённый GitHub coding-agent workflow, а не развёртывание всей AI SDLC-команды.

Этот режим реализован в `compose.smb.yaml` **отдельно** от `compose.yaml`. Нельзя объединять их через `-f`: полный Compose требует credentials всех семи ролей и намеренно остаётся отдельным режимом.

## Что установлено

Шесть инфраструктурных/runtime сервисов:

- `hermes-builder` — единственная Hermes-роль. Отдельный облегчённый Dockerfile/profile без OpenHands, Langfuse SDK, LSP и сторонних MCP. Orchestrator выключен, direct GitHub MCP credentials отсутствуют.
- `capability-gateway` — mandatory Dynamic Authority, exact request, branch/path checks, approvals, серверная GitHub App token minting.
- `subscription-relay` — узкий OpenAI-compatible bridge к модели, **уже назначенной подпиской HermeTeam**. Builder и judge получают только внутренний relay key, не исходный provider/subscription token. Model alias фиксирован: `hermeteam-subscribed`.
- `hermeteam-dashboard` — один установленный Builder + governance, loopback `127.0.0.1:9130`.
- `docker-socket-proxy` — только ограниченные read-only Docker endpoints для Dashboard.
- `skills-superset-sync` — только пять закреплённых read-only skills (architecture, DevOps, test, security, RLM/ROEC); не расширяет полномочия агента.

Нет семи role MCP PAT, отдельных cron credentials для каждого агента, Kubernetes или обязательного Langfuse. GitHub App private key монтируется **только** в Gateway; ключ подписки — **только** в relay.

## Подписка: провайдера выбирает HermeTeam, а не пользователь

До команды bootstrap операторский/подписной процесс HermeTeam обязан предоставить три файла с правами `0600`:

```text
secrets/smb-subscription.env    # SMB_SUBSCRIPTION_BASE_URL, SMB_SUBSCRIPTION_MODEL
secrets/smb-subscription.token  # scoped subscription token, НЕ API-ключ базового провайдера
secrets/smb-github-app.pem      # GitHub App private key
```

Первые два файла выдаёт **HermeTeam subscription provisioning**; CTO не выбирает Qwen/OpenAI, модель, регион, тариф или upstream Base URL. В `.env.smb` ни токен подписки, ни модель upstream не копируются. Если entitlement или его provisioning недоступен, установка останавливается — переключения на персональный API-ключ/другого провайдера нет.

**Ограничение этапа 1:** внешний subscription provisioning/backend и автоматическая выдача файлов из кабинета подписчика в данном репозитории **не реализованы**. Эти файлы должны быть переданы утверждённым операторским способом до установки. Нельзя объявлять эту ветку полностью self-service или гарантировать 30-минутный onboarding до реализации этапа 2.

## Первый запуск

Требования: Docker Engine + Compose v2, Python 3.12+, GitHub App, установленная **только** на выбранный тестовый репозиторий, заранее назначенная подписка и digest-pinned образ Hermes. GitHub App должна иметь минимум Contents/PR permissions, достаточных для разрешённых операций Builder. Никогда не выдавайте администрации организации или merge/branch protection mutation.

Проверьте, что три pre-provisioned файла существуют и доступны только владельцу (`chmod 600`). Укажите только сведения о GitHub и закреплённый образ; здесь нет ни одного пользовательского параметра выбора LLM:

```bash
export SMB_GITHUB_REPOSITORY_FULL_NAME="my-org/my-sandbox-repo"
export SMB_GITHUB_APP_ID="123456"
export SMB_GITHUB_APP_INSTALLATION_ID="987654"
export SMB_HERMES_BASE_IMAGE="registry.example/hermes@sha256:<64-hex-digest>"
python3 scripts/smb/bootstrap.py
python3 scripts/smb/doctor.py
bash scripts/smb/up.sh
```

Команда создаёт отдельный `.env.smb` с пятью независимыми внутренними ключами, не меняя существующий `.env`. Повторный bootstrap сохраняет конфигурацию и не сбрасывает ключи. Не коммитьте `.env.smb` и файлы в `secrets/`.

После smoke-проверки откройте `http://127.0.0.1:9130`. Центральный dashboard и role APIs не открываются публично. Показаны только реально развёрнутые роли; остальные шесть в SMB режиме не считаются неисправными.

## Безопасный режим и критерии пилота

Orchestrator остаётся выключенным. До включения любых автоматических заданий в реальном репозитории проверьте через отдельный sandbox фактическое состояние GitHub для: запрета изменения protected paths и default branch, exact approval, single-use replay и emergency stop. Ответ модели «не могу» недостаточен. Существующий Dynamic Authority — Builder canary; это ещё не общий production security boundary для всех возможных инструментов и ролей.

`bash scripts/smb/smoke.sh` проверяет readiness четырёх компонентов и делает минимальный реальный запрос к назначенной по подписке модели через relay. Это **не заменяет** negative provider-state canaries.

Остановка без удаления persistent state:

```bash
bash scripts/smb/down.sh
```

Не используйте `down --volumes` при обычном rollback. Для recovery сначала исправьте причину, затем повторите `bash scripts/smb/up.sh`. Никогда не ослабляйте Gate и не подставляйте broad PAT для обхода ошибки установки.

## Скоуп следующего этапа

Подключить subscription provisioning/account entitlement, GitHub App manifest/installation UX, prebuilt digest-pinned release images, веб-мастер, zero-touch doctor/recovery и измерить время до первого подтверждённого sandbox PR. Текущий этап — **минимальный защищённый runtime и offline CI-контракты**, а не готовый self-service installer.
