"""Explicit default-deny GitHub role authority contracts.

This module is a preparatory enforcement component for the all-role Gateway.
Do not treat this mapping as active enforcement until every AI role and
orchestrator route is moved behind the authenticated Gateway boundary.
"""
from __future__ import annotations

from typing import Any, Mapping

from .authority import (
    ActionSpec,
    AuthorityDenied,
    BUILDER_ACTIONS,
    InvocationContext,
    builder_invocation_context,
    canonical_args_hash,
)
from .models import RiskCategory


_READ_ACTIONS: dict[str, ActionSpec] = {
    "get_file_contents": ActionSpec("repository.file.read", RiskCategory.LOW, {"contents": "read"}),
    "get_repository_tree": ActionSpec("repository.tree.read", RiskCategory.LOW, {"contents": "read"}),
    "search_code": ActionSpec("repository.code.search", RiskCategory.LOW, {"contents": "read"}),
    "issue_read": ActionSpec("repository.issue.read", RiskCategory.LOW, {"issues": "read"}),
    "list_issues": ActionSpec("repository.issues.list", RiskCategory.LOW, {"issues": "read"}),
    "pull_request_read": ActionSpec("repository.pull_request.read", RiskCategory.LOW, {"pull_requests": "read"}),
    "actions_get": ActionSpec("ci.workflow.read", RiskCategory.LOW, {"actions": "read"}),
    "actions_list": ActionSpec("ci.workflow.read", RiskCategory.LOW, {"actions": "read"}),
    "get_job_logs": ActionSpec("ci.logs.read", RiskCategory.LOW, {"actions": "read"}),
}
_COMMENT_ACTION = ActionSpec(
    "repository.issue.comment",
    # Until commitment changes, incident context and learning approval can
    # be independently established, every role comment is human-approved.
    RiskCategory.HIGH,
    {"issues": "write"},
    True,
)
_ROLE_TOOL_NAMES: dict[str, frozenset[str]] = {
    "planner": frozenset({
        "get_file_contents", "get_repository_tree", "search_code", "issue_read", "list_issues"
    }),
    "project-manager": frozenset({
        "get_file_contents", "get_repository_tree", "search_code",
        "issue_read", "list_issues", "add_issue_comment",
    }),
    "reviewer": frozenset({
        "pull_request_read", "get_file_contents",
        "actions_get", "actions_list", "get_job_logs", "add_issue_comment",
    }),
    "release": frozenset({"actions_get", "actions_list"}),
    "incident": frozenset({"issue_read", "list_issues", "add_issue_comment"}),
    "learning": frozenset({"issue_read", "list_issues", "add_issue_comment"}),
}


def role_action_spec(role: str, tool_name: str) -> ActionSpec:
    """Minimal capability for a role; unknown roles/tools always fail closed.

    Deliberately excludes generic issue_write pending an operation-specific
    capability breakdown and verification of tool argument semantics.
    """
    normalized = role.removeprefix("hermes-")
    if normalized == "builder":
        spec = BUILDER_ACTIONS.get(tool_name)
    elif tool_name in _ROLE_TOOL_NAMES.get(normalized, frozenset()):
        spec = _COMMENT_ACTION if tool_name == "add_issue_comment" else _READ_ACTIONS.get(tool_name)
    else:
        spec = None
    if spec is None:
        raise AuthorityDenied("tool_not_in_role_authority_map")
    return spec


def role_invocation_context(
    *,
    role: str,
    run_id: str,
    tool_name: str,
    arguments: Mapping[str, Any],
    configured_repository: str,
    default_branch: str,
    protected_patterns: tuple[str, ...],
) -> InvocationContext:
    """Derive a bounded, auditable invocation from validated role + tool inputs.

    Caller MUST independently authenticate the role before calling this function.
    A caller-controlled role header alone is not sufficient authentication.
    """
    normalized = role.removeprefix("hermes-")
    if normalized == "builder":
        return builder_invocation_context(
            agent_id="hermes-builder",
            run_id=run_id,
            tool_name=tool_name,
            arguments=arguments,
            configured_repository=configured_repository,
            default_branch=default_branch,
            protected_patterns=protected_patterns,
        )

    spec = role_action_spec(normalized, tool_name)
    owner = arguments.get("owner")
    repo = arguments.get("repo")
    if not isinstance(owner, str) or not owner or not isinstance(repo, str) or not repo:
        raise AuthorityDenied("owner_and_repo_are_required")
    repository = owner + "/" + repo
    if repository != configured_repository:
        raise AuthorityDenied("repository_out_of_scope")

    if tool_name == "add_issue_comment":
        issue_number = arguments.get("issue_number")
        body = arguments.get("body")
        if (
            not isinstance(issue_number, int)
            or isinstance(issue_number, bool)
            or issue_number <= 0
            or not isinstance(body, str)
            or not body.strip()
            or len(body) > 10000
        ):
            raise AuthorityDenied("issue_comment_requires_bounded_issue_number_and_body")

    return InvocationContext(
        agent_id="hermes-" + normalized,
        role=normalized,
        run_id=run_id,
        tool_id="github:" + tool_name,
        capability=spec.capability,
        category=spec.category,
        repository=repository,
        branch=None,
        paths=(),
        args_hash=canonical_args_hash(tool_name, arguments),
        github_permissions=dict(spec.github_permissions),
    )
