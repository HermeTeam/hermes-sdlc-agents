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
expected_external_skill_dirs = ["/etc/hermes/skills", "/opt/hermes-shared-skills/current"]
broad_provider_tool_markers = ["github_request", "gitlab_request", "graphql", "http_request"]
required_dotenv_keys = {
    "OPENAI_API_KEY",
    "GIT_PROVIDER_MCP_URL",
    "REPOSITORY_ID",
    "REPOSITORY_PROVIDER",
    "REPOSITORY_ACCESS_MODE",
    "REPOSITORY_DEFAULT_BRANCH",
    "REPOSITORY_CLONE_ALLOWED",
    "GITHUB_API_BASE_URL",
    "GITHUB_WEB_BASE_URL",
    "GITHUB_OWNER",
    "GITHUB_REPOSITORY",
    "GITHUB_REPOSITORY_FULL_NAME",
    "GITHUB_REPOSITORY_HTML_URL",
    "GITHUB_REPOSITORY_API_URL",
}

errors = []
if set(policy_roles) != expected_roles:
    errors.append("roles.yaml does not define exactly the six expected roles")

dotenv_example = root / ".env.example"
def parse_dotenv(path):
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            result[key] = value
    return result

dotenv_values = parse_dotenv(dotenv_example)
dotenv_keys = set(dotenv_values)
missing_dotenv_keys = sorted(required_dotenv_keys - dotenv_keys)
if missing_dotenv_keys:
    errors.append(f".env.example missing required repository keys: {', '.join(missing_dotenv_keys)}")
if dotenv_values.get("REPOSITORY_CLONE_ALLOWED") != "false":
    errors.append(".env.example: REPOSITORY_CLONE_ALLOWED must be false")
if dotenv_values.get("GITHUB_REPOSITORY_FULL_NAME") != "test-project/test-project":
    errors.append(".env.example: GITHUB_REPOSITORY_FULL_NAME must be test-project/test-project")
if (root / ".env").is_file():
    runtime_dotenv_values = parse_dotenv(root / ".env")
    missing_runtime_dotenv_keys = sorted(required_dotenv_keys - set(runtime_dotenv_values))
    if missing_runtime_dotenv_keys:
        errors.append(f".env missing required repository keys: {', '.join(missing_runtime_dotenv_keys)}")
    if runtime_dotenv_values.get("REPOSITORY_CLONE_ALLOWED") != "false":
        errors.append(".env: REPOSITORY_CLONE_ALLOWED must be false")

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
    if "skills" not in config.get("toolsets", []):
        errors.append(f"{role}: skills toolset must be enabled for shared skill discovery")
    if "skills" in set(config.get("agent", {}).get("disabled_toolsets", [])):
        errors.append(f"{role}: skills toolset must not be disabled")
    external_dirs = config.get("skills", {}).get("external_dirs", [])
    if external_dirs != expected_external_skill_dirs:
        errors.append(f"{role}: skills.external_dirs must be {expected_external_skill_dirs}")

    mcp_servers = config.get("mcp_servers", {})
    if "sdlc" in mcp_servers:
        errors.append(f"{role}: legacy repository gateway server must not be configured for MVP")
    if "mcp-sdlc" in config.get("toolsets", []):
        errors.append(f"{role}: mcp-sdlc toolset must not be enabled for MVP")
    server = mcp_servers.get("repository", {})
    included = server.get("tools", {}).get("include", [])
    allowed = policy_roles[role].get("allowTools", [])
    if included != allowed:
        errors.append(f"{role}: MCP include list differs from roles.yaml allowTools")
    if any("*" in item for item in included):
        errors.append(f"{role}: wildcard in MCP include list")
    if any(marker in tool for tool in included for marker in broad_provider_tool_markers):
        errors.append(f"{role}: broad provider/raw request tool exposed")
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
        if config.get("worktree") is not False or config.get("worktree_sync") is not False:
            errors.append("hermes-builder: local worktree mode must be disabled in direct repository API/MCP mode")
        if "terminal" in config.get("toolsets", []):
            errors.append("hermes-builder: terminal toolset must be disabled in direct repository API/MCP mode")
        if any(tool in included for tool in ["repo_merge_pull_request", "repo_merge_change_request"]):
            errors.append("hermes-builder: merge tool exposed")
        if any(tool in included for tool in ["repo_push_task_branch", "repo_create_pull_request"]):
            errors.append("hermes-builder: deprecated local-checkout repository tool exposed")
    if role == "hermes-learning":
        if config.get("skills", {}).get("write_approval") is not True:
            errors.append("hermes-learning: every skill write must require approval")
        if any("activate" in tool or "publish" in tool or "install" in tool for tool in included):
            errors.append("hermes-learning: activation/publication tool exposed")

    for secret_template in [root / "secrets" / f"{role}.env.example", root / "secrets" / f"{role}.env"]:
        if secret_template.is_file() and "OPENAI_API_KEY" in secret_template.read_text(encoding="utf-8"):
            errors.append(f"{secret_template.relative_to(root)}: OPENAI_API_KEY must be supplied from .env, not role secrets")

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
        init_containers = pod_spec.get("initContainers", [])
        if not any(container.get("name") == "sync-shared-skills" for container in init_containers):
            errors.append(f"{role}: shared skills sync initContainer missing")
        volumes = pod_spec.get("volumes", [])
        if not any(volume.get("name") == "shared-skills" for volume in volumes):
            errors.append(f"{role}: shared-skills volume missing")
        if len(containers) != 1:
            errors.append(f"{role}: exactly one main Hermes container is required")
        else:
            refs = containers[0].get("envFrom", [])
            expected_secret = f"{role}-env"
            if not any(item.get("secretRef", {}).get("name") == expected_secret for item in refs):
                errors.append(f"{role}: expected Secret ref {expected_secret}")
            mounts = containers[0].get("volumeMounts", [])
            if not any(
                mount.get("name") == "shared-skills"
                and mount.get("mountPath") == "/opt/hermes-shared-skills/current"
                and mount.get("readOnly") is True
                for mount in mounts
            ):
                errors.append(f"{role}: shared skills must be mounted read-only")
            if role == "hermes-builder":
                container_text = str(containers[0])
                if "/workspace/repo" in container_text or "REPO_DIR" in container_text:
                    errors.append("hermes-builder: local repository mount references must be absent")

kustomization = yaml.safe_load((root / "kustomization.yaml").read_text(encoding="utf-8"))
for resource in kustomization.get("resources", []):
    if not (root / resource).is_file():
        errors.append(f"kustomization references missing resource: {resource}")

compose = yaml.safe_load((root / "compose.yaml").read_text(encoding="utf-8"))
expected_services = expected_roles | {"skills-superset-sync"}
if set(compose.get("services", {})) != expected_services:
    errors.append("compose.yaml does not define exactly the expected services")
for role, service in compose.get("services", {}).items():
    if role == "skills-superset-sync":
        if "shared-skills:/shared" not in service.get("volumes", []):
            errors.append("skills-superset-sync: shared-skills volume must be writable at /shared")
        continue
    if service.get("container_name") != role:
        errors.append(f"{role}: container_name mismatch")
    service_environment = service.get("environment", {})
    if "GITHUB_PROVIDER_TOKEN" in service_environment:
        errors.append(f"{role}: legacy GitHub adapter token must not be passed to Hermes agents")
    if role != "hermes-builder" and any("/workspace/repo" in str(v) for v in service.get("volumes", [])):
        errors.append(f"{role}: repository mount must be absent")
    if role == "hermes-builder":
        service_text = str(service)
        if "/workspace/repo" in service_text or "REPO_DIR" in service_text:
            errors.append("hermes-builder: compose local repository mount references must be absent")
    if "shared-skills:/opt/hermes-shared-skills:ro" not in service.get("volumes", []):
        errors.append(f"{role}: shared-skills volume must be mounted read-only")
    depends_on = service.get("depends_on", {})
    if depends_on.get("skills-superset-sync", {}).get("condition") != "service_completed_successfully":
        errors.append(f"{role}: must wait for skills-superset-sync")

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
