from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "verification_topology", ROOT / "verification" / "verify_authority_topology.py"
)
assert SPEC and SPEC.loader
topology = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(topology)


def fixture():
    configured = {
        "BUILDER_CAPABILITY_GATEWAY_KEY": "builder-mcp-internal-unique-long-key",
    }
    gw = {
        "CAPABILITY_EXECUTION_MODE": "dynamic",
        "GITHUB_APP_ID": "12345",
    }
    services = {"capability-gateway": {"environment": gw}}
    for role, prefix in topology.ROLES.items():
        mcp = configured["BUILDER_CAPABILITY_GATEWAY_KEY"] if role == "builder" else "mcp-" + role + "-identity-long-enough-unique"
        orch = "orch-" + role + "-identity-long-enough-unique"
        if role != "builder":
            configured["CAPABILITY_" + prefix + "_GATEWAY_KEY"] = mcp
            gw["CAPABILITY_" + prefix + "_GATEWAY_KEY"] = mcp
        configured["ORCHESTRATOR_" + prefix + "_GATEWAY_KEY"] = orch
        gw["ORCHESTRATOR_" + prefix + "_GATEWAY_KEY"] = orch
        services["hermes-" + role] = {"environment": {
            "GIT_PROVIDER_MCP_URL": "http://capability-gateway:8787/mcp",
            "GIT_PROVIDER_MCP_TOKEN": mcp,
            "HERMES_DEFAULT_ORCHESTRATOR_GITHUB_AUTH_MODE": "gateway",
            "HERMES_DEFAULT_ORCHESTRATOR_GITHUB_GATEWAY_URL": "http://capability-gateway:8787",
            "HERMES_DEFAULT_ORCHESTRATOR_GITHUB_GATEWAY_KEY": orch,
            "HERMES_DEFAULT_ORCHESTRATOR_GITHUB_TOKEN": "",
        }}
    return services, configured


class TopologyContractTests(unittest.TestCase):
    def test_seven_roles_and_orchestrators_have_no_provider_tokens(self):
        services, configured = fixture()
        report = topology.check_topology(services, configured)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(len(report["roles_verified"]), 7)

    def test_direct_mcp_endpoint_is_rejected(self):
        services, configured = fixture()
        services["hermes-reviewer"]["environment"]["GIT_PROVIDER_MCP_URL"] = "https://api.githubcopilot.com/mcp/"
        with self.assertRaisesRegex(RuntimeError, "bypasses Gateway"):
            topology.check_topology(services, configured)

    def test_standing_orchestrator_token_is_rejected(self):
        services, configured = fixture()
        services["hermes-learning"]["environment"]["HERMES_DEFAULT_ORCHESTRATOR_GITHUB_TOKEN"] = "ghp_something"
        with self.assertRaisesRegex(RuntimeError, "provider token remains exposed"):
            topology.check_topology(services, configured)

    def test_reused_credentials_across_roles_are_rejected(self):
        services, configured = fixture()
        key = configured["CAPABILITY_PLANNER_GATEWAY_KEY"]
        configured["CAPABILITY_REVIEWER_GATEWAY_KEY"] = key
        services["hermes-reviewer"]["environment"]["GIT_PROVIDER_MCP_TOKEN"] = key
        services["capability-gateway"]["environment"]["CAPABILITY_REVIEWER_GATEWAY_KEY"] = key
        with self.assertRaisesRegex(RuntimeError, "distinct"):
            topology.check_topology(services, configured)


if __name__ == "__main__":
    unittest.main()
