import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


PLUGIN = Path(__file__).parents[1] / "hermeteam-openhands-bridge" / "__init__.py"
spec = importlib.util.spec_from_file_location("hermeteam_openhands_bridge", PLUGIN)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


class OpenHandsBridgeTests(unittest.TestCase):
    def test_rejects_non_builder_role(self):
        with patch.dict(os.environ, {"ORCHESTRATOR_ROLE": "reviewer"}, clear=False):
            payload = json.loads(module.delegate({"task": "fix it"}))
        self.assertFalse(payload["success"])
        self.assertIn("builder role", payload["error"])

    def test_workspace_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_root = module.WORKSPACE_ROOT
            module.WORKSPACE_ROOT = Path(tmp)
            try:
                with self.assertRaises(ValueError):
                    module._safe_workspace("../escape")
            finally:
                module.WORKSPACE_ROOT = old_root

    def test_builder_delegation_calls_only_runner_socket(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_root = module.WORKSPACE_ROOT
            module.WORKSPACE_ROOT = Path(tmp)
            try:
                with patch.dict(
                    os.environ,
                    {"ORCHESTRATOR_ROLE": "builder", "BUILDER_OPENHANDS_ENABLED": "true"},
                    clear=False,
                ), patch.object(
                    module,
                    "_call_runner",
                    return_value={"success": True, "changed": [" M src/a.py"]},
                ) as call:
                    payload = json.loads(
                        module.delegate({"task": "fix it", "workspace": "work-1", "timeout_seconds": 60})
                    )
                self.assertTrue(payload["success"])
                self.assertEqual(payload["plugin_version"], module.PLUGIN_VERSION)
                request, timeout = call.call_args.args
                self.assertEqual(request["task"], "fix it")
                self.assertEqual(request["workspace"], "work-1")
                self.assertEqual(timeout, 60)
            finally:
                module.WORKSPACE_ROOT = old_root

    def test_missing_runner_socket_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_socket = module.SOCKET_PATH
            module.SOCKET_PATH = Path(tmp) / "missing.sock"
            try:
                with self.assertRaises(RuntimeError):
                    module._call_runner({"task": "fix"}, 30)
            finally:
                module.SOCKET_PATH = old_socket


if __name__ == "__main__":
    unittest.main()
