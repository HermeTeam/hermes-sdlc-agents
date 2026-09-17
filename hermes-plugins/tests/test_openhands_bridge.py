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

    def test_requires_dedicated_llm_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_root = module.WORKSPACE_ROOT
            module.WORKSPACE_ROOT = Path(tmp)
            try:
                with patch.dict(
                    os.environ,
                    {"ORCHESTRATOR_ROLE": "builder", "BUILDER_OPENHANDS_ENABLED": "true"},
                    clear=True,
                ), patch.object(module.shutil, "which", return_value="/usr/local/bin/openhands"):
                    payload = json.loads(module.delegate({"task": "fix it"}))
                self.assertFalse(payload["success"])
                self.assertIn("BUILDER_OPENHANDS_LLM_MODEL", payload["error"])
            finally:
                module.WORKSPACE_ROOT = old_root

    def test_sanitized_env_does_not_forward_provider_credentials(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "BUILDER_OPENHANDS_LLM_MODEL": "openrouter/test/model",
                "BUILDER_OPENHANDS_LLM_API_KEY": "dedicated-key",
                "BUILDER_OPENHANDS_LLM_BASE_URL": "https://example.invalid/v1",
                "GIT_PROVIDER_MCP_TOKEN": "must-not-leak",
                "ORCHESTRATOR_GITHUB_TOKEN": "must-not-leak-either",
                "PATH": "/usr/local/bin:/usr/bin:/bin",
            },
            clear=True,
        ):
            workspace = Path(tmp)
            env = module._openhands_env(workspace)
            self.assertEqual(env["LLM_API_KEY"], "dedicated-key")
            self.assertNotIn("GIT_PROVIDER_MCP_TOKEN", env)
            self.assertNotIn("ORCHESTRATOR_GITHUB_TOKEN", env)
            self.assertNotIn("OPENAI_API_KEY", env)

    def test_workspace_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_root = module.WORKSPACE_ROOT
            module.WORKSPACE_ROOT = Path(tmp)
            try:
                with self.assertRaises(ValueError):
                    module._safe_workspace("../escape")
            finally:
                module.WORKSPACE_ROOT = old_root


if __name__ == "__main__":
    unittest.main()
