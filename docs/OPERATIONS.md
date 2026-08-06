# Operations runbook

## Initial rollout

1. Разверните и проверьте LLM gateway с role quotas и model allowlist.
2. Разверните или настройте прямой GitHub/GitLab API/MCP endpoint и примените `policies/roles.yaml` плюс argument-level rules.
3. Настройте role-scoped provider tokens. Проверьте, что ни один token не имеет merge/admin/branch-protection scopes.
4. Запустите `scripts/bootstrap.sh`, заполните secrets, pin image digest.
5. Выполните `scripts/validate.sh` и OPA unit/negative tests на provider MCP/API policy layer.
6. Запустите сначала planner/reviewer/learning, затем builder, release и incident.
7. Для каждой роли выполните positive и negative canary; сопоставьте Hermes run, provider MCP audit и upstream audit.
8. Только после canary подключайте Jira/OpenProject/webhook/CI orchestrator к `/v1/runs`.

## Day-2 checks

Ежедневно:

- `/health` и authenticated `/health/detailed`;
- crash/restart count, pending runs, token usage и MCP error rate;
- denied tool-call spikes и repeated-loop hard stops;
- stale release/incident actions и unreconciled async executions.

Еженедельно:

- diff role config ↔ `policies/roles.yaml` через `scripts/validate.sh`;
- active token subjects/JTI, TTL и unused identities;
- branch protection, protected-path gate, provider token scopes и reviewer independence;
- runbook/flag allowlists и release policy version;
- pending skill proposals и просроченные human approvals.

## Secret rotation

1. Выпустите новый token с новым `jti` и тем же минимальным role scope.
2. Обновите только одну роль и перезапустите её container/Pod.
3. Выполните positive read canary и negative mutation canary.
4. Отзовите старый `jti`; проверьте, что повтор старого token получает deny.
5. Не ротируйте все роли одновременно без необходимости: это усложняет attribution.

## Upgrade Hermes

1. Прочитайте upstream release/security notes.
2. Обновите digest в отдельной ветке этого bundle.
3. Запустите `hermes config check`/`doctor` в disposable copy каждого data volume.
4. Выполните structural validation, provider MCP discovery snapshot, repository canaries и все role canaries.
5. Canary одной low-risk роли, затем последовательный rollout.
6. Не запускайте два контейнера на одном `/opt/data`: Hermes state не рассчитан на concurrent writers.

## Backup and restore

Сохраняйте отдельный encrypted backup каждого `/opt/data` с разными encryption contexts. Перед backup остановите соответствующий gateway либо используйте storage snapshot с consistency guarantee. Не объединяйте state разных ролей.

После restore:

- отзовите старые MCP/API tokens и выдайте новые;
- проверьте managed config и SOUL mounts;
- запустите health, positive read и negative mutation canaries;
- сравните restored session/memory policy. В этом bundle persistent Hermes memory отключена.

## Emergency stop

Остановите только конкретную роль:

```bash
docker compose stop hermes-release
```

Затем отзовите её provider MCP token/JTI и inbound API key. Остановка Hermes без revoke недостаточна, если token мог утечь. Для release/incident также временно запретите subject на provider MCP/API policy layer и upstream integrations.

## Incident involving an agent

Сохраните immutable copies audit/logs, run IDs, token JTI, provider request IDs и policy revision. Не помещайте raw tokens в тикет. Определите последние successful mutations, reconcile фактическое upstream state и при необходимости выполните rollback только через человеческий break-glass процесс. Learning pipeline не должен автоматически обучаться на security incident до redaction и отдельного approval.
