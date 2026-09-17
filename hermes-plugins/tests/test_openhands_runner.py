import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


RUNNER = Path(__file__).parents[2] / "openhands_runner" / "server.py"
spec = importlib.util.spec_from_file_location("hermeteam_openhands_runner", RUNNER)
runner = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(runner)


class OpenHandsRunnerTests(unittest.TestCase):
    def test_child_environment_is_minimal(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "BUILDER_OPENHANDS_LLM_MODEL": "openrouter/test/model",
                "BUILDER_OPENHANDS_LLM_API_KEY": "dedicated-key",
                "BUILDER_OPENHANDS_LLM_BASE_URL": "https://example.invalid/v1",
                "GIT_PROVIDER_MCP_TOKEN": "must-not-leak",
                "ORCHESTRATOR_GITHUB_TOKEN": "must-not-leak-either",
                "OPENAI_API_KEY": "must-not-leak-either",
                "PATH": "/usr/local/bin:/usr/bin:/bin",
            },
            clear=True,
        ):
            workspace = Path(tmp)
            (workspace / ".git" / "info").mkdir(parents=True)
            env = runner.child_env(workspace)
            self.assertEqual(env["LLM_API_KEY"], "dedicated-key")
            self.assertNotIn("GIT_PROVIDER_MCP_TOKEN", env)
            self.assertNotIn("ORCHESTRATOR_GITHUB_TOKEN", env)
            self.assertNotIn("OPENAI_API_KEY", env)

    def test_runner_requires_dedicated_model_credentials(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            workspace = Path(tmp)
            (workspace / ".git" / "info").mkdir(parents=True)
            with self.assertRaises(ValueError):
                runner.child_env(workspace)

    def test_workspace_cannot_escape_runner_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_root = runner.WORKSPACE_ROOT
            runner.WORKSPACE_ROOT = Path(tmp)
            try:
                with self.assertRaises(ValueError):
                    runner.safe_workspace("../escape")
            finally:
                runner.WORKSPACE_ROOT = old_root

    def test_openhands_overlay_has_no_provider_secret_names(self):
        overlay = (Path(__file__).parents[2] / "compose.openhands.yaml").read_text(encoding="utf-8")
        self.assertNotIn("GIT_PROVIDER_MCP_TOKEN", overlay)
        self.assertNotIn("ORCHESTRATOR_GITHUB_TOKEN", overlay)
        self.assertNotIn("GITHUB_APP_PRIVATE_KEY", overlay)
        self.assertIn("secrets/hermes-builder-openhands.env", overlay)


if __name__ == "__main__":
    unittest.main()
