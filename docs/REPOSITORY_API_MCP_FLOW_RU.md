# Флоу доступа к репозиториям через API/MCP

> Аудитория: platform engineers, DevOps/SRE-инженеры и операторы агентов, которые настраивают Hermes SDLC роли и прямые GitHub/GitLab API/MCP интеграции с репозиториями.

### Назначение

Этот документ описывает флоу доступа к репозиториям в `hermes-sdlc-agents` после миграции от локальных writable checkout к прямому GitHub/GitLab API/MCP доступу в MVP.

Главное правило:

```text
Hermes agents не монтируют writable checkout репозитория.
Все чтения и изменения репозитория выполняются через role-scoped GitHub/GitLab API/MCP tools с exact allowlist.
```

### Высокоуровневая архитектура

```text
Hermes role container
  -> GitHub/GitLab provider API/MCP endpoint
    -> GitHub API / GitLab API
    -> provider-side policy/permission checks
    -> optional ephemeral workspace worker or trusted CI
    -> provider/upstream audit log
```

В MVP нет отдельного repository gateway. Граница безопасности переносится в комбинацию role-scoped provider tokens, exact `tools.include`, provider MCP policy, GitHub/GitLab permissions, branch protection и trusted CI.

Для official GitHub MCP endpoint каждый role profile отправляет `X-MCP-Toolsets: "repos,issues,pull_requests,actions,git,code_security,dependabot"`. Это включает только server-side discovery; Hermes всё равно показывает tools через exact `tools.include` allowlist конкретной роли.

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
  -> читает файлы репозитория через GitHub/GitLab API/MCP
  -> создаёт bounded patch/change-set
  -> создаёт/обновляет task branch через GitHub/GitLab API/MCP
  -> применяет и коммитит patch через GitHub/GitLab API/MCP
  -> запускает CI или workspace checks через provider API/MCP
  -> создаёт change request
```

В Hermes builder container больше нет `REPO_DIR` и `/workspace/repo`; вместо broad provider credential используется `BUILDER_GITHUB_MCP_TOKEN` из основного `.env`, который Compose маппит во внутренний `GIT_PROVIDER_MCP_TOKEN` контейнера.

### Provider-neutral терминология

Workflow использует ограниченный набор общих терминов, чтобы один и тот же agent flow работал с GitHub или GitLab.

| Workflow term | GitHub | GitLab |
|---|---|---|
| `change_request` | Pull Request | Merge Request |
| review comment | PR review comment | Diff note/discussion |
| approval | PR approval | MR approval |
| CI evidence | Checks / Actions | Pipelines / Jobs |

Agents должны использовать стабильные `repository_id`, а не raw provider URLs, даже при прямом provider API/MCP доступе.

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

Builder реализует утверждённую работу через role-allowed GitHub/GitLab API/MCP repository tools.

Разрешено:

- читать назначенные `work_item`, `spec` и `plan`;
- читать repository files и trees через provider API/MCP;
- создать task branch `agent/<work-item-id>-<slug>`;
- передать bounded text patch/change-set;
- закоммитить изменения через repository adapter;
- запустить CI или workspace checks;
- создать или обновить change request.

Запрещено:

- использовать local checkout;
- получать broad GitHub/GitLab credentials вне role-scoped token;
- делать direct Git push;
- писать в protected branches;
- merge-ить change requests;
- менять CI workflows, quality gates, branch protection или production configuration.

Builder может вернуть `PR_READY_FOR_REVIEW` только после того, как provider API/MCP принял change-set и появилась обязательная CI/workspace evidence.
В orchestrated mode это решение должно возвращаться строгим final JSON, а не свободным текстом; orchestrator проверяет `assignment_key`, `role` и допустимый для роли `final_status` перед применением handoff labels/comments.

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

Provider policy или внешний orchestrator обязан проверять reviewer independence по provenance, а не по тексту ответа модели.

#### Release

Release role не использует repository write access. Она работает с immutable release candidates, созданными trusted CI.

Разрешено для GitHub MVP:

- читать GitHub Actions evidence;
- возвращать `BLOCKED_NO_ACTION` для deployment changes, пока native release/deployment tools не обнаружены и не ограничены.

#### Incident и Learning

Incident и Learning roles не получают repository write access. В GitHub MVP incident может читать/comment GitHub issues. Learning может создавать/comment GitHub issues для human-reviewed proposals, но не может напрямую публиковать docs, активировать skills или менять repositories.

### Repository tools

Official GitHub MCP MVP tool surface. Exact names нужно подтвердить runtime `tools/list` для настроенного endpoint и token scopes.

Issue mutations используют `issue_write` для создания и обновления issues.

Planner/read tools:

- `get_file_contents`
- `get_repository_tree`
- `search_code`
- `issue_read`
- `list_issues`

Builder mutation tools:

- `create_branch`
- `push_files`
- `create_pull_request`
- `actions_run_trigger`
- `actions_get`
- `actions_list`
- `get_job_logs`

Reviewer tools:

- `pull_request_read`
- `get_file_contents`
- `actions_get`
- `actions_list`
- `get_job_logs`
- `add_issue_comment`

Не публикуйте Hermes широкие tools вроде `github_request`, raw GraphQL, generic HTTP, repository admin, merge, branch protection mutation или workflow editing tools. GitLab out of scope для этого GitHub MVP.

### Обязательный mutation envelope

Каждый mutating repository call должен содержать достаточно данных для authorization, concurrency control, idempotency и audit.

Пример:

```json
{
  "owner": "test-project",
  "repo": "test-project",
  "branch": "agent/REQ-123-short-slug",
  "message": "Implement REQ-123",
  "files": [
    {"path": "src/example.py", "content": "..."}
  ]
}
```

Provider MCP/API policy должен отклонить вызов, если:

- роль не имеет права вызывать tool;
- `owner`/`repo` не совпадают с настроенным target repository;
- branch не начинается с `agent/`;
- branch равен `main`, `master` или `release/*`;
- `files[].path` затрагивает protected paths;
- операция требует merge, admin или protected branch privileges;
- тот же idempotency key повторно используется с другими аргументами.

### Правила file changes

`push_files` по умолчанию должен принимать только bounded text changes:

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
Official GitHub MCP
  -> ephemeral workspace worker or trusted CI
    -> clone repository в isolated workspace
    -> apply bounded file changes
    -> run allowlisted checks
    -> commit/push task branch
    -> return logs, artifacts, and exit codes
```

Минимальный путь:

```text
push_files
  -> actions_run_trigger
  -> actions_list
  -> actions_get
  -> get_job_logs
```

Если обязательная CI/workspace evidence отсутствует, pending или failed, builder должен вернуть `BLOCKED`, а не `PR_READY_FOR_REVIEW`.

### Security requirements

- Hermes agents не должны получать broad GitHub tokens.
- Каждый role-scoped `*_GITHUB_MCP_TOKEN` в основном `.env` должен иметь минимальные repository scopes для конкретной роли.
- Provider tokens не должны иметь admin, branch protection, protected branch write или merge scopes.
- Repository content должен считаться untrusted input, потому что он может содержать prompt injection.
- Provider MCP resources, prompts, sampling и elicitation не должны публиковаться Hermes.
- Protected path checks должны выполняться server-side и повторно в trusted CI вне author branch.
- Каждая mutation должна создавать audit record с role, subject, tool, canonical argument hash, upstream request ID, before/after revision, idempotency key и policy decision.

### Operational canaries

Positive canaries:

1. Planner читает файл через `get_file_contents` и получает repository tree data.
2. Builder создаёт `agent/<work-item-id>-<slug>`, отправляет маленькое разрешённое file change через `push_files`, запускает/проверяет Actions и открывает Pull Request.
3. Reviewer читает Pull Request evidence и оставляет comment.
4. Release читает Actions evidence и возвращает `BLOCKED_NO_ACTION` для deployment mutation в GitHub MVP.

Negative canaries:

1. Builder пытается писать напрямую в `main` и получает server-side deny.
2. Builder пытается изменить protected path и получает server-side deny.
3. Builder пытается вызвать broad raw GitHub provider tool и получает deny или tool not found.
4. Reviewer пытается изменить author branch и получает deny.
5. Planner пытается создать branch и получает deny.
6. Любая роль пытается выполнить merge и получает deny.
