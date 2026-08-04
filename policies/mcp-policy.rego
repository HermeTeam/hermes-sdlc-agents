package hermes.sdlc.mcp

import rego.v1

default allow := false

base_authorized if {
  input.identity.active == true
  input.identity.aud == "sdlc-mcp"
  time.now_ns() < input.identity.exp * 1000000000
  input.tool in data.spec.roles[input.identity.role].allowTools
}

planner_mutations := {"spec_create", "spec_update", "plan_create", "plan_update"}
builder_branch_mutations := {
  "repo_create_task_branch", "repo_push_task_branch", "repo_create_pull_request",
}
builder_other_mutations := {"repo_update_pull_request_description"}
reviewer_mutations := {
  "repo_add_review_comment", "repo_submit_review", "repo_request_changes",
  "repo_approve_pull_request",
}
release_mutations := {"deployment_promote", "deployment_abort"}
incident_mutations := {"incident_update_timeline", "flags_disable", "runbooks_execute_approved"}
learning_mutations := {"proposal_create", "proposal_update", "proposal_attach_diff"}

nonempty(args, key) if {
  object.get(args, key, "") != ""
}

allow if {
  base_authorized
  input.identity.role == "hermes-planner"
  not planner_mutations[input.tool]
}

allow if {
  base_authorized
  input.identity.role == "hermes-planner"
  planner_mutations[input.tool]
  nonempty(input.args, "expected_version")
  nonempty(input.args, "idempotency_key")
}

allow if {
  base_authorized
  input.identity.role == "hermes-builder"
  not builder_branch_mutations[input.tool]
  not builder_other_mutations[input.tool]
}

allow if {
  base_authorized
  input.identity.role == "hermes-builder"
  builder_branch_mutations[input.tool]
  branch := object.get(input.args, "branch", "")
  startswith(branch, "agent/")
  branch != "main"
  branch != "master"
  not startswith(branch, "release/")
  nonempty(input.args, "expected_version")
  nonempty(input.args, "idempotency_key")
}

allow if {
  base_authorized
  input.identity.role == "hermes-builder"
  builder_other_mutations[input.tool]
  nonempty(input.args, "expected_version")
  nonempty(input.args, "idempotency_key")
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
  nonempty(input.args, "expected_version")
  nonempty(input.args, "idempotency_key")
}

allow if {
  base_authorized
  input.identity.role == "hermes-release"
  not release_mutations[input.tool]
}

allow if {
  base_authorized
  input.identity.role == "hermes-release"
  release_mutations[input.tool]
  nonempty(input.args, "candidate_id")
  nonempty(input.args, "expected_revision")
  nonempty(input.args, "stage")
  nonempty(input.args, "policy_evaluation_id")
  nonempty(input.args, "idempotency_key")
}

allow if {
  base_authorized
  input.identity.role == "hermes-incident"
  not incident_mutations[input.tool]
}

allow if {
  base_authorized
  input.identity.role == "hermes-incident"
  input.tool == "incident_update_timeline"
  nonempty(input.args, "incident_id")
  nonempty(input.args, "expected_version")
  nonempty(input.args, "idempotency_key")
}

allow if {
  base_authorized
  input.identity.role == "hermes-incident"
  input.tool == "flags_disable"
  nonempty(input.args, "incident_id")
  nonempty(input.args, "expected_version")
  nonempty(input.args, "idempotency_key")
  input.args.target_state == "disabled"
}

allow if {
  base_authorized
  input.identity.role == "hermes-incident"
  input.tool == "runbooks_execute_approved"
  nonempty(input.args, "incident_id")
  nonempty(input.args, "runbook_version")
  input.args.approval_state == "approved"
  nonempty(input.args, "idempotency_key")
}

allow if {
  base_authorized
  input.identity.role == "hermes-learning"
  not learning_mutations[input.tool]
}

allow if {
  base_authorized
  input.identity.role == "hermes-learning"
  learning_mutations[input.tool]
  input.args.destination == "human-review-queue"
  nonempty(input.args, "expected_version")
  nonempty(input.args, "idempotency_key")
}

decision := {
  "allow": allow,
  "role": input.identity.role,
  "tool": input.tool,
  "jti": input.identity.jti,
}
