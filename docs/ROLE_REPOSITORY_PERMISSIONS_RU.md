# Права на репозитории по ролям Hermes SDLC Agents

Документ описывает минимальный набор прав на репозитории для ролей `hermes-sdlc-agents` при работе напрямую через GitHub/GitLab API/MCP.

Цель: выдать каждой роли только те repository permissions, которые нужны для её задачи, без clone-доступа, admin-доступа, merge-доступа и прав на изменение branch protection.

## Базовые правила

- Используйте отдельный `GIT_PROVIDER_MCP_TOKEN` для каждой роли.
- Не переиспользуйте один token между ролями.
- Не выдавайте Hermes agents broad GitHub/GitLab admin token.
- Не выдавайте права на изменение branch protection, rulesets, CODEOWNERS, CI settings и repository settings.
- Не выдавайте права на прямой write в protected branches: `main`, `master`, `release/*`.
- Builder может писать только в task branches с prefix `agent/`.
- Reviewer не должен иметь права менять файлы или ветку автора.
- Planner и project manager не должны иметь write-доступ к коду.
- Release/incident/learning получают repository-write только если соответствующий workflow реально представлен в GitHub/GitLab Issues, PR/MR, Releases или Deployments.
- Репозиторий не клонируется в Hermes containers. Работа идёт только через provider API/MCP.

## Рекомендуемая модель токенов

Предпочтительно использовать GitHub App installation tokens или GitLab project access tokens с коротким TTL и role-specific scopes.

Допустимые варианты:

- GitHub fine-grained PAT, ограниченный одним repository.
- GitHub App installation token, ограниченный одним repository.
- GitLab project access token, ограниченный одним project.
- GitLab group access token только если scope дополнительно ограничен project allowlist на стороне MCP/API layer.

Не рекомендуется:

- classic GitHub PAT с `repo` на все репозитории пользователя;
- GitLab personal access token с широкими group/admin правами;
- общий token для всех ролей;
- token с repository admin/maintainer правами для planner/reviewer.

## GitHub permissions matrix

Таблица ниже использует названия fine-grained GitHub permissions. Для GitHub App используйте эквивалентные repository permissions.

| Роль | Минимальные GitHub permissions | Зачем |
|---|---|---|
| `hermes-planner` | Metadata: read; Contents: read; Issues: read; Pull requests: read; Actions: read | Читать требования, issue context, код, PR context и CI evidence для планирования |
| `hermes-project-manager` | Metadata: read; Contents: read; Issues: read/write; Pull requests: read; Actions: read | Управлять intake, статусами, backlog, рисками, решениями и evidence через Issues без code/branch mutation |
| `hermes-builder` | Metadata: read; Contents: read/write; Pull requests: read/write; Actions: read; Actions: write только если builder запускает workflow | Создавать `agent/*` branch, писать change-set, открывать PR, читать/запускать CI |
| `hermes-reviewer` | Metadata: read; Contents: read; Pull requests: read/write; Issues: read/write если PR comments идут через issue comments; Actions: read; Code scanning alerts: read; Dependabot alerts: read | Читать diff/evidence, оставлять review/comments, approve/request changes, анализировать security findings |
| `hermes-release` | Metadata: read; Actions: read; Deployments: read/write только если release управляется GitHub Deployments; Releases: read/write только если release создаёт GitHub Release | Читать immutable candidate/evidence и выполнять только разрешённый promote/abort через GitHub-native механизм, если он используется |
| `hermes-incident` | Metadata: read; Issues: read/write; Actions: read; Contents: read только если runbooks хранятся в repo | Читать incident issue, писать timeline/comments, читать runbook docs и CI context |
| `hermes-learning` | Metadata: read; Contents: read; Issues: read/write; Pull requests: read; Pull requests: write только если proposals оформляются как draft PR | Читать outcomes/docs/skills, создавать proposal issue или draft PR для human review |

## GitLab permissions matrix

GitLab permissions зависят от типа token. Для project access token предпочтительно выдавать минимальную роль и scopes.

| Роль | Project role | Token scopes | Зачем |
|---|---|---|---|
| `hermes-planner` | Reporter | `read_api`, `read_repository` | Читать issues, MR context, repository files и pipeline evidence |
| `hermes-project-manager` | Reporter | `api`, `read_repository` | Читать/обновлять project-management issues и читать repository evidence без repository writes |
| `hermes-builder` | Developer | `api`, `read_repository`, `write_repository` | Создавать branch, commit/change-set, MR и запускать pipeline |
| `hermes-reviewer` | Reporter или Developer | `api`, `read_repository`; Developer нужен только если approve/comment требует write permissions | Читать MR diff/evidence и оставлять review/discussions |
| `hermes-release` | Reporter или Maintainer только при GitLab Deployments/Releases write | `api`, `read_repository`; `write_repository` не нужен для обычного release approval | Читать pipeline/release evidence, управлять release/deployment только если GitLab является release control plane |
| `hermes-incident` | Reporter | `api`, optional `read_repository` | Читать/обновлять incident issues и читать runbook docs при необходимости |
| `hermes-learning` | Reporter или Developer | `api`, `read_repository`; Developer только если proposals оформляются как MR | Читать outcomes/docs и создавать proposal issues/MRs |

Для GitLab избегайте Owner/Maintainer для всех ролей, кроме отдельного human/platform automation account, который не используется Hermes agents напрямую.

## Детализация по ролям

### hermes-planner

Назначение роли: анализ требований, чтение кода, создание спецификации и плана.

Разрешить:

- read repository tree;
- read file contents;
- search code;
- read issues/work items;
- read pull/merge requests;
- read CI status.

Запретить:

- create branch;
- push files;
- create PR/MR;
- approve PR/MR;
- merge;
- edit repository settings;
- edit workflows/rulesets/branch protection.

GitHub minimum:

```text
Metadata: read
Contents: read
Issues: read
Pull requests: read
Actions: read
```

GitLab minimum:

```text
Role: Reporter
Scopes: read_api, read_repository
```

### hermes-project-manager

Назначение роли: определять измеримые цели проекта, сохранять BRD/PRD governance, управлять Funnel/Discovery, scope, roadmap/backlog, WIP, рисками, weekly decision reporting, flow/health metrics, статусами, решениями и evidence gates.

Разрешить:

- read repository tree и file contents как evidence;
- search code для понимания impact/dependencies;
- read issues/work items;
- create issues для project-management artifacts;
- add issue comments для статусов, weekly reports, decision packets, risk updates, retrospectives и handoffs.

Запретить:

- create branch;
- push files;
- create PR/MR;
- approve PR/MR;
- merge;
- микроменеджить technical implementation approach, который принадлежит Tech Lead и Delivery Team;
- менять budget, access rights, credentials, production state, repository settings, workflows, rulesets или branch protection.

Выход: обновлённое или подготовленное состояние проекта с concrete next step, owner, deadline/range и completion evidence.

### hermes-builder

Назначение роли: реализовать утверждённый change-set и открыть change request.

Разрешить:

- read repository tree/files;
- create branch only with prefix `agent/`;
- push files only to `agent/*` branches;
- create PR/MR from `agent/*` to protected base branch;
- read CI status;
- trigger CI only if required by workflow.

Запретить:

- write to `main`, `master`, `release/*`;
- merge PR/MR;
- edit branch protection/rulesets;
- edit CODEOWNERS;
- edit CI workflow files unless separately approved;
- edit protected paths from `policies/protected-paths.txt`;
- access repository secrets;
- delete repository, environments, releases or packages.

GitHub minimum:

```text
Metadata: read
Contents: read/write
Pull requests: read/write
Actions: read
Actions: write only if builder triggers workflow_dispatch
```

GitLab minimum:

```text
Role: Developer
Scopes: api, read_repository, write_repository
```

Provider-side policy must additionally enforce:

```text
branch starts with agent/
target repository is allowed
protected paths are denied
merge tools are denied
admin/settings tools are denied
```

### hermes-reviewer

Назначение роли: независимый review фиксированной revision.

Разрешить:

- read PR/MR metadata;
- read diff/files;
- read CI/checks/actions/pipeline evidence;
- read code scanning/dependabot findings where available;
- add review comments;
- approve or request changes if token identity is independent from builder identity.

Запретить:

- push files;
- create branch;
- modify author branch;
- merge;
- edit checks/gates;
- edit workflow files/settings;
- approve own work.

GitHub minimum:

```text
Metadata: read
Contents: read
Pull requests: read/write
Issues: read/write if PR comments use issue comments
Actions: read
Code scanning alerts: read
Dependabot alerts: read
```

GitLab minimum:

```text
Role: Reporter for read-only review
Role: Developer only if GitLab approval/comment APIs require it
Scopes: api, read_repository
```

### hermes-release

Назначение роли: принять fail-closed решение по immutable release candidate.

Если release control plane не представлен в GitHub/GitLab, роль должна иметь только read-доступ к evidence.

Разрешить:

- read workflow/pipeline status;
- read releases/deployments only if used as release evidence;
- create/update deployment or release only if this is the approved release mechanism.

Запретить:

- write repository contents;
- create branch;
- create arbitrary PR/MR;
- change workflow/rulesets/environments;
- access repository secrets;
- bypass approvals.

GitHub minimum for evidence-only mode:

```text
Metadata: read
Actions: read
Deployments: read
Releases: read
```

GitHub if release role manages GitHub Deployments/Releases:

```text
Deployments: read/write
Releases: read/write
```

GitLab minimum:

```text
Role: Reporter
Scopes: api, read_repository
```

Use Maintainer only for a separate trusted release automation identity, not as a default Hermes role token.

### hermes-incident

Назначение роли: incident triage, timeline и ограниченные reversible actions.

Для repository provider эта роль обычно работает с incident issues/comments, а не с кодом.

Разрешить:

- read incident issues;
- write incident comments/timeline;
- read runbook files if runbooks are stored in repo;
- read CI/actions only for context.

Запретить:

- write code;
- create branch;
- create PR/MR for code changes;
- merge;
- edit workflows/settings;
- access secrets;
- delete issues/releases/packages.

GitHub minimum:

```text
Metadata: read
Issues: read/write
Actions: read
Contents: read only if runbooks are stored in repo
```

GitLab minimum:

```text
Role: Reporter
Scopes: api
Optional: read_repository if runbooks are stored in repo
```

### hermes-learning

Назначение роли: создавать proposals для улучшения процесса, docs или skills без самостоятельной активации.

Разрешить:

- read repository docs/skills;
- read issues/PRs/MRs and outcomes;
- create proposal issue;
- optionally create draft PR/MR targeting human review only.

Запретить:

- publish/activate skills;
- merge proposal PR/MR;
- write protected branches;
- edit CI/gates/settings;
- access secrets/PII;
- modify production docs directly without human review.

GitHub minimum for issue-only proposals:

```text
Metadata: read
Contents: read
Issues: read/write
Pull requests: read
```

GitHub if draft PR proposals are allowed:

```text
Pull requests: read/write
Contents: read/write only to agent/proposal branches
```

GitLab minimum:

```text
Role: Reporter for issue-only proposals
Role: Developer only for MR proposal branches
Scopes: api, read_repository
Optional: write_repository for MR proposal branches
```

## GitHub MCP toolsets by role

Если используется official GitHub MCP Server, включайте минимальные toolsets или explicit tools.

Рекомендуемый старт:

| Роль | GitHub MCP toolsets |
|---|---|
| `hermes-planner` | `repos`, `issues`, `pull_requests`, `actions` read-only where supported |
| `hermes-project-manager` | `repos`, `issues`, `pull_requests`, `actions` read-only plus issue comment/create where supported |
| `hermes-builder` | `repos`, `git`, `pull_requests`, `actions` |
| `hermes-reviewer` | `repos`, `pull_requests`, `issues`, `actions`, `code_security`, `dependabot` |
| `hermes-release` | `actions`, optional `repos`/release/deployment tools if exposed |
| `hermes-incident` | `issues`, optional `repos` read-only |
| `hermes-learning` | `issues`, `repos` read-only, optional `pull_requests` for draft proposal PRs |

Перед фиксацией allowlist обязательно выполните `tools/list` для каждого role token и убедитесь, что `profiles/*/config.yaml` содержит только реально доступные tool names.

## Protected branches and paths

GitHub/GitLab permissions сами по себе недостаточны. Обязательно включите server-side защиту:

- branch protection или rulesets для `main`, `master`, `release/*`;
- запрет force push и deletion для protected branches;
- required PR/MR review для protected branches;
- required status checks/pipelines;
- CODEOWNERS для чувствительных зон;
- CI check для `policies/protected-paths.txt`;
- запрет workflow/ruleset/branch protection changes без human approval.

Protected paths должны включать минимум:

```text
.github/workflows/**
.gitlab-ci.yml
CODEOWNERS
policies/**
kubernetes/production/**
terraform/production/**
```

Актуальный список хранится в `policies/protected-paths.txt`.

## Минимальные проверки перед запуском

Для каждого role token проверьте:

- token видит только целевой repository/project;
- planner не может создавать branch;
- builder не может писать в `main`;
- builder может писать только в `agent/*`;
- builder не может merge;
- reviewer не может push files;
- release не может write contents;
- incident не может write contents;
- learning не может merge proposal;
- ни одна роль не может менять repository settings, branch protection, rulesets или secrets.

## Краткий итог

Минимальная безопасная модель:

```text
planner  = read-only repo + issues + PR + CI
builder  = write only to agent/* + PR create + CI read/trigger
reviewer = read repo/PR/CI + review/comment, no code write
release  = read evidence, optional deployment/release write only if GitHub/GitLab is release control plane
incident = issue timeline/comments, optional runbook read, no code write
learning = proposal issue/draft PR only, no activation/merge
```
