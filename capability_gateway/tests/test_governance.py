from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from capability_gateway.governance import GovernanceStore
from capability_gateway.models import RiskCategory


class GovernanceStoreTests(unittest.TestCase):
    def test_emergency_stop_persists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            store = GovernanceStore(path)
            store.set_emergency_stop(True)
            self.assertTrue(GovernanceStore(path).snapshot().emergency_stop)

    def test_one_shot_grant_is_consumed_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = GovernanceStore(Path(directory) / "state.sqlite3")
            store.grant_once("req-1", "server:tool")
            self.assertTrue(store.has_unconsumed_once("req-1", "server:tool"))
            self.assertTrue(store.consume_once("req-1", "server:tool"))
            self.assertFalse(store.consume_once("req-1", "server:tool"))

    def test_tool_exception_and_capability_override_persist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            store = GovernanceStore(path)
            store.add_tool_exception("server:tool")
            store.set_capability_override("issue.create", RiskCategory.LOW)
            snapshot = GovernanceStore(path).snapshot()
            self.assertIn("server:tool", snapshot.tool_exceptions)
            self.assertEqual(snapshot.capability_overrides["issue.create"], RiskCategory.LOW)


if __name__ == "__main__":
    unittest.main()
