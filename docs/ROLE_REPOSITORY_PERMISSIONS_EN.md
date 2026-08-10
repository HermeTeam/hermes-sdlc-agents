# Repository Permissions by Hermes SDLC Agent Role

This document describes the minimum repository permissions required by each `hermes-sdlc-agents` role when working directly through GitHub/GitLab API/MCP.

Goal: grant each role only the repository permissions it needs, without clone access, admin access, merge access, or permission to change branch protection.

## Baseline Rules

- Use a separate `GIT_PROVIDER_MCP_TOKEN` for each role.
- Do not reuse one token across roles.
- Do not give Hermes agents a broad GitHub/GitLab admin token.
- Do not grant permissions to change branch protection, rulesets, CODEOWNERS, CI settings, or repository settings.
- Do not grant direct write access to protected branches: `main`, `master`, `release/*`.
- Builder may write only to task branches with the `agent/` prefix.
- Reviewer must not be able to modify files or the author's branch.
- Planner and project manager must not have code write access.
- Release, incident, and learning roles receive repository-write permissions only if their workflow is actually represented in GitHub/GitLab Issues, PRs/MRs, Releases, or Deployments.
- The repository is not cloned into Hermes containers. All work goes through provider API/MCP.

## Recommended Token Model

Prefer GitHub App installation tokens or GitLab project access tokens with short TTL and role-specific scopes.

Acceptable options:

- GitHub fine-grained PAT restricted to one repository.
- GitHub App installation token restricted to one repository.
- GitLab project access token restricted to one project.
- GitLab group access token only if the MCP/API layer additionally enforces a project allowlist.

Not recommended:

- classic GitHub PAT with `repo` access across all user repositories;
- GitLab personal access token with broad group/admin permissions;
- one shared token for all roles;
- repository admin/maintainer token for planner or reviewer.

## GitHub Permissions Matrix

This table uses GitHub fine-grained permission names. For a GitHub App, use equivalent repository permissions.

| Role | Minimum GitHub permissions | Purpose |
|---|---|---|
| `hermes-planner` | Metadata: read; Contents: read; Issues: read; Pull requests: read; Actions: read | Read requirements, issue context, code, PR context, and CI evidence for planning |
| `hermes-project-manager` | Metadata: read; Contents: read; Issues: read/write; Pull requests: read; Actions: read | Manage intake, status, backlog, risks, decisions, and evidence through Issues without code or branch mutation |
| `hermes-builder` | Metadata: read; Contents: read/write; Pull requests: read/write; Actions: read; Actions: write only if builder triggers workflows | Create `agent/*` branches, write change-sets, open PRs, read/trigger CI |
| `hermes-reviewer` | Metadata: read; Contents: read; Pull requests: read/write; Issues: read/write if PR comments use issue comments; Actions: read; Code scanning alerts: read; Dependabot alerts: read | Read diff/evidence, leave review/comments, approve/request changes, inspect security findings |
| `hermes-release` | Metadata: read; Actions: read; Deployments: read/write only if release is managed through GitHub Deployments; Releases: read/write only if release creates GitHub Releases | Read immutable candidate/evidence and perform only approved promote/abort actions if GitHub is the release control plane |
| `hermes-incident` | Metadata: read; Issues: read/write; Actions: read; Contents: read only if runbooks are stored in the repository | Read incident issues, write timeline/comments, read runbook docs and CI context |
| `hermes-learning` | Metadata: read; Contents: read; Issues: read/write; Pull requests: read; Pull requests: write only if proposals are draft PRs | Read outcomes/docs/skills, create proposal issues or draft PRs for human review |

## GitLab Permissions Matrix

GitLab permissions depend on token type. For project access tokens, prefer the lowest project role and token scopes that still support the required MCP/API calls.

| Role | Project role | Token scopes | Purpose |
|---|---|---|---|
| `hermes-planner` | Reporter | `read_api`, `read_repository` | Read issues, MR context, repository files, and pipeline evidence |
| `hermes-project-manager` | Reporter | `api`, `read_repository` | Read/update project-management issues and read repository evidence without repository writes |
| `hermes-builder` | Developer | `api`, `read_repository`, `write_repository` | Create branch, commit/change-set, MR, and trigger pipeline |
| `hermes-reviewer` | Reporter or Developer | `api`, `read_repository`; Developer only if approval/comment APIs require it | Read MR diff/evidence and leave review/discussions |
| `hermes-release` | Reporter, or Maintainer only when GitLab Deployments/Releases write is required | `api`, `read_repository`; `write_repository` is not needed for normal release approval | Read pipeline/release evidence and manage release/deployment only if GitLab is the release control plane |
| `hermes-incident` | Reporter | `api`, optional `read_repository` | Read/update incident issues and read runbook docs if needed |
| `hermes-learning` | Reporter or Developer | `api`, `read_repository`; Developer only for MR proposal branches | Read outcomes/docs and create proposal issues/MRs |

For GitLab, avoid Owner/Maintainer for all Hermes roles except a separate trusted human/platform automation identity that is not used directly by Hermes agents.

## Role Details

### hermes-planner

Role purpose: analyze requirements, read code, and create a specification and implementation plan.

Allow:

- read repository tree;
- read file contents;
- search code;
- read issues/work items;
- read pull/merge requests;
- read CI status.

Deny:

- create branch;
- push files;
- create PR/MR;
- approve PR/MR;
- merge;
- edit repository settings;
- edit workflows, rulesets, or branch protection.

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

Role purpose: define measurable project goals, preserve BRD/PRD governance, manage Funnel/Discovery, scope, roadmap/backlog, WIP, risks, weekly decision reporting, flow/health metrics, status, decisions, and evidence gates.

Allow:

- read repository tree and file contents as evidence;
- search code to understand impact and dependencies;
- read issues/work items;
- create issues for project-management artifacts;
- add issue comments for status, weekly reports, decision packets, risk updates, retrospectives, and handoffs.

Deny:

- create branch;
- push files;
- create PR/MR;
- approve PR/MR;
- merge;
- micromanage the technical implementation approach owned by the Tech Lead and Delivery Team;
- change budget, access rights, credentials, production state, repository settings, workflows, rulesets, or branch protection.

Exit: updated or prepared project state with concrete next step, owner, deadline/range, and completion evidence.

### hermes-builder

Role purpose: implement an approved change-set and open a change request.

Allow:

- read repository tree/files;
- create branch only with prefix `agent/`;
- push files only to `agent/*` branches;
- create PR/MR from `agent/*` to a protected base branch;
- read CI status;
- trigger CI only if required by the workflow.

Deny:

- write to `main`, `master`, `release/*`;
- merge PR/MR;
- edit branch protection/rulesets;
- edit CODEOWNERS;
- edit CI workflow files unless separately approved;
- edit protected paths from `policies/protected-paths.txt`;
- access repository secrets;
- delete repository, environments, releases, or packages.

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

The provider-side policy must additionally enforce:

```text
branch starts with agent/
target repository is allowed
protected paths are denied
merge tools are denied
admin/settings tools are denied
```

### hermes-reviewer

Role purpose: independently review a fixed change request revision.

Allow:

- read PR/MR metadata;
- read diff/files;
- read CI/checks/actions/pipeline evidence;
- read code scanning/dependabot findings where available;
- add review comments;
- approve or request changes if token identity is independent from builder identity.

Deny:

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

Role purpose: make fail-closed decisions for immutable release candidates.

If the release control plane is not represented in GitHub/GitLab, this role should have read-only evidence permissions.

Allow:

- read workflow/pipeline status;
- read releases/deployments only if used as release evidence;
- create/update deployment or release only if this is the approved release mechanism.

Deny:

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

Role purpose: incident triage, timeline updates, and limited reversible actions.

For repository providers, this role usually works with incident issues/comments rather than code.

Allow:

- read incident issues;
- write incident comments/timeline;
- read runbook files if runbooks are stored in the repository;
- read CI/actions only for context.

Deny:

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

Role purpose: create proposals for process, docs, or skills improvements without self-activation.

Allow:

- read repository docs/skills;
- read issues/PRs/MRs and outcomes;
- create proposal issue;
- optionally create draft PR/MR targeting human review only.

Deny:

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

## GitHub MCP Toolsets by Role

If the official GitHub MCP Server is used, enable the smallest practical toolsets or explicit tools.

Recommended starting point:

| Role | GitHub MCP toolsets |
|---|---|
| `hermes-planner` | `repos`, `issues`, `pull_requests`, `actions` read-only where supported |
| `hermes-project-manager` | `repos`, `issues`, `pull_requests`, `actions` read-only plus issue comment/create where supported |
| `hermes-builder` | `repos`, `git`, `pull_requests`, `actions` |
| `hermes-reviewer` | `repos`, `pull_requests`, `issues`, `actions`, `code_security`, `dependabot` |
| `hermes-release` | `actions`, optional `repos`/release/deployment tools if exposed |
| `hermes-incident` | `issues`, optional `repos` read-only |
| `hermes-learning` | `issues`, `repos` read-only, optional `pull_requests` for draft proposal PRs |

Before finalizing allowlists, run `tools/list` for each role token and confirm that `profiles/*/config.yaml` contains only tool names that are actually available.

## Protected Branches and Paths

GitHub/GitLab permissions are not sufficient on their own. Enable server-side protection:

- branch protection or rulesets for `main`, `master`, `release/*`;
- no force push and no deletion for protected branches;
- required PR/MR review for protected branches;
- required status checks/pipelines;
- CODEOWNERS for sensitive areas;
- CI check for `policies/protected-paths.txt`;
- no workflow/ruleset/branch protection changes without human approval.

Protected paths should include at least:

```text
.github/workflows/**
.gitlab-ci.yml
CODEOWNERS
policies/**
kubernetes/production/**
terraform/production/**
```

The active list is stored in `policies/protected-paths.txt`.

## Minimum Pre-Launch Checks

For each role token, verify:

- the token can see only the target repository/project;
- planner cannot create branches;
- builder cannot write to `main`;
- builder can write only to `agent/*`;
- builder cannot merge;
- reviewer cannot push files;
- release cannot write contents;
- incident cannot write contents;
- learning cannot merge proposals;
- no role can change repository settings, branch protection, rulesets, or secrets.

## Summary

Minimum safe model:

```text
planner  = read-only repo + issues + PR + CI
builder  = write only to agent/* + PR create + CI read/trigger
reviewer = read repo/PR/CI + review/comment, no code write
release  = read evidence, optional deployment/release write only if GitHub/GitLab is release control plane
incident = issue timeline/comments, optional runbook read, no code write
learning = proposal issue/draft PR only, no activation/merge
```
