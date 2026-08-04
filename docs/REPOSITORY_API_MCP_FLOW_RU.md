# Флоу доступа к репозиториям через API/MCP

> Аудитория: platform engineers, сопровождающие SDLC gateway, DevOps/SRE-инженеры и операторы агентов, которые настраивают Hermes SDLC роли и интеграции с репозиториями.

### Назначение

Этот документ описывает флоу доступа к репозиториям в `hermes-sdlc-agents` после миграции от локальных writable checkout к provider-neutral доступу через SDLC MCP gateway.

Главное правило:

```text
Hermes agents не получают GitHub/GitLab/Forgejo credentials и не монтируют writable checkout репозитория.
Все чтения и изменения репозитория выполняются через типизированные SDLC MCP repository tools.
```

### Высокоуровневая архитектура

```text
Hermes role container
  -> SDLC MCP gateway
    -> repository adapter
      -> GitHub API / GitLab API / Forgejo API / wrapped provider MCP
    -> optional ephemeral workspace worker
    -> CI adapter
    -> policy engine
    -> append-only audit log
```

SDLC MCP gateway является границей безопасности. GitHub, GitLab, Forgejo или provider MCP servers являются upstream implementation details и не должны напрямую публиковаться Hermes agents.

### Что изменилось относительно старого флоу

Старый флоу:

```text
Host REPO_DIR
  -> mount в hermes-builder как /workspace/repo:rw
  -> builder локально редактирует файлы
  -> builder использует terminal/local checks
  -> branch/PR операции идут через MCP
```

Новый флоу:

```text
Hermes builder
  -> читает файлы репозитория через SDLC MCP
  -> создаёт bounded patch/change-set
  -> просит SDLC MCP создать/обновить task branch
  -> просит SDLC MCP применить и закоммитить patch
  -> запускает CI или workspace checks через SDLC MCP
  -> создаёт provider-neutral change request
```

В Hermes builder container больше нет `REPO_DIR`, `/workspace/repo` и Git provider token.

### Provider-neutral терминология

SDLC contract использует provider-neutral термины, чтобы один и тот же agent flow работал с GitHub, GitLab или Forgejo.

| SDLC term | GitHub | GitLab | Forgejo/Gitea |
|---|---|---|---|
| `change_request` | Pull Request | Merge Request | Pull Request |
| review comment | PR review comment | Diff note/discussion | PR review comment |
| approval | PR approval | MR approval | PR approval |
| CI evidence | Checks / Actions | Pipelines / Jobs | Actions / external CI |

Provider-specific IDs и URLs должны оставаться внутри SDLC MCP gateway. Agents должны использовать стабильные `repository_id`, а не raw provider URLs.

Пример записи repository registry:

```json
{
  "repository_id": "service-a",
  "provider": "github",
  "owner": "example-org",
  "name": "service-a",
  "default_branch": "main"
}
```

### Ответственность ролей

#### Planner

Planner имеет только read-only доступ к содержимому репозитория.

Разрешено:

- искать код;
- читать tree репозитория;
- читать файлы на scoped refs;
- создавать или обновлять `spec` и `plan` artifacts.

Запрещено:

- создавать branches;
- применять patches;
- создавать change requests;
- менять код.

#### Builder

Builder реализует утверждённую работу через SDLC MCP repository tools.

Разрешено:

- читать назначенные `work_item`, `spec` и `plan`;
- читать repository files и trees через MCP;
- создать task branch `agent/<work-item-id>-<slug>`;
- передать bounded text patch/change-set;
- закоммитить изменения через repository adapter;
- запустить CI или workspace checks;
- создать или обновить change request.

Запрещено:

- использовать local checkout;
- получать GitHub/GitLab/Forgejo credentials;
- делать direct Git push;
- писать в protected branches;
- merge-ить change requests;
- менять CI workflows, quality gates, branch protection или production configuration.

Builder может вернуть `PR_READY_FOR_REVIEW` только после того, как SDLC MCP gateway принял change-set и появилась обязательная CI/workspace evidence.

#### Reviewer

Reviewer оценивает fixed revision конкретного change request.

Разрешено:

- читать change request metadata;
- читать diff и файлы на конкретных revisions;
- читать CI, coverage, mutation score и quality findings;
- оставлять review comments;
- approve или request changes.

Запрещено:

- менять author branch;
- создавать commits;
- merge-ить;
- менять quality gates или branch protection.

Gateway обязан проверять reviewer independence по provenance, а не по тексту ответа модели.

#### Release

Release role не использует repository write access. Она работает с immutable release candidates, созданными trusted CI.

Разрешено:

- читать candidate, policy, CI, quality, SLO и rollout evidence;
- вызывать `deployment_promote` или `deployment_abort` только для существующего candidate.

#### Incident и Learning

Incident и Learning roles не получают repository write access. Incident может читать service/catalog/release context. Learning может создавать proposals, но не может напрямую публиковать docs, активировать skills или менять repositories.

### Repository tools

Типичная provider-neutral tool surface:

Read tools:

- `repo_get_default_branch`
- `repo_list_tree`
- `repo_read_file`
- `repo_search_code`
- `repo_get_file_at_revision`
- `repo_compare_refs`

Builder mutation tools:

- `repo_create_task_branch`
- `repo_apply_patch`
- `repo_commit_changes`
- `repo_create_change_request`
- `repo_update_change_request_description`
- `ci_trigger_pipeline`

Reviewer tools:

- `repo_get_change_request`
- `repo_get_diff`
- `repo_add_review_comment`
- `repo_submit_review`
- `repo_request_changes`
- `repo_approve_change_request`

Не публикуйте Hermes широкие tools вроде `github_request`, `gitlab_request`, raw GraphQL, generic HTTP, repository admin, merge, branch protection mutation или workflow editing tools.

### Обязательный mutation envelope

Каждый mutating repository call должен содержать достаточно данных для authorization, concurrency control, idempotency и audit.

Пример:

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

Gateway должен отклонить вызов, если:

- роль не имеет права вызывать tool;
- repository не входит в scope work item;
- branch не начинается с `agent/<work-item-id>-`;
- base или head revision устарели;
- diff затрагивает protected paths;
- операция требует merge, admin или protected branch privileges;
- тот же idempotency key повторно используется с другими аргументами.

### Правила patch/change-set

`repo_apply_patch` по умолчанию должен принимать только bounded text changes:

- создание text file;
- изменение text file через unified diff;
- удаление явно scoped file;
- rename file, если и source, и target paths разрешены.

Отклоняйте или требуйте human/platform approval для:

- binary files;
- LFS или submodule changes;
- generated lockfile changes, если они не созданы trusted workspace worker;
- protected paths;
- файлов больше заданного size limit;
- изменений вне assigned repository/work item scope.

### Validation и tests

Так как builder больше не запускает local shell commands в checkout, validation должна идти одним из двух путей.

Предпочтительный путь:

```text
SDLC MCP gateway
  -> ephemeral workspace worker
    -> clone repository в isolated workspace
    -> apply patch
    -> run allowlisted checks
    -> commit/push task branch
    -> return logs, artifacts, and exit codes
```

Минимальный путь:

```text
repo_commit_changes
  -> ci_trigger_pipeline
  -> ci_get_status
  -> ci_get_test_results
```

Если обязательная CI/workspace evidence отсутствует, pending или failed, builder должен вернуть `BLOCKED`, а не `PR_READY_FOR_REVIEW`.

### Security requirements

- Hermes agents не должны получать GitHub/GitLab/Forgejo tokens.
- Provider tokens находятся только в SDLC MCP repository adapter или workspace worker.
- Provider tokens не должны иметь admin, branch protection, protected branch write или merge scopes.
- Repository content должен считаться untrusted input, потому что он может содержать prompt injection.
- Provider MCP resources, prompts, sampling и elicitation не должны публиковаться Hermes.
- Protected path checks должны выполняться server-side и повторно в trusted CI вне author branch.
- Каждая mutation должна создавать audit record с role, subject, tool, canonical argument hash, upstream request ID, before/after revision, idempotency key и policy decision.

### Operational canaries

Positive canaries:

1. Planner читает файл через `repo_read_file` и создаёт plan.
2. Builder создаёт `agent/<work-item-id>-<slug>`, применяет маленький patch, запускает checks и открывает change request.
3. Reviewer читает fixed diff и оставляет review comment.
4. Release читает candidate evidence и выполняет promote или abort без repository access.

Negative canaries:

1. Builder пытается писать напрямую в `main` и получает server-side deny.
2. Builder пытается изменить protected path и получает server-side deny.
3. Builder пытается вызвать raw GitHub/GitLab provider tool и получает deny или tool not found.
4. Reviewer пытается изменить author branch и получает deny.
5. Planner пытается создать branch и получает deny.
6. Любая роль пытается выполнить merge и получает deny.
