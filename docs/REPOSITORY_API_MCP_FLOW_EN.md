# Repository API/MCP Flow

> Audience: platform engineers, SDLC gateway maintainers, DevOps/SRE engineers, and agent operators who configure Hermes SDLC roles and repository integrations.

### Purpose

This document describes the repository access flow used by `hermes-sdlc-agents` after migrating from local writable checkouts to provider-neutral repository access through the SDLC MCP gateway.

The core rule is:

```text
Hermes agents do not receive GitHub/GitLab/Forgejo credentials and do not mount writable repository checkouts.
All repository reads and writes go through typed SDLC MCP repository tools.
```

### High-level architecture

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

The SDLC MCP gateway is the security boundary. GitHub, GitLab, Forgejo, or provider MCP servers are upstream implementation details and must not be exposed directly to Hermes agents.

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
  -> reads repository files through SDLC MCP
  -> creates a bounded patch/change-set
  -> asks SDLC MCP to create/update a task branch
  -> asks SDLC MCP to apply and commit the patch
  -> triggers CI or workspace checks through SDLC MCP
  -> creates a provider-neutral change request
```

There is no `REPO_DIR`, no `/workspace/repo`, and no Git provider token in the Hermes builder container.

### Provider-neutral terminology

The SDLC contract uses provider-neutral terms so the same agent flow works with GitHub, GitLab, or Forgejo.

| SDLC term | GitHub | GitLab | Forgejo/Gitea |
|---|---|---|---|
| `change_request` | Pull Request | Merge Request | Pull Request |
| review comment | PR review comment | Diff note/discussion | PR review comment |
| approval | PR approval | MR approval | PR approval |
| CI evidence | Checks / Actions | Pipelines / Jobs | Actions / external CI |

Provider-specific IDs and URLs should stay inside the SDLC MCP gateway. Agents should use stable `repository_id` values instead of raw provider URLs.

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

The builder implements approved work through SDLC MCP repository tools.

Allowed repository behavior:

- read assigned `work_item`, `spec`, and `plan`;
- read repository files and trees through MCP;
- create a task branch named `agent/<work-item-id>-<slug>`;
- submit a bounded text patch/change-set;
- commit changes through the repository adapter;
- trigger CI or workspace checks;
- create or update a change request.

Not allowed:

- use a local checkout;
- obtain GitHub/GitLab/Forgejo credentials;
- push directly with Git;
- write protected branches;
- merge change requests;
- change CI workflows, quality gates, branch protection, or production configuration.

The builder may return `PR_READY_FOR_REVIEW` only after the SDLC MCP gateway accepts the change-set and required CI/workspace evidence is available.

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

The gateway must enforce reviewer independence through provenance, not through model text.

#### Release

The release role does not use repository write access. It works with immutable release candidates created by trusted CI.

Allowed behavior:

- read candidate, policy, CI, quality, SLO, and rollout evidence;
- call `deployment_promote` or `deployment_abort` only for an existing candidate.

#### Incident and Learning

Incident and learning roles do not receive repository write access. Incident may read service/catalog/release context. Learning may create proposals, but cannot directly publish docs, activate skills, or mutate repositories.

### Repository tools

Typical provider-neutral tool surface:

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

Do not expose broad tools such as `github_request`, `gitlab_request`, raw GraphQL, generic HTTP, repository admin, merge, branch protection mutation, or workflow editing tools to Hermes.

### Required mutation envelope

Every mutating repository call must include enough information for authorization, concurrency control, idempotency, and audit.

Example:

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

The gateway must reject the call if:

- the role is not allowed to call the tool;
- the repository is outside the work item scope;
- the branch does not start with `agent/<work-item-id>-`;
- the base or head revision is stale;
- the diff touches protected paths;
- the operation requires merge, admin, or protected branch privileges;
- the same idempotency key is reused with different arguments.

### Patch/change-set rules

`repo_apply_patch` should accept only bounded text changes by default:

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
SDLC MCP gateway
  -> ephemeral workspace worker
    -> clone repository in isolated workspace
    -> apply patch
    -> run allowlisted checks
    -> commit/push task branch
    -> return logs, artifacts, and exit codes
```

Minimum path:

```text
repo_commit_changes
  -> ci_trigger_pipeline
  -> ci_get_status
  -> ci_get_test_results
```

If required CI/workspace evidence is missing, pending, or failed, the builder must return `BLOCKED`, not `PR_READY_FOR_REVIEW`.

### Security requirements

- Hermes agents must not receive GitHub/GitLab/Forgejo tokens.
- Provider tokens live only in the SDLC MCP repository adapter or workspace worker.
- Provider tokens must not have admin, branch protection, protected branch write, or merge scopes.
- Repository content must be treated as untrusted input because it may contain prompt injection.
- Provider MCP resources, prompts, sampling, and elicitation must not be exposed to Hermes.
- Protected path checks must run server-side and again in trusted CI outside the author branch.
- Every mutation must produce an audit record with role, subject, tool, canonical argument hash, upstream request ID, before/after revision, idempotency key, and policy decision.

### Operational canaries

Positive canaries:

1. Planner reads a file through `repo_read_file` and creates a plan.
2. Builder creates `agent/<work-item-id>-<slug>`, applies a small patch, triggers checks, and opens a change request.
3. Reviewer reads the fixed diff and submits a review comment.
4. Release reads candidate evidence and promotes or aborts without repository access.

Negative canaries:

1. Builder attempts to write `main` directly and receives server-side deny.
2. Builder attempts to modify a protected path and receives server-side deny.
3. Builder attempts to call a raw GitHub/GitLab provider tool and receives deny or tool not found.
4. Reviewer attempts to modify the author branch and receives deny.
5. Planner attempts to create a branch and receives deny.
6. Any role attempts merge and receives deny.
