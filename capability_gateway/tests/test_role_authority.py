from __future__ import annotations

import unittest

from capability_gateway.authority import AuthorityDenied
from capability_gateway.models import RiskCategory
from capability_gateway.role_authority import role_action_spec, role_invocation_context


REPO = "HermeTeam/e2e-sandbox"


def invoke(role: str, tool: str, args: dict[str, object]):
    return role_invocation_context(
        role=role,
        run_id="test-run",
        tool_name=tool,
        arguments=args,
        configured_repository=REPO,
        default_branch="main",
        protected_patterns=(".github/workflows/**", "policies/**"),
    )


class RoleAuthorityContracts(unittest.TestCase):
    """The new role matrix must reject privilege escalation before token mint."""

    def test_every_role_has_specific_minimal_read_permissions(self):
        candidates = (
            ("planner", "issue_read", {"issues": "read"}),
            ("project-manager", "get_file_contents", {"contents": "read"}),
            ("reviewer", "pull_request_read", {"pull_requests": "read"}),
            ("release", "actions_list", {"actions": "read"}),
            ("incident", "list_issues", {"issues": "read"}),
            ("learning", "issue_read", {"issues": "read"}),
            ("builder", "get_file_contents", {"contents": "read"}),
        )
        for role, tool, expected in candidates:
            with self.subTest(role=role):
                ctx = invoke(role, tool, {"owner": "HermeTeam", "repo": "e2e-sandbox"})
                self.assertEqual(ctx.github_permissions, expected)
                self.assertEqual(ctx.role, role)
                self.assertEqual(ctx.repository, REPO)

    def test_unknown_role_or_tool_is_denied(self):
        for role, tool in (
            ("release", "push_files"),
            ("planner", "add_issue_comment"),
            ("incident", "actions_run_trigger"),
            ("learning", "issue_write"),
            ("project-manager", "issue_write"),
            ("rogue-agent", "issue_read"),
            ("reviewer", "merge_pull_request"),
        ):
            with self.subTest(role=role, tool=tool):
                with self.assertRaises(AuthorityDenied):
                    invoke(role, tool, {"owner": "HermeTeam", "repo": "e2e-sandbox"})

    def test_cross_repository_denied(self):
        with self.assertRaisesRegex(AuthorityDenied, "repository_out_of_scope"):
            invoke("planner", "issue_read", {"owner": "OtherOrg", "repo": "private"})

    def test_comment_must_be_bounded_and_targets_exact_issue(self):
        args = {"owner": "HermeTeam", "repo": "e2e-sandbox", "issue_number": 23, "body": "Verified."}
        ctx = invoke("incident", "add_issue_comment", args)
        self.assertEqual(ctx.github_permissions, {"issues": "write"})
        self.assertEqual(ctx.category, RiskCategory.HIGH)
        mutated = {**args, "body": "Modified"}
        self.assertNotEqual(ctx.args_hash, invoke("incident", "add_issue_comment", mutated).args_hash)
        for invalid in (
            {**args, "issue_number": True},
            {**args, "issue_number": 0},
            {**args, "issue_number": "23"},
            {**args, "body": "   "},
            {**args, "body": "x" * 10001},
        ):
            with self.subTest(invalid=repr(invalid)[:40]):
                with self.assertRaises(AuthorityDenied):
                    invoke("incident", "add_issue_comment", invalid)

    def test_builder_branch_and_protected_paths_are_unchanged(self):
        args = {
            "owner": "HermeTeam", "repo": "e2e-sandbox", "branch": "main",
            "files": [{"path": "README.md", "content": "test"}],
        }
        with self.assertRaisesRegex(AuthorityDenied, "builder_branch_must_use_agent_prefix"):
            invoke("builder", "push_files", args)
        args["branch"] = "agent/e2e-test"
        args["files"] = [{"path": "policies/roles.yaml", "content": "deny:false"}]
        with self.assertRaisesRegex(AuthorityDenied, "protected_path"):
            invoke("builder", "push_files", args)

    def test_role_action_spec_never_infers_write_permission_from_read(self):
        self.assertEqual(
            role_action_spec("hermes-release", "actions_get").github_permissions,
            {"actions": "read"},
        )
        with self.assertRaises(AuthorityDenied):
            role_action_spec("hermes-release", "actions_run_trigger")


if __name__ == "__main__":
    unittest.main()
