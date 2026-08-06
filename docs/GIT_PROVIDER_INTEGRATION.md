# Official GitHub MCP Integration

Hermes GitHub MVP roles connect directly to the official GitHub MCP endpoint:

```env
GIT_PROVIDER_MCP_URL=https://api.githubcopilot.com/mcp/
```

The active repository MCP allowlists use native GitHub MCP tools, not the historical `repo_*`, `ci_*`, `quality_*`, `work_item_*`, `spec_*`, or `plan_*` facade. Exact tool availability must be confirmed with runtime `tools/list` for the configured endpoint, server version, toolsets, and token scopes.

GitLab support is out of scope for this MVP and requires a separate tool mapping.

## Identity And Tokens

Each role token in the main `.env` must be a GitHub credential accepted by the official GitHub MCP Server, such as a fine-grained PAT or GitHub App installation token scoped to the target repository. Compose maps `PLANNER_GITHUB_MCP_TOKEN`, `BUILDER_GITHUB_MCP_TOKEN`, `REVIEWER_GITHUB_MCP_TOKEN`, `RELEASE_GITHUB_MCP_TOKEN`, `INCIDENT_GITHUB_MCP_TOKEN`, and `LEARNING_GITHUB_MCP_TOKEN` into container-local `GIT_PROVIDER_MCP_TOKEN` for the matching agent. An arbitrary internal workload JWT will not work unless an intermediate proxy translates it into a GitHub credential.

Recommended minimum fine-grained GitHub permissions:

| Role | Permissions |
| --- | --- |
| `hermes-planner` | Contents read, Issues read, Pull requests read, Metadata read |
| `hermes-builder` | Contents read/write, Pull requests read/write, Actions read/write if triggering workflows otherwise read, Metadata read |
| `hermes-reviewer` | Contents read, Pull requests read/write, Issues read/write for PR comments if needed, Actions read, Metadata read |
| `hermes-release` | Actions read, Metadata read |
| `hermes-incident` | Issues read/write, Metadata read |
| `hermes-learning` | Issues read/write, Pull requests read, Contents read, Metadata read |

Do not give Hermes broad organization admin tokens, repository admin permissions, branch-protection mutation permissions, merge permissions, Kubernetes credentials, cloud credentials, or runner shell access.

## Active Native Tool Shape

The offline configuration currently uses the GitHub MVP tool shape below. Treat it as an allowlist candidate until runtime `tools/list` confirms every name.

| Role | Native GitHub MCP tools |
| --- | --- |
| `hermes-planner` | `get_file_contents`, `get_repository_tree`, `search_code`, `issue_read`, `list_issues` |
| `hermes-builder` | `get_file_contents`, `get_repository_tree`, `search_code`, `create_branch`, `push_files`, `create_pull_request`, `actions_run_trigger`, `actions_get`, `actions_list`, `get_job_logs` |
| `hermes-reviewer` | `pull_request_read`, `get_file_contents`, `actions_get`, `actions_list`, `get_job_logs`, `add_issue_comment` |
| `hermes-release` | `actions_get`, `actions_list` |
| `hermes-incident` | `issue_read`, `list_issues`, `add_issue_comment` |
| `hermes-learning` | `issue_read`, `list_issues`, `add_issue_comment`, `create_issue` |

Release, incident, and learning roles are intentionally reduced to GitHub-native read/comment/issue workflows for the MVP. The old deployment, flag, runbook, and proposal facade tools are not exposed unless a separate, policy-enforced MCP integration is added later.

## Required Policy Checks

Provider-side policy or an equivalent OPA layer must enforce:

- `owner` and `repo` match the configured target repository.
- Builder branch mutations target only `agent/*` branches.
- Builder cannot write `main`, `master`, or `release/*`.
- Builder `push_files` cannot touch protected paths such as `.github/workflows/`, `policies/`, or CODEOWNERS without a separate trusted gate.
- `create_pull_request` uses an `agent/*` head and a protected base branch.
- Reviewer comments require independent-review evidence if the orchestrator can supply it.
- Merge, branch protection, repository administration, raw HTTP, raw GraphQL, and broad provider request tools are denied or not exposed.

The sample policy in `policies/mcp-policy.rego` shows these argument-level checks using GitHub-native arguments such as `owner`, `repo`, `branch`, `ref`, `head`, `base`, `files`, `issue_number`, and `body`.

## Runtime Discovery Checklist

Before enabling automation with real credentials:

1. Run MCP `tools/list` against `https://api.githubcopilot.com/mcp/` with each role token.
2. Verify every tool in `profiles/<role>/config.yaml` exists for that token.
3. Verify planner can read file/tree/search data but cannot mutate.
4. Verify builder negative canaries fail before any positive write canary: no writes to protected branches, protected paths, merge/admin tools, or non-target repositories.
5. Verify reviewer can read PR evidence and comment, but cannot push files.
6. Record tool inventory and canary results in implementation evidence or PR notes, not in secrets or generated source files.
