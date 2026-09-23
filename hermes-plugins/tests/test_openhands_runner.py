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

    def test_discovers_only_regular_agent_skill_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "skills"
            root.mkdir()
            good = root / "python-testing"
            good.mkdir()
            (good / "SKILL.md").write_text("---\nname: python-testing\n---\n", encoding="utf-8")
            missing = root / "missing-skill-file"
            missing.mkdir()
            outside = Path(tmp) / "outside"
            outside.mkdir()
            (outside / "SKILL.md").write_text("outside", encoding="utf-8")
            (root / "linked-skill").symlink_to(outside, target_is_directory=True)
            bad_name = root / "bad name"
            bad_name.mkdir()
            (bad_name / "SKILL.md").write_text("bad", encoding="utf-8")

            discovered = runner.discover_shared_skills(root)
            self.assertEqual(discovered, {"python-testing": good.resolve()})

    def test_discover_shared_skills_rejects_symlinked_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            skill = source / "safe-skill"
            skill.mkdir()
            (skill / "SKILL.md").write_text("---\nname: safe-skill\n---\n", encoding="utf-8")
            linked_root = Path(tmp) / "linked-root"
            linked_root.symlink_to(source, target_is_directory=True)

            with self.assertRaises(RuntimeError):
                runner.discover_shared_skills(linked_root)

    def test_prepare_shared_skills_materializes_user_skill_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "skills"
            skill = root / "rlm-roec-context-reasoning"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: rlm-roec-context-reasoning\n---\n", encoding="utf-8")
            home = Path(tmp) / "home"

            prepared = runner.prepare_shared_skills(home, root)
            link = home / ".openhands" / "skills" / "rlm-roec-context-reasoning"
            self.assertEqual(prepared, {"rlm-roec-context-reasoning": skill.resolve()})
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), skill.resolve())
            self.assertIsNone(runner.verify_shared_skills(home, prepared))

    def test_prepare_shared_skills_rejects_symlinked_openhands_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "skills"
            skill = root / "safe-skill"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: safe-skill\n---\n", encoding="utf-8")
            home = Path(tmp) / "home"
            home.mkdir()
            outside = Path(tmp) / "outside"
            outside.mkdir()
            (home / ".openhands").symlink_to(outside, target_is_directory=True)

            with self.assertRaises(ValueError):
                runner.prepare_shared_skills(home, root)

    def test_verify_shared_skills_detects_link_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "skills"
            skill = root / "safe-skill"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: safe-skill\n---\n", encoding="utf-8")
            home = Path(tmp) / "home"
            prepared = runner.prepare_shared_skills(home, root)
            link = home / ".openhands" / "skills" / "safe-skill"
            link.unlink()
            link.mkdir()

            violation = runner.verify_shared_skills(home, prepared)
            self.assertIn("link was replaced", violation or "")

    def test_openhands_overlay_has_no_provider_secret_names(self):
        overlay = (Path(__file__).parents[2] / "compose.openhands.yaml").read_text(encoding="utf-8")
        self.assertNotIn("GIT_PROVIDER_MCP_TOKEN", overlay)
        self.assertNotIn("ORCHESTRATOR_GITHUB_TOKEN", overlay)
        self.assertNotIn("GITHUB_APP_PRIVATE_KEY", overlay)
        self.assertIn("secrets/hermes-builder-openhands.env", overlay)
        self.assertIn("shared-skills:/opt/hermes-shared-skills:ro", overlay)
        self.assertIn("OPENHANDS_SHARED_SKILLS_ROOT: /opt/hermes-shared-skills/current", overlay)
        self.assertIn("skills-superset-sync:", overlay)
        self.assertIn("condition: service_completed_successfully", overlay)


if __name__ == "__main__":
    unittest.main()
