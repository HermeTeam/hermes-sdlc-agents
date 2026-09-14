from __future__ import annotations

import unittest

from capability_gateway.core import assess_risk, mark_dominated, resolve
from capability_gateway.models import RankedTool, RiskCategory, ToolDescriptor, ToolSemantics


def candidate(
    name: str,
    capability: str,
    *,
    fit: float,
    read: bool = False,
    write: bool = False,
    destructive: bool = False,
    egress: bool = False,
    credential_access: bool = False,
    arbitrary_execution: bool = False,
    open_world: bool = False,
) -> RankedTool:
    tool = ToolDescriptor("test/server", name, name)
    semantics = ToolSemantics(
        canonical_capability=capability,
        read=read,
        write=write,
        destructive=destructive,
        egress=egress,
        credential_access=credential_access,
        arbitrary_execution=arbitrary_execution,
        open_world=open_world,
        rationale="test",
        confidence=1.0,
    )
    return RankedTool(tool, assess_risk(tool, semantics), fit, False)


class ResolverTests(unittest.TestCase):
    def test_read_only_tool_dominates_shell_for_read_intent(self) -> None:
        safe = candidate("read_file", "repository.file.read", fit=0.95, read=True)
        shell = candidate(
            "shell_exec",
            "shell.execute",
            fit=0.98,
            read=True,
            write=True,
            destructive=True,
            egress=True,
            credential_access=True,
            arbitrary_execution=True,
            open_world=True,
        )
        marked = mark_dominated((safe, shell))
        self.assertFalse(marked[0].dominated)
        self.assertTrue(marked[1].dominated)

    def test_over_limit_requested_tool_requires_human_approval(self) -> None:
        safe = candidate("read_file", "repository.file.read", fit=0.95, read=True)
        shell = candidate(
            "shell_exec",
            "shell.execute",
            fit=0.99,
            read=True,
            write=True,
            destructive=True,
            arbitrary_execution=True,
        )
        result = resolve(
            intent="read the README",
            candidates=(safe, shell),
            max_auto_category=RiskCategory.MEDIUM,
            requested_tool_id=shell.tool.tool_id,
        )
        self.assertIsNone(result.selected)
        self.assertIsNotNone(result.approval_required)
        self.assertEqual(result.approval_required.recommended_tool_id, safe.tool.tool_id)

    def test_tool_exception_does_not_restore_dominated_tool(self) -> None:
        safe = candidate("read_file", "repository.file.read", fit=0.95, read=True)
        shell = candidate(
            "shell_exec",
            "shell.execute",
            fit=0.98,
            read=True,
            write=True,
            destructive=True,
            arbitrary_execution=True,
        )
        result = resolve(
            intent="read the README",
            candidates=(safe, shell),
            max_auto_category=RiskCategory.MEDIUM,
            exception_tools=frozenset({shell.tool.tool_id}),
        )
        self.assertEqual(result.selected.tool.tool_id, safe.tool.tool_id)
        self.assertTrue(any(item.tool.tool_id == shell.tool.tool_id for item in result.filtered_tools))

    def test_emergency_stop_hides_every_tool(self) -> None:
        safe = candidate("read_file", "repository.file.read", fit=1.0, read=True)
        result = resolve(
            intent="read",
            candidates=(safe,),
            max_auto_category=RiskCategory.CRITICAL,
            emergency_stop=True,
        )
        self.assertTrue(result.emergency_stop)
        self.assertIsNone(result.selected)
        self.assertEqual(result.visible_tools, ())

    def test_capability_override_changes_enforcement_category_not_base_assessment(self) -> None:
        write = candidate("create_issue", "issue.create", fit=1.0, write=True, egress=True)
        original = write.assessment.category
        result = resolve(
            intent="create issue",
            candidates=(write,),
            max_auto_category=RiskCategory.LOW,
            capability_overrides={"issue.create": RiskCategory.LOW},
        )
        self.assertEqual(result.selected.tool.tool_id, write.tool.tool_id)
        self.assertEqual(write.assessment.category, original)


if __name__ == "__main__":
    unittest.main()
