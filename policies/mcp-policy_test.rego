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

repo := {"owner": "test-project", "repo": "test-project", "default_branch": "main"}
protected_paths := ["policies/", ".github/workflows/"]

scoped_args(extra) := object.union({"owner": "test-project", "repo": "test-project"}, extra)

test_planner_read_allowed if {
  repository_mcp.allow with input as {
    "identity": identity("hermes-planner"),
    "repository": repo,
    "tool": "get_file_contents",
    "args": scoped_args({"path": "README.md", "ref": "main"}),
  }
}

test_provider_tool_not_in_allowlist_denied if {
  not repository_mcp.allow with input as {
    "identity": identity("hermes-planner"),
    "repository": repo,
    "tool": "push_files",
    "args": scoped_args({"branch": "agent/REQ-1-change", "files": []}),
  }
}

test_project_manager_create_issue_allowed if {
  repository_mcp.allow with input as {
    "identity": identity("hermes-project-manager"),
    "repository": repo,
    "tool": "create_issue",
    "args": scoped_args({"title": "PM status", "body": "Prepared project status"}),
  }
}

test_project_manager_push_denied if {
  not repository_mcp.allow with input as {
    "identity": identity("hermes-project-manager"),
    "repository": repo,
    "tool": "push_files",
    "args": scoped_args({"branch": "agent/REQ-1-change", "files": []}),
  }
}

test_wrong_repository_denied if {
  not repository_mcp.allow with input as {
    "identity": identity("hermes-planner"),
    "repository": repo,
    "tool": "get_file_contents",
    "args": {"owner": "other", "repo": "test-project", "path": "README.md"},
  }
}

test_builder_create_branch_allowed_for_agent_branch if {
  repository_mcp.allow with input as {
    "identity": identity("hermes-builder"),
    "repository": repo,
    "tool": "create_branch",
    "args": scoped_args({"branch": "agent/REQ-1-change", "sha": "sha-base"}),
  }
}

test_builder_create_branch_denied_for_main if {
  not repository_mcp.allow with input as {
    "identity": identity("hermes-builder"),
    "repository": repo,
    "tool": "create_branch",
    "args": scoped_args({"branch": "main", "sha": "sha-base"}),
  }
}

test_builder_push_files_allowed_for_agent_branch if {
  repository_mcp.allow with input as {
    "identity": identity("hermes-builder"),
    "repository": repo,
    "protected_paths": protected_paths,
    "tool": "push_files",
    "args": scoped_args({
      "branch": "agent/REQ-1-change",
      "message": "Implement REQ-1",
      "files": [{"path": "src/service.py", "content": "print('ok')\n"}],
    }),
  }
}

test_builder_push_files_denied_for_main if {
  not repository_mcp.allow with input as {
    "identity": identity("hermes-builder"),
    "repository": repo,
    "protected_paths": protected_paths,
    "tool": "push_files",
    "args": scoped_args({
      "branch": "main",
      "message": "bad",
      "files": [{"path": "src/service.py", "content": "bad\n"}],
    }),
  }
}

test_builder_push_files_denied_for_release_branch if {
  not repository_mcp.allow with input as {
    "identity": identity("hermes-builder"),
    "repository": repo,
    "protected_paths": protected_paths,
    "tool": "push_files",
    "args": scoped_args({
      "branch": "release/1.0",
      "message": "bad",
      "files": [{"path": "src/service.py", "content": "bad\n"}],
    }),
  }
}

test_builder_push_files_denied_for_protected_path if {
  not repository_mcp.allow with input as {
    "identity": identity("hermes-builder"),
    "repository": repo,
    "protected_paths": protected_paths,
    "tool": "push_files",
    "args": scoped_args({
      "branch": "agent/REQ-1-change",
      "message": "bad",
      "files": [{"path": ".github/workflows/ci.yml", "content": "bad\n"}],
    }),
  }
}

test_builder_create_pull_request_allowed_from_agent_to_protected_base if {
  repository_mcp.allow with input as {
    "identity": identity("hermes-builder"),
    "repository": repo,
    "tool": "create_pull_request",
    "args": scoped_args({"head": "agent/REQ-1-change", "base": "main", "title": "REQ-1"}),
  }
}

test_builder_create_pull_request_denied_from_main if {
  not repository_mcp.allow with input as {
    "identity": identity("hermes-builder"),
    "repository": repo,
    "tool": "create_pull_request",
    "args": scoped_args({"head": "main", "base": "main", "title": "bad"}),
  }
}

test_reviewer_comment_requires_independence if {
  not repository_mcp.allow with input as {
    "identity": identity("hermes-reviewer"),
    "repository": repo,
    "tool": "add_issue_comment",
    "args": scoped_args({"issue_number": 1, "body": "LGTM", "independence_verified": false}),
  }
}

test_reviewer_comment_allowed_with_independence if {
  repository_mcp.allow with input as {
    "identity": identity("hermes-reviewer"),
    "repository": repo,
    "tool": "add_issue_comment",
    "args": scoped_args({"issue_number": 1, "body": "Finding", "independence_verified": true}),
  }
}

test_merge_tool_denied if {
  not repository_mcp.allow with input as {
    "identity": identity("hermes-builder"),
    "repository": repo,
    "tool": "merge_pull_request",
    "args": scoped_args({"pull_number": 1}),
  }
}

test_incident_comment_allowed if {
  repository_mcp.allow with input as {
    "identity": identity("hermes-incident"),
    "repository": repo,
    "tool": "add_issue_comment",
    "args": scoped_args({"issue_number": 2, "body": "Incident update"}),
  }
}

test_learning_create_issue_allowed if {
  repository_mcp.allow with input as {
    "identity": identity("hermes-learning"),
    "repository": repo,
    "tool": "create_issue",
    "args": scoped_args({"title": "Learning proposal", "body": "Proposal details"}),
  }
}
