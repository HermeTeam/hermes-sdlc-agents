from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import unittest

PLUGIN_PATH = Path(__file__).resolve().parents[1] / "hermeteam-intent-action-gate" / "__init__.py"
spec = importlib.util.spec_from_file_location("hermeteam_intent_action_gate", PLUGIN_PATH)
plugin = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(plugin)


class FakeCtx:
    def __init__(self):
        self.hooks = {}

    def register_hook(self, name, fn):
        self.hooks[name] = fn


class IntentActionGateTests(unittest.TestCase):
    def setUp(self):
        plugin.PROPOSALS.clear()
        self.events = []
        self.original_emit = plugin.emit
        plugin.emit = self.events.append
        self.old_mode = os.environ.get("HERMETEAM_GATE_MODE")
        self.old_level = os.environ.get("HERMETEAM_GATE_BLOCK_LEVEL")
        os.environ["HERMETEAM_GATE_MODE"] = "shadow"
        os.environ["HERMETEAM_GATE_BLOCK_LEVEL"] = "critical"

    def tearDown(self):
        plugin.emit = self.original_emit
        for key, value in (
            ("HERMETEAM_GATE_MODE", self.old_mode),
            ("HERMETEAM_GATE_BLOCK_LEVEL", self.old_level),
        ):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_registers_expected_hooks(self):
        ctx = FakeCtx()
        plugin.register(ctx)
        self.assertEqual(
            set(ctx.hooks),
            {"pre_api_request", "post_api_request", "pre_tool_call", "post_tool_call"},
        )

    def test_risk_classification(self):
        self.assertEqual(plugin.classify_action("get_file_contents", {"path": "src/a.py"})[0], "low")
        self.assertEqual(plugin.classify_action("push_files", {"branch": "agent/REQ-1"})[0], "medium")
        self.assertEqual(plugin.classify_action("push_files", {"branch": "main"})[0], "high")
        self.assertEqual(plugin.classify_action("merge_pull_request", {"number": 4})[0], "critical")

    def test_sensitive_content_is_not_logged(self):
        value = plugin.bounded({"path": "src/a.py", "content": "super secret source", "token": "abc"})
        self.assertEqual(value["path"], "src/a.py")
        self.assertTrue(value["content"]["omitted"])
        self.assertTrue(value["token"]["omitted"])
        self.assertNotIn("super secret source", str(value))

    def test_model_proposal_matches_actual_tool_call(self):
        response = {
            "choices": [{
                "message": {
                    "tool_calls": [{
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "push_files",
                            "arguments": "{\"branch\":\"agent/REQ-1\",\"files\":[{\"path\":\"src/a.py\",\"content\":\"x\"}]}"
                        },
                    }]
                }
            }]
        }
        plugin.on_post_api_request(
            session_id="session-1", turn_id="turn-1", api_request_id="api-1", response=response
        )
        decision = plugin.on_pre_tool_call(
            session_id="session-1",
            turn_id="turn-1",
            api_request_id="api-1",
            tool_call_id="call-1",
            tool_name="push_files",
            args={"branch": "agent/REQ-1", "files": [{"path": "src/a.py", "content": "x"}]},
        )
        self.assertIsNone(decision)
        action = [e for e in self.events if e["event_type"] == "action.requested"][-1]
        self.assertTrue(action["matched_model_proposal"])
        self.assertFalse(action["proposal_mismatch"])
        self.assertEqual(action["decision"], "ALLOW_SHADOW")

    def test_enforce_blocks_critical_action(self):
        os.environ["HERMETEAM_GATE_MODE"] = "enforce"
        decision = plugin.on_pre_tool_call(
            session_id="session-2",
            tool_call_id="call-2",
            tool_name="merge_pull_request",
            args={"number": 7},
        )
        self.assertEqual(decision["action"], "block")
        event = self.events[-1]
        self.assertEqual(event["risk"], "critical")
        self.assertEqual(event["decision"], "DENY")

    def test_unmatched_mutation_is_raised_to_high(self):
        plugin.on_pre_tool_call(
            session_id="session-3",
            tool_call_id="call-3",
            tool_name="push_files",
            args={"branch": "agent/REQ-3", "files": [{"path": "src/b.py", "content": "x"}]},
        )
        event = self.events[-1]
        self.assertEqual(event["risk"], "high")
        self.assertIn("no_matching_model_proposal", event["reasons"])

    def test_llm_request_and_response_events(self):
        plugin.on_pre_api_request(
            session_id="s",
            turn_id="t",
            api_request_id="a",
            provider="custom",
            model="m",
            request={"messages": [{"role": "user", "content": "do secret thing"}]},
            message_count=1,
            tool_count=2,
        )
        plugin.on_post_api_request(
            session_id="s",
            turn_id="t",
            api_request_id="a",
            provider="custom",
            model="m",
            response={"choices": [{"message": {"content": "ok"}}]},
            finish_reason="stop",
            usage={"total_tokens": 12},
        )
        self.assertEqual(self.events[0]["event_type"], "llm.request")
        self.assertEqual(self.events[1]["event_type"], "llm.response")
        self.assertNotIn("do secret thing", str(self.events[0]))


if __name__ == "__main__":
    unittest.main()
