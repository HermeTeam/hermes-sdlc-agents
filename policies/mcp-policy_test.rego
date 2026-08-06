package hermes.sdlc.repository_mcp_test

import rego.v1
import data.hermes.sdlc.repository_mcp

identity(role) := {
  "active": true,
  "aud": "git-provider-mcp",
  "role": role,
  "sub": sprintf("test/%s", [role]),
  "jti": sprintf("jti-%s", [role]),
  "exp": 9999999999,
}

test_planner_read_allowed if {
    repository_mcp.allow with input as {
    "identity": identity("hermes-planner"),
    "tool": "requirements_get",
    "args": {"id": "REQ-1"},
  }
}

test_planner_deployment_denied if {
    not repository_mcp.allow with input as {
    "identity": identity("hermes-planner"),
    "tool": "deployment_promote",
    "args": {},
  }
}

test_builder_task_branch_allowed if {
    repository_mcp.allow with input as {
    "identity": identity("hermes-builder"),
    "tool": "repo_create_task_branch",
    "args": {
      "work_item_id": "REQ-1",
      "repository_id": "service-a",
      "task_branch": "agent/REQ-1-change",
      "expected_base_sha": "sha-base",
      "idempotency_key": "idem-1",
    },
  }
}

test_builder_apply_patch_allowed if {
    repository_mcp.allow with input as {
    "identity": identity("hermes-builder"),
    "tool": "repo_apply_patch",
    "args": {
      "work_item_id": "REQ-1",
      "repository_id": "service-a",
      "task_branch": "agent/REQ-1-change",
      "expected_base_sha": "sha-base",
      "expected_head_sha": "sha-head",
      "idempotency_key": "idem-1b",
    },
  }
}

test_builder_main_denied if {
    not repository_mcp.allow with input as {
    "identity": identity("hermes-builder"),
    "tool": "repo_create_task_branch",
    "args": {
      "work_item_id": "REQ-1",
      "repository_id": "service-a",
      "task_branch": "main",
      "expected_base_sha": "sha-base",
      "idempotency_key": "idem-2",
    },
  }
}

test_reviewer_write_requires_independence if {
    not repository_mcp.allow with input as {
    "identity": identity("hermes-reviewer"),
    "tool": "repo_approve_change_request",
    "args": {"idempotency_key": "idem-3", "independence_verified": false},
  }
}

test_release_promote_allowed_with_preconditions if {
    repository_mcp.allow with input as {
    "identity": identity("hermes-release"),
    "tool": "deployment_promote",
    "args": {
      "candidate_id": "rc-1",
      "expected_revision": "sha256:abc",
      "stage": "canary-10",
      "policy_evaluation_id": "eval-1",
      "idempotency_key": "idem-4",
    },
  }
}

test_release_promote_missing_policy_denied if {
    not repository_mcp.allow with input as {
    "identity": identity("hermes-release"),
    "tool": "deployment_promote",
    "args": {
      "candidate_id": "rc-1",
      "expected_revision": "sha256:abc",
      "stage": "canary-10",
      "idempotency_key": "idem-5",
    },
  }
}

test_incident_flag_disable_allowed if {
    repository_mcp.allow with input as {
    "identity": identity("hermes-incident"),
    "tool": "flags_disable",
    "args": {
      "incident_id": "INC-1",
      "expected_version": "7",
      "target_state": "disabled",
      "idempotency_key": "idem-6",
    },
  }
}

test_incident_flag_enable_denied if {
  not repository_mcp.allow with input as {
    "identity": identity("hermes-incident"),
    "tool": "flags_disable",
    "args": {
      "incident_id": "INC-1",
      "expected_version": "7",
      "target_state": "enabled",
      "idempotency_key": "idem-7",
    },
  }
}

test_learning_activation_denied if {
  not repository_mcp.allow with input as {
    "identity": identity("hermes-learning"),
    "tool": "skills_activate",
    "args": {},
  }
}
