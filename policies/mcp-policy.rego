package hermes.sdlc.repository_mcp

import rego.v1

default allow := false

protected_branches := {"main", "master"}
builder_branch_mutations := {"create_branch", "push_files", "create_pull_request", "actions_run_trigger"}
project_manager_mutations := {"add_issue_comment", "issue_write"}
reviewer_mutations := {"add_issue_comment"}
incident_mutations := {"add_issue_comment"}
learning_mutations := {"add_issue_comment", "issue_write"}
denied_admin_tools := {
  "merge_pull_request", "repo_merge_pull_request", "repo_merge_change_request",
  "update_branch_protection", "delete_branch", "delete_repository", "create_repository",
}

base_authorized if {
  input.identity.active == true
  input.identity.aud == "git-provider-mcp"
  time.now_ns() < input.identity.exp * 1000000000
  input.tool in data.spec.roles[input.identity.role].allowTools
  not denied_admin_tools[input.tool]
  github_repository_scoped(input.args)
}

nonempty(args, key) if {
  object.get(args, key, "") != ""
}

expected_owner := object.get(input.repository, "owner", "")
expected_repo := object.get(input.repository, "repo", object.get(input.repository, "name", ""))

github_repository_scoped(args) if {
  expected_owner != ""
  expected_repo != ""
  object.get(args, "owner", "") == expected_owner
  object.get(args, "repo", "") == expected_repo
}

target_branch(args) := branch if {
  branch := object.get(args, "branch", object.get(args, "ref", object.get(args, "head", "")))
}

base_branch(args) := branch if {
  branch := object.get(args, "base", object.get(input.repository, "default_branch", "main"))
}

branch_allowed(branch) if {
  startswith(branch, "agent/")
  not protected_branch(branch)
}

protected_branch(branch) if {
  protected_branches[branch]
}

protected_branch(branch) if {
  startswith(branch, "release/")
}

protected_base_allowed(branch) if {
  protected_branch(branch)
}

protected_file_path(path) if {
  prefix := input.protected_paths[_]
  startswith(path, prefix)
}

file_path(file) := path if {
  path := object.get(file, "path", object.get(file, "file_path", ""))
}

push_file_paths_allowed(files) if {
  every file in files {
    path := file_path(file)
    path != ""
    not protected_file_path(path)
  }
}

allow if {
  base_authorized
  input.identity.role == "hermes-planner"
}

allow if {
  base_authorized
  input.identity.role == "hermes-project-manager"
  not project_manager_mutations[input.tool]
}

allow if {
  base_authorized
  input.identity.role == "hermes-project-manager"
  input.tool == "add_issue_comment"
  nonempty(input.args, "issue_number")
  nonempty(input.args, "body")
}

allow if {
  base_authorized
  input.identity.role == "hermes-project-manager"
  input.tool == "issue_write"
  nonempty(input.args, "title")
  nonempty(input.args, "body")
}

allow if {
  base_authorized
  input.identity.role == "hermes-builder"
  input.tool in {"get_file_contents", "get_repository_tree", "search_code", "actions_get", "actions_list", "get_job_logs"}
}

allow if {
  base_authorized
  input.identity.role == "hermes-builder"
  input.tool == "create_branch"
  branch := target_branch(input.args)
  branch_allowed(branch)
  nonempty(input.args, "sha")
}

allow if {
  base_authorized
  input.identity.role == "hermes-builder"
  input.tool == "push_files"
  branch := target_branch(input.args)
  branch_allowed(branch)
  files := object.get(input.args, "files", [])
  count(files) > 0
  push_file_paths_allowed(files)
  nonempty(input.args, "message")
}

allow if {
  base_authorized
  input.identity.role == "hermes-builder"
  input.tool == "create_pull_request"
  head := target_branch(input.args)
  branch_allowed(head)
  base := base_branch(input.args)
  protected_base_allowed(base)
  nonempty(input.args, "title")
}

allow if {
  base_authorized
  input.identity.role == "hermes-builder"
  input.tool == "actions_run_trigger"
  branch := target_branch(input.args)
  branch_allowed(branch)
  nonempty(input.args, "workflow_id")
}

allow if {
  base_authorized
  input.identity.role == "hermes-reviewer"
  not reviewer_mutations[input.tool]
}

allow if {
  base_authorized
  input.identity.role == "hermes-reviewer"
  reviewer_mutations[input.tool]
  input.args.independence_verified == true
  nonempty(input.args, "issue_number")
  nonempty(input.args, "body")
}

allow if {
  base_authorized
  input.identity.role == "hermes-release"
}

allow if {
  base_authorized
  input.identity.role == "hermes-incident"
  not incident_mutations[input.tool]
}

allow if {
  base_authorized
  input.identity.role == "hermes-incident"
  incident_mutations[input.tool]
  nonempty(input.args, "issue_number")
  nonempty(input.args, "body")
}

allow if {
  base_authorized
  input.identity.role == "hermes-learning"
  not learning_mutations[input.tool]
}

allow if {
  base_authorized
  input.identity.role == "hermes-learning"
  input.tool == "add_issue_comment"
  nonempty(input.args, "issue_number")
  nonempty(input.args, "body")
}

allow if {
  base_authorized
  input.identity.role == "hermes-learning"
  input.tool == "issue_write"
  nonempty(input.args, "title")
  nonempty(input.args, "body")
}

decision := {
  "allow": allow,
  "role": input.identity.role,
  "tool": input.tool,
  "jti": input.identity.jti,
}
