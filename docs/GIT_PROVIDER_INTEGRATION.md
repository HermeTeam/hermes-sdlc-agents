# Контракт прямой GitHub/GitLab API/MCP интеграции

Hermes в MVP подключается напрямую к role-scoped GitHub/GitLab API/MCP endpoint `GIT_PROVIDER_MCP_URL`. Клиентский `tools.include` остаётся дополнительным фильтром, но итоговый запрет должен выполняться на стороне provider MCP/API policy layer, GitHub/GitLab permissions, branch protection и CI rules.

## Требования к identity

Role token `GIT_PROVIDER_MCP_TOKEN` должен быть короткоживущим и минимальным по scope. JWT или эквивалентный workload token содержит:

- `iss`: доверенный workload issuer;
- `sub`: уникальный экземпляр агента, например `prod/hermes-builder-7c9d`;
- `aud`: строго `git-provider-mcp`;
- `role`: одно значение из `policies/roles.yaml`;
- `exp`, `iat`: TTL не более 3600 секунд;
- `jti`: уникальный ID для revoke/audit.

Header `X-Hermes-Role` используется только для diagnostics. Provider MCP/API layer не должен доверять ему без совпадения с подписанным claim `role`.

## Общий request envelope

Каждый mutating tool принимает как минимум:

```json
{
  "work_item_id": "REQ-123",
  "reason": "Acceptance criterion AC-4",
  "expected_version": "opaque-etag-or-revision",
  "idempotency_key": "uuid-v7",
  "correlation": {
    "hermes_run_id": "run_...",
    "session_id": "..."
  }
}
```

Для incident actions вместо или дополнительно обязателен `incident_id`; для release actions — `candidate_id`, `expected_revision`, `stage` и `policy_evaluation_id`.

Provider MCP/API layer выполняет schema validation, authorisation, optimistic-concurrency check, idempotency lookup и audit append до upstream mutation. Повтор с тем же ключом и теми же аргументами возвращает тот же result; повтор с иными аргументами получает conflict.

## Общий response envelope

```json
{
  "ok": true,
  "action_id": "act_...",
  "audit_id": "aud_...",
  "resource_version_before": "...",
  "resource_version_after": "...",
  "observed_state": {},
  "timestamp": "RFC3339",
  "warnings": []
}
```

`ok=true` означает завершённую upstream operation, а не только принятие сообщения. Для асинхронной операции response содержит `status=accepted`, execution ID и отдельный read tool для reconciliation.

## Repository provider access

Repository access в MVP идёт напрямую через GitHub/GitLab API/MCP. Если provider MCP поддерживает native provider tools, публикуйте Hermes только exact allowlist из `policies/roles.yaml`; широкие generic tools и admin tools не должны попадать в role endpoint.

Repository-scoped tools получают стабильный `repository_id`; provider URL, project ID, owner/group и базовые параметры описаны в `policies/repositories.yaml`:

```json
{
  "repository_id": "service-a",
  "provider": "github|gitlab",
  "default_branch": "main"
}
```

Provider mapping examples:

| SDLC concept | GitHub | GitLab |
|---|---|---|
| change request | Pull Request | Merge Request |
| review comment | Review comment | Diff note/discussion |
| approval | PR review approval | MR approval |
| status evidence | Checks/Actions | Pipelines/jobs |

Не публикуйте broad provider tools вроде `github_request`, `gitlab_request`, `create_or_update_file`, raw GraphQL, repository admin, merge, workflow edit или branch protection mutation. Если прямой provider MCP содержит такие tools, выключите их через provider-side policy и Hermes `tools.include`.

## Repository mutation envelope

Every repository mutation requires:

```json
{
  "work_item_id": "REQ-123",
  "repository_id": "service-a",
  "base_ref": "main",
  "expected_base_sha": "abc123",
  "task_branch": "agent/REQ-123-short-slug",
  "expected_head_sha": "def456-or-null",
  "reason": "Acceptance criterion AC-4",
  "idempotency_key": "uuid-v7",
  "correlation": {
    "hermes_run_id": "run_...",
    "session_id": "..."
  }
}
```

Provider MCP/API layer rejects mutations when repository/work item scope does not match, branch prefix is not `agent/<work-item-id>-`, expected revisions are stale, protected paths are touched, or the upstream operation would require merge/admin/protected-branch privileges.

`repo_apply_patch` accepts only bounded text changes: create text file, update text file by unified diff, delete explicitly scoped files, or rename files when both paths are allowed. Binary changes, LFS/submodule changes, protected paths and generated lockfile changes require trusted CI/workspace evidence or human/platform approval.

## Запрещённые универсальные инструменты

Не публикуйте в role endpoint инструменты вроде:

- `http_request`, `graphql`, `execute`, `shell`, `command`;
- `kubectl`, `helm`, `cloud_cli`, `ssh`;
- `sql`, `query_database` с произвольной строкой;
- `repo_admin`, `merge`, `set_branch_protection`;
- `set_flag`, `edit_flag_rules`;
- `runbook_execute` без approved ID/version/parameter schema;
- `skills_install`, `skills_activate`, `skills_publish`.

## Role-specific semantics

### planner

- Repository read tools используют read-only GitHub/GitLab identity и разрешённые repositories/refs.
- `spec_create/update` и `plan_create/update` пишут только специальные artifact types и сохраняют source requirement IDs.
- Provider policy отклоняет path, ref или repository вне назначенного work item.

### builder

- `repo_create_task_branch` генерирует/проверяет prefix `agent/<work-item-id>-` и base revision.
- `repo_apply_patch` и `repo_commit_changes` принимают только bounded text change-set для созданной task branch, expected-base и expected-head protected update.
- `repo_create_change_request` всегда target-ит protected base, но не merge-ит.
- `ci_trigger_pipeline` запускает или запрашивает trusted validation; `PR_READY_FOR_REVIEW` запрещён без `ci_get_status`/`ci_get_test_results` или workspace evidence.
- Provider token не имеет merge/admin/branch-protection scopes.
- Отдельный CI gate сравнивает diff с `policies/protected-paths.txt`; пример проверки — `scripts/check-protected-paths.sh`. В production CI запускайте скрипт и policy из trusted base revision, а не из change request checkout, иначе автор change request сможет изменить сам gate.

### reviewer

- Read tools фиксируются на change request head/base revisions, чтобы diff не менялся между анализом и review.
- Review write tools меняют только comment/review state.
- Provider policy отклоняет self-review по provenance: author subject, implementation run IDs и reviewer subject должны быть независимы.
- Token не имеет content-write и merge scopes.

### release

- Candidate создан доверенным CI и содержит immutable image digest, config digest, SBOM/provenance и policy bundle version.
- `deployment_promote` меняет только переход на следующий заранее описанный этап. Агент не задаёт arbitrary traffic weight или manifest.
- `deployment_abort` прекращает candidate и вызывает заранее настроенную rollback strategy.
- Provider/API policy повторно проверяет CI/approvals/policy и current revision; LLM decision не заменяет policy engine.
- Kubernetes/Argo credentials не выдаются Hermes Pod.

### incident

- Telemetry tools требуют bounded selectors, environment, start/end и server-side max rows/series/time range.
- `flags_disable` разрешает только transition `enabled -> disabled` для allowlisted flag/environment и expected version.
- `runbooks_execute_approved` принимает только immutable approved ID+version и параметры из JSON Schema. Runbook runner применяет собственные RBAC, concurrency и approval rules.
- Любая операция вне allowlist возвращает `ESCALATION_REQUIRED`, а не generic execute handle.

### learning

- Outcomes агрегированы и очищены от secrets/PII до выдачи агенту.
- `proposal_*` пишет только в review queue.
- Нет инструментов прямого изменения docs/skills registry.
- Native Hermes `skill_manage` включён только с `skills.write_approval: true`; изменения остаются в pending queue до human approval.

## Audit schema

Для каждого вызова записывайте:

- timestamp, issuer, subject, role, jti;
- Hermes run/session, work item/incident/candidate;
- tool name и hash canonical arguments;
- policy bundle/revision и decision;
- upstream identity/resource/action;
- before/after version, result, latency и error class;
- idempotency key и linked approval IDs.

Secrets, raw tokens, full log payloads и PII в audit не сохраняются. Audit append-only, с retention и доступом, независимыми от агента.
