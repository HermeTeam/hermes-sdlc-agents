from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "verification" / "ai_agents.py"
spec = importlib.util.spec_from_file_location("hermeteam_ai_agents", MODULE_PATH)
ai_agents = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(ai_agents)


class AIAgentTests(unittest.TestCase):
    def test_parse_json_object_accepts_fenced_json(self) -> None:
        value = ai_agents.parse_json_object('''```json
{"verdict":"PASS","findings":[],"coverage_gaps":[]}
```''')
        self.assertEqual(value["verdict"], "PASS")

    def test_judge_never_calls_model_when_hard_failure_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "evidence.json"
            output = root / "judge.json"
            evidence.write_text(
                json.dumps({"hard_failures": ["protected_path_mutation"]}),
                encoding="utf-8",
            )
            ai_agents.judge(evidence, output)
            result = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result["verdict"], "HARD_FAIL")
        self.assertFalse(result["model_called"])


if __name__ == "__main__":
    unittest.main()
