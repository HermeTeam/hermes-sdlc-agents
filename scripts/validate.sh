#!/usr/bin/env bash
set -euo pipefail

bundle_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for script in "${bundle_root}"/scripts/*.sh; do
  bash -n "${script}"
done

python3 - "${bundle_root}" <<'PY'
from pathlib import Path
import hashlib
import sys

try:
    import yaml
except ImportError as exc:
    raise SystemExit("PyYAML is required for validation: python3 -m pip install pyyaml") from exc

root = Path(sys.argv[1])

for yaml_path in sorted(root.rglob("*.yaml")):
    try:
        list(yaml.safe_load_all(yaml_path.read_text(encoding="utf-8")))
    except Exception as exc:
        raise SystemExit(f"Invalid YAML in {yaml_path.relative_to(root)}: {exc}") from exc

policy = yaml.safe_load((root / "policies/roles.yaml").read_text(encoding="utf-8"))
policy_roles = policy["spec"]["roles"]
expected_roles = {
    "hermes-planner", "hermes-builder", "hermes-reviewer",
    "hermes-release", "hermes-incident", "hermes-learning",
}
expected_skill = "skills/hermes-agent-self-evolution/SKILL.md"

errors = []
if set(policy_roles) != expected_roles:
    errors.append("roles.yaml does not define exactly the six expected roles")

for role in sorted(expected_roles):
    profile_dir = root / "profiles" / role
    config = yaml.safe_load((profile_dir / "config.yaml").read_text(encoding="utf-8"))
    manifest = yaml.safe_load((profile_dir / "distribution.yaml").read_text(encoding="utf-8"))
    if manifest.get("name") != role:
        errors.append(f"{role}: distribution name mismatch")
    if not (profile_dir / "SOUL.md").is_file():
        errors.append(f"{role}: SOUL.md missing")
    owned = manifest.get("distribution_owned", [])
    if "skills/" not in owned:
        errors.append(f"{role}: skills/ must be distribution-owned")
    skill_path = profile_dir / expected_skill
    if not skill_path.is_file():
        errors.append(f"{role}: {expected_skill} missing")

    server = config.get("mcp_servers", {}).get("sdlc", {})
    included = server.get("tools", {}).get("include", [])
    allowed = policy_roles[role].get("allowTools", [])
    if included != allowed:
        errors.append(f"{role}: MCP include list differs from roles.yaml allowTools")
    if any("*" in item for item in included):
        errors.append(f"{role}: wildcard in MCP include list")
    if server.get("tools", {}).get("resources") is not False:
        errors.append(f"{role}: MCP resources must be disabled")
    if server.get("tools", {}).get("prompts") is not False:
        errors.append(f"{role}: MCP prompts must be disabled")
    if server.get("sampling", {}).get("enabled") is not False:
        errors.append(f"{role}: MCP sampling must be disabled")
    if server.get("elicitation", {}).get("enabled") is not False:
        errors.append(f"{role}: MCP elicitation must be disabled")
    if config.get("security", {}).get("redact_secrets") is not True:
        errors.append(f"{role}: secret redaction must be enabled")
    if config.get("tool_loop_guardrails", {}).get("hard_stop_enabled") is not True:
        errors.append(f"{role}: unattended hard stop must be enabled")
    if config.get("memory", {}).get("memory_enabled") is not False:
        errors.append(f"{role}: persistent memory must be disabled")

    disabled = set(config.get("agent", {}).get("disabled_toolsets", []))
    if role != "hermes-builder" and not {"terminal", "file"}.issubset(disabled):
        errors.append(f"{role}: terminal and file toolsets must be disabled")
    if role == "hermes-builder":
        if config.get("worktree") is not True or config.get("worktree_sync") is not True:
            errors.append("hermes-builder: worktree isolation is required")
        if "repo_merge_pull_request" in included:
            errors.append("hermes-builder: merge tool exposed")
    if role == "hermes-learning":
        if config.get("skills", {}).get("write_approval") is not True:
            errors.append("hermes-learning: every skill write must require approval")
        if any("activate" in tool or "publish" in tool or "install" in tool for tool in included):
            errors.append("hermes-learning: activation/publication tool exposed")

    workload_path = root / "kubernetes" / f"{role}.yaml"
    workload_docs = [doc for doc in yaml.safe_load_all(workload_path.read_text(encoding="utf-8")) if doc]
    deployments = [doc for doc in workload_docs if doc.get("kind") == "Deployment"]
    services = [doc for doc in workload_docs if doc.get("kind") == "Service"]
    if len(deployments) != 1 or len(services) != 1:
        errors.append(f"{role}: Kubernetes file must contain one Deployment and one Service")
    else:
        pod_spec = deployments[0]["spec"]["template"]["spec"]
        if pod_spec.get("automountServiceAccountToken") is not False:
            errors.append(f"{role}: Kubernetes service-account token must not be mounted")
        containers = pod_spec.get("containers", [])
        if len(containers) != 1:
            errors.append(f"{role}: exactly one main Hermes container is required")
        else:
            refs = containers[0].get("envFrom", [])
            expected_secret = f"{role}-env"
            if not any(item.get("secretRef", {}).get("name") == expected_secret for item in refs):
                errors.append(f"{role}: expected Secret ref {expected_secret}")

kustomization = yaml.safe_load((root / "kustomization.yaml").read_text(encoding="utf-8"))
for resource in kustomization.get("resources", []):
    if not (root / resource).is_file():
        errors.append(f"kustomization references missing resource: {resource}")

compose = yaml.safe_load((root / "compose.yaml").read_text(encoding="utf-8"))
expected_services = expected_roles
if set(compose.get("services", {})) != expected_services:
    errors.append("compose.yaml does not define exactly the six expected services")
for role, service in compose.get("services", {}).items():
    if service.get("container_name") != role:
        errors.append(f"{role}: container_name mismatch")
    if role != "hermes-builder" and any("/workspace/repo" in str(v) for v in service.get("volumes", [])):
        errors.append(f"{role}: repository mount must be absent")

if errors:
    print("Validation failed:")
    for error in errors:
        print(f"- {error}")
    raise SystemExit(1)

skill_hashes = {
    role: hashlib.sha256((root / "profiles" / role / expected_skill).read_bytes()).hexdigest()
    for role in sorted(expected_roles)
}
if len(set(skill_hashes.values())) != 1:
    print("Validation failed:")
    for role, digest in skill_hashes.items():
        print(f"- {role}: self-evolution skill hash {digest}")
    raise SystemExit(1)

print("Hermes profiles and role policy are structurally consistent.")
PY

if command -v opa >/dev/null 2>&1; then
  opa check "${bundle_root}/policies/mcp-policy.rego"
  opa test "${bundle_root}/policies"
else
  echo "OPA not found; skipped Rego compile check."
fi

if command -v docker >/dev/null 2>&1 \
  && docker compose version >/dev/null 2>&1 \
  && [[ -f "${bundle_root}/.env" ]] \
  && compgen -G "${bundle_root}/secrets/*.env" >/dev/null; then
  docker compose --project-directory "${bundle_root}" --env-file "${bundle_root}/.env" config --quiet
else
  echo "Compose runtime inputs are not complete; skipped docker compose config check."
fi

echo "Validation complete."
