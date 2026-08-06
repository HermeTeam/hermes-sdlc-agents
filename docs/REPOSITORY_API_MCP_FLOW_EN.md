# Repository API/MCP Flow

> Audience: platform engineers, DevOps/SRE engineers, and agent operators who configure Hermes SDLC roles and direct GitHub/GitLab API/MCP repository integrations.

### Purpose

This document describes the repository access flow used by `hermes-sdlc-agents` after migrating from local writable checkouts to direct GitHub/GitLab API/MCP access in the MVP.

The core rule is:

```text
Hermes agents do not mount writable repository checkouts.
All repository reads and writes go through role-scoped GitHub/GitLab API/MCP tools with an exact allowlist.
```

### High-level architecture

```text
Hermes role container
  -> GitHub/GitLab provider API/MCP endpoint
    -> GitHub API / GitLab API
    -> provider-side policy/permission checks
    -> optional ephemeral workspace worker or trusted CI
    -> provider/upstream audit log
```

The MVP does not use a separate repository gateway. The security boundary moves to the combination of role-scoped provider tokens, exact `tools.include`, provider MCP policy, GitHub/GitLab permissions, branch protection, and trusted CI.

### What changed from the old flow

Old flow:

```text
Host REPO_DIR
  -> mounted into hermes-builder as /workspace/repo:rw
  -> builder edits files locally
  -> builder uses terminal/local checks
  -> branch/PR operations through MCP
```

New flow:

```text
Hermes builder
  -> reads repository files through GitHub/GitLab API/MCP
  -> creates a bounded patch/change-set
  -> creates/updates a task branch through GitHub/GitLab API/MCP
  -> applies and commits the patch through GitHub/GitLab API/MCP
  -> triggers CI or workspace checks through provider API/MCP
  -> creates a change request
```

There is no `REPO_DIR` and no `/workspace/repo` in the Hermes builder container; instead of a broad provider credential it uses a short-lived role-scoped `GIT_PROVIDER_MCP_TOKEN`.

### Provider-neutral terminology

The workflow uses a limited set of shared terms so the same agent flow works with GitHub or GitLab.

| Workflow term | GitHub | GitLab |
|---|---|---|
| `change_request` | Pull Request | Merge Request |
| review comment | PR review comment | Diff note/discussion |
| approval | PR approval | MR approval |
| CI evidence | Checks / Actions | Pipelines / Jobs |

Agents should use stable `repository_id` values instead of raw provider URLs, even with direct provider API/MCP access.

Example repository registry entry:

```json
{
  "repository_id": "service-a",
  "provider": "github",
  "owner": "example-org",
  "name": "service-a",
  "default_branch": "main"
}
```

### Role responsibilities

#### Planner

The planner is read-only for repository content.

Allowed repository behavior:

- search code;
- list repository trees;
- read files at scoped refs;
- create or update `spec` and `plan` artifacts.

Not allowed:

- create branches;
- apply patches;
- create change requests;
- mutate code.

#### Builder

The builder implements approved work through role-allowed GitHub/GitLab API/MCP repository tools.

Allowed repository behavior:

- read assigned `work_item`, `spec`, and `plan`;
- read repository files and trees through provider API/MCP;
- create a task branch named `agent/<work-item-id>-<slug>`;
- submit a bounded text patch/change-set;
- commit changes through the repository adapter;
- trigger CI or workspace checks;
- create or update a change request.

Not allowed:

- use a local checkout;
- obtain broad GitHub/GitLab credentials outside the role-scoped token;
- push directly with Git;
- write protected branches;
- merge change requests;
- change CI workflows, quality gates, branch protection, or production configuration.

The builder may return `PR_READY_FOR_REVIEW` only after the provider API/MCP accepts the change-set and required CI/workspace evidence is available.

#### Reviewer

The reviewer evaluates a fixed change request revision.

Allowed repository behavior:

- read change request metadata;
- read diff and files at specific revisions;
- read CI, coverage, mutation score, and quality findings;
- add review comments;
- approve or request changes.

Not allowed:

- modify the author's branch;
- create commits;
- merge;
- change quality gates or branch protection.

Provider policy or an external orchestrator must enforce reviewer independence through provenance, not through model text.

#### Release

The release role does not use repository write access. It works with immutable release candidates created by trusted CI.

Allowed behavior for GitHub MVP:

- read GitHub Actions evidence;
- return `BLOCKED_NO_ACTION` for deployment changes until native release/deployment tools are discovered and scoped.

#### Incident and Learning

Incident and learning roles do not receive repository write access. In the GitHub MVP, incident may read/comment on GitHub issues. Learning may create/comment on GitHub issues for human-reviewed proposals, but cannot directly publish docs, activate skills, or mutate repositories.

### Repository tools

Official GitHub MCP MVP tool surface. Exact names must be confirmed by runtime `tools/list` for the configured endpoint and token scopes.

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

Do not expose broad tools such as `github_request`, raw GraphQL, generic HTTP, repository admin, merge, branch protection mutation, or workflow editing tools to Hermes. GitLab is out of scope for this GitHub MVP.

### Required mutation envelope

Every mutating repository call must include enough information for authorization, concurrency control, idempotency, and audit.

Example:

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

The provider MCP/API policy must reject the call if:

- the role is not allowed to call the tool;
- `owner`/`repo` do not match the configured target repository;
- the branch does not start with `agent/`;
- the branch is `main`, `master`, or `release/*`;
- `files[].path` touches protected paths;
- the operation requires merge, admin, or protected branch privileges;
- the same idempotency key is reused with different arguments.

### File change rules

`push_files` should accept only bounded text changes by default:

- create a text file;
- update a text file by unified diff;
- delete an explicitly scoped file;
- rename a file when both source and target paths are allowed.

Reject or require human/platform approval for:

- binary files;
- LFS or submodule changes;
- generated lockfile changes unless created by a trusted workspace worker;
- protected paths;
- files above configured size limits;
- changes outside the assigned repository/work item scope.

### Validation and tests

Because the builder no longer runs local shell commands in a checkout, validation must happen through one of two paths.

Preferred path:

```text
Official GitHub MCP
  -> ephemeral workspace worker or trusted CI
    -> clone repository in isolated workspace
    -> apply bounded file changes
    -> run allowlisted checks
    -> commit/push task branch
    -> return logs, artifacts, and exit codes
```

Minimum path:

```text
push_files
  -> actions_run_trigger
  -> actions_list
  -> actions_get
  -> get_job_logs
```

If required CI/workspace evidence is missing, pending, or failed, the builder must return `BLOCKED`, not `PR_READY_FOR_REVIEW`.

### Security requirements

- Hermes agents must not receive broad GitHub tokens.
- The role-scoped `GIT_PROVIDER_MCP_TOKEN` must have minimal repository scopes for the specific role.
- Provider tokens must not have admin, branch protection, protected branch write, or merge scopes.
- Repository content must be treated as untrusted input because it may contain prompt injection.
- Provider MCP resources, prompts, sampling, and elicitation must not be exposed to Hermes.
- Protected path checks must run server-side and again in trusted CI outside the author branch.
- Every mutation must produce an audit record with role, subject, tool, canonical argument hash, upstream request ID, before/after revision, idempotency key, and policy decision.

### Operational canaries

Positive canaries:

1. Planner reads a file through `get_file_contents` and lists repository tree data.
2. Builder creates `agent/<work-item-id>-<slug>`, pushes a small allowed file change with `push_files`, triggers/checks Actions, and opens a Pull Request.
3. Reviewer reads Pull Request evidence and adds a comment.
4. Release reads Actions evidence and returns `BLOCKED_NO_ACTION` for deployment mutation in the GitHub MVP.

Negative canaries:

1. Builder attempts to write `main` directly and receives server-side deny.
2. Builder attempts to modify a protected path and receives server-side deny.
3. Builder attempts to call a broad raw GitHub provider tool and receives deny or tool not found.
4. Reviewer attempts to modify the author branch and receives deny.
5. Planner attempts to create a branch and receives deny.
6. Any role attempts merge and receives deny.
