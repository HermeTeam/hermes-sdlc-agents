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
    "hermes-planner", "hermes-project-manager", "hermes-builder", "hermes-reviewer",
    "hermes-release", "hermes-incident", "hermes-learning",
}
expected_skill = "skills/hermes-agent-self-evolution/SKILL.md"
expected_external_skill_dirs = ["/etc/hermes/skills", "/opt/hermes-shared-skills/current"]
broad_provider_tool_markers = ["github_request", "gitlab_request", "graphql", "http_request"]
legacy_facade_tool_prefixes = ("repo_", "ci_", "quality_", "work_item_", "spec_", "plan_")
github_mcp_url = "https://api.githubcopilot.com/mcp/"
github_mcp_toolsets = "repos,issues,pull_requests,actions,git,code_security,dependabot"
legacy_issue_tool = "create" + "_issue"
role_github_token_vars = {
    "hermes-planner": "PLANNER_GITHUB_MCP_TOKEN",
    "hermes-project-manager": "PROJECT_MANAGER_GITHUB_MCP_TOKEN",
    "hermes-builder": "BUILDER_GITHUB_MCP_TOKEN",
    "hermes-reviewer": "REVIEWER_GITHUB_MCP_TOKEN",
    "hermes-release": "RELEASE_GITHUB_MCP_TOKEN",
    "hermes-incident": "INCIDENT_GITHUB_MCP_TOKEN",
    "hermes-learning": "LEARNING_GITHUB_MCP_TOKEN",
}
role_short_names = {role: role.removeprefix("hermes-") for role in role_github_token_vars}
role_env_prefixes = {
    "hermes-planner": "PLANNER",
    "hermes-project-manager": "PROJECT_MANAGER",
    "hermes-builder": "BUILDER",
    "hermes-reviewer": "REVIEWER",
    "hermes-release": "RELEASE",
    "hermes-incident": "INCIDENT",
    "hermes-learning": "LEARNING",
}
role_api_model_names = {role: role for role in role_env_prefixes}
orchestrator_wrapper = "/opt/hermes-sdlc-orchestrator/bin/hermes-with-orchestrator.sh"
orchestrator_mount = "./orchestrator:/opt/hermes-sdlc-orchestrator:ro"
orchestrator_db_path = "/opt/data/sdlc-orchestrator/orchestrator.sqlite"
orchestrator_lock_path = "/opt/data/sdlc-orchestrator/run_once.lock"
workspace_dir = "/opt/data/workspace"
required_dotenv_keys = {
    "OPENAI_API_KEY",
    "HERMES_ORCHESTRATOR_IMAGE",
    "ORCHESTRATOR_ENABLED",
    "ORCHESTRATOR_PROVIDER",
    "ORCHESTRATOR_CRON_SCHEDULE",
    "ORCHESTRATOR_MAX_STARTS_PER_TICK",
    "ORCHESTRATOR_RUN_TIMEOUT_SECONDS",
    "ORCHESTRATOR_APPLY_TRANSITIONS",
    "ORCHESTRATOR_TRANSITION_COMMENT_ONLY",
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
    "HERMES_MODEL_ID",
    "HERMES_MODEL_BASE_URL",
    "HERMES_MODEL_OPENAI_API_KEY",
    "BRAVE_API_KEY",
    "CONTEXT7_DEFAULT_MINIMUM_TOKENS",
    "MDB_MCP_CONNECTION_STRING",
    "POSTGRES_MCP_CONNECTION_STRING",
} | set(role_github_token_vars.values())
for role, prefix in role_env_prefixes.items():
    required_dotenv_keys.update({
        f"{prefix}_API_SERVER_KEY",
        f"{prefix}_API_SERVER_MODEL_NAME",
        f"{prefix}_HERMES_MODEL_ID",
        f"{prefix}_HERMES_MODEL_BASE_URL",
        f"{prefix}_HERMES_MODEL_OPENAI_API_KEY",
        f"{prefix}_BRAVE_API_KEY",
        f"{prefix}_CONTEXT7_DEFAULT_MINIMUM_TOKENS",
        f"{prefix}_MDB_MCP_CONNECTION_STRING",
        f"{prefix}_POSTGRES_MCP_CONNECTION_STRING",
        f"ORCHESTRATOR_{prefix}_GITHUB_TOKEN",
        f"ORCHESTRATOR_{prefix}_GITLAB_TOKEN",
    })
runtime_optional_dotenv_keys = {
    "HERMES_ORCHESTRATOR_IMAGE",
    "ORCHESTRATOR_ENABLED",
    "ORCHESTRATOR_PROVIDER",
    "ORCHESTRATOR_CRON_SCHEDULE",
    "ORCHESTRATOR_MAX_STARTS_PER_TICK",
    "ORCHESTRATOR_RUN_TIMEOUT_SECONDS",
    "ORCHESTRATOR_APPLY_TRANSITIONS",
    "ORCHESTRATOR_TRANSITION_COMMENT_ONLY",
}

errors = []
if set(policy_roles) != expected_roles:
    errors.append("roles.yaml does not define exactly the seven expected roles")

active_policy_text = (root / "policies/roles.yaml").read_text(encoding="utf-8")
if legacy_issue_tool in active_policy_text:
    errors.append("policies/roles.yaml must use issue_write, not the legacy issue creation tool")

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
if dotenv_values.get("REPOSITORY_PROVIDER") == "github" and dotenv_values.get("GIT_PROVIDER_MCP_URL") != github_mcp_url:
    errors.append(f".env.example: GIT_PROVIDER_MCP_URL must be {github_mcp_url} for GitHub MVP")
if dotenv_values.get("GITHUB_REPOSITORY_FULL_NAME") != "test-project/test-project":
    errors.append(".env.example: GITHUB_REPOSITORY_FULL_NAME must be test-project/test-project")
if "GIT_PROVIDER_MCP_TOKEN" in dotenv_values:
    errors.append(".env.example: use role-specific *_GITHUB_MCP_TOKEN keys, not generic GIT_PROVIDER_MCP_TOKEN")
if dotenv_values.get("ORCHESTRATOR_ENABLED") != "false":
    errors.append(".env.example: ORCHESTRATOR_ENABLED must default to false")
if dotenv_values.get("ORCHESTRATOR_PROVIDER") != "github":
    errors.append(".env.example: ORCHESTRATOR_PROVIDER must default to github")
if dotenv_values.get("ORCHESTRATOR_APPLY_TRANSITIONS") != "false":
    errors.append(".env.example: ORCHESTRATOR_APPLY_TRANSITIONS must default to false")
if dotenv_values.get("ORCHESTRATOR_TRANSITION_COMMENT_ONLY") != "true":
    errors.append(".env.example: ORCHESTRATOR_TRANSITION_COMMENT_ONLY must default to true")
if (root / ".env").is_file():
    runtime_dotenv_values = parse_dotenv(root / ".env")
    missing_runtime_dotenv_keys = sorted((required_dotenv_keys - runtime_optional_dotenv_keys) - set(runtime_dotenv_values))
    if missing_runtime_dotenv_keys:
        errors.append(f".env missing required repository keys: {', '.join(missing_runtime_dotenv_keys)}")
    if runtime_dotenv_values.get("REPOSITORY_CLONE_ALLOWED") != "false":
        errors.append(".env: REPOSITORY_CLONE_ALLOWED must be false")
    if runtime_dotenv_values.get("REPOSITORY_PROVIDER") == "github" and runtime_dotenv_values.get("GIT_PROVIDER_MCP_URL") != github_mcp_url:
        errors.append(f".env: GIT_PROVIDER_MCP_URL must be {github_mcp_url} for GitHub MVP")
    if "GIT_PROVIDER_MCP_TOKEN" in runtime_dotenv_values:
        errors.append(".env: use role-specific *_GITHUB_MCP_TOKEN keys, not generic GIT_PROVIDER_MCP_TOKEN")
    if "ORCHESTRATOR_PROVIDER" in runtime_dotenv_values and runtime_dotenv_values.get("ORCHESTRATOR_PROVIDER") not in {"github", "gitlab"}:
        errors.append(".env: ORCHESTRATOR_PROVIDER must be github or gitlab")

if not (root / "Dockerfile.orchestrator").is_file():
    errors.append("Dockerfile.orchestrator is required for cron runner packaging")
for script_name in ["orchestrator/bin/hermes-with-orchestrator.sh", "orchestrator/bin/orchestrator-run-once.sh"]:
    script_path = root / script_name
    if not script_path.is_file():
        errors.append(f"{script_name} missing")
    elif not (script_path.stat().st_mode & 0o111):
        errors.append(f"{script_name} must be executable")

for role in sorted(expected_roles):
    profile_dir = root / "profiles" / role
    config_text = (profile_dir / "config.yaml").read_text(encoding="utf-8")
    if legacy_issue_tool in config_text:
        errors.append(f"{role}: config.yaml must use issue_write, not the legacy issue creation tool")
    config = yaml.safe_load(config_text)
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
    headers = server.get("headers", {})
    if headers.get("X-MCP-Toolsets") != github_mcp_toolsets:
        errors.append(f"{role}: repository MCP X-MCP-Toolsets must be {github_mcp_toolsets}")
    included = server.get("tools", {}).get("include", [])
    allowed = policy_roles[role].get("allowTools", [])
    if included != allowed:
        errors.append(f"{role}: MCP include list differs from roles.yaml allowTools")
    if any("*" in item for item in included):
        errors.append(f"{role}: wildcard in MCP include list")
    if any(marker in tool for tool in included for marker in broad_provider_tool_markers):
        errors.append(f"{role}: broad provider/raw request tool exposed")
    if any(tool.startswith(legacy_facade_tool_prefixes) for tool in included):
        errors.append(f"{role}: legacy abstract repository facade tool exposed")
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
        if any(tool in included for tool in ["merge_pull_request", "repo_merge_pull_request", "repo_merge_change_request"]):
            errors.append("hermes-builder: merge tool exposed")
        if any(tool in included for tool in ["repo_push_task_branch", "repo_create_pull_request", "repo_apply_patch", "repo_commit_changes"]):
            errors.append("hermes-builder: deprecated abstract repository facade tool exposed")
    if role == "hermes-learning":
        if config.get("skills", {}).get("write_approval") is not True:
            errors.append("hermes-learning: every skill write must require approval")
        if any("activate" in tool or "publish" in tool or "install" in tool for tool in included):
            errors.append("hermes-learning: activation/publication tool exposed")

    for secret_template in [root / "secrets" / f"{role}.env.example", root / "secrets" / f"{role}.env"]:
        if secret_template.is_file():
            secret_values = parse_dotenv(secret_template)
            if "OPENAI_API_KEY" in secret_values:
                errors.append(f"{secret_template.relative_to(root)}: OPENAI_API_KEY must be supplied from .env, not role secrets")
            if "GIT_PROVIDER_MCP_TOKEN" in secret_values:
                errors.append(f"{secret_template.relative_to(root)}: GIT_PROVIDER_MCP_TOKEN must be supplied from role-specific .env token, not role secrets")
            allowed_secret_keys = {
                "HERMES_MODEL_ID",
                "HERMES_MODEL_BASE_URL",
                "HERMES_MODEL_OPENAI_API_KEY",
                "API_SERVER_KEY",
                "API_SERVER_MODEL_NAME",
                "ORCHESTRATOR_GITHUB_TOKEN",
                "ORCHESTRATOR_GITLAB_TOKEN",
                "BRAVE_API_KEY",
                "CONTEXT7_DEFAULT_MINIMUM_TOKENS",
                "MDB_MCP_CONNECTION_STRING",
                "POSTGRES_MCP_CONNECTION_STRING",
            }
            unknown_secret_keys = sorted(set(secret_values) - allowed_secret_keys)
            if unknown_secret_keys:
                errors.append(f"{secret_template.relative_to(root)}: unsupported role env keys: {', '.join(unknown_secret_keys)}")
            if secret_template.name.endswith(".env.example"):
                missing_secret_keys = sorted(allowed_secret_keys - set(secret_values))
                if missing_secret_keys:
                    errors.append(f"{secret_template.relative_to(root)}: missing role env example keys: {', '.join(missing_secret_keys)}")

    workload_path = root / "kubernetes" / f"{role}.yaml"
    workload_docs = [doc for doc in yaml.safe_load_all(workload_path.read_text(encoding="utf-8")) if doc]
    deployments = [doc for doc in workload_docs if doc.get("kind") == "Deployment"]
    services = [doc for doc in workload_docs if doc.get("kind") == "Service"]
    if len(deployments) != 1 or len(services) != 1:
        errors.append(f"{role}: Kubernetes file must contain one Deployment and one Service")
    else:
        pod_spec = deployments[0]["spec"]["template"]["spec"]
        if deployments[0].get("spec", {}).get("replicas") != 1:
            errors.append(f"{role}: Kubernetes replicas must be 1 for local SQLite dedupe")
        if deployments[0].get("spec", {}).get("strategy", {}).get("type") != "Recreate":
            errors.append(f"{role}: Kubernetes strategy must be Recreate")
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
            container = containers[0]
            refs = containers[0].get("envFrom", [])
            expected_secret = f"{role}-env"
            if not any(item.get("secretRef", {}).get("name") == expected_secret for item in refs):
                errors.append(f"{role}: expected Secret ref {expected_secret}")
            mounts = containers[0].get("volumeMounts", [])
            command = container.get("command", [])
            if command != [orchestrator_wrapper]:
                errors.append(f"{role}: Kubernetes container must start via orchestrator wrapper")
            container_env = {item.get("name"): item.get("value") for item in container.get("env", [])}
            if container_env.get("ORCHESTRATOR_ROLE") != role_short_names[role]:
                errors.append(f"{role}: Kubernetes ORCHESTRATOR_ROLE mismatch")
            if container_env.get("ORCHESTRATOR_DB_PATH") != orchestrator_db_path:
                errors.append(f"{role}: Kubernetes ORCHESTRATOR_DB_PATH must be {orchestrator_db_path}")
            if container_env.get("ORCHESTRATOR_LOCK_PATH") != orchestrator_lock_path:
                errors.append(f"{role}: Kubernetes ORCHESTRATOR_LOCK_PATH must be {orchestrator_lock_path}")
            if container_env.get("ORCHESTRATOR_HERMES_URL") != "http://127.0.0.1:8642":
                errors.append(f"{role}: Kubernetes ORCHESTRATOR_HERMES_URL must be localhost")
            if container_env.get("ORCHESTRATOR_APPLY_TRANSITIONS") != "false":
                errors.append(f"{role}: Kubernetes ORCHESTRATOR_APPLY_TRANSITIONS must default to false")
            if container_env.get("ORCHESTRATOR_TRANSITION_COMMENT_ONLY") != "true":
                errors.append(f"{role}: Kubernetes ORCHESTRATOR_TRANSITION_COMMENT_ONLY must default to true")
            if str(container).count("API_SERVER_KEY") > 0:
                errors.append(f"{role}: Kubernetes API_SERVER_KEY must come only from the role Secret envFrom")
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
    if service.get("entrypoint") != [orchestrator_wrapper]:
        errors.append(f"{role}: compose service must start via orchestrator wrapper")
    if service.get("init") is not True:
        errors.append(f"{role}: compose init must be true for child reaping")
    service_environment = service.get("environment", {})
    prefix = role_env_prefixes[role]
    expected_env_file = [{"path": f"./secrets/{role}.env", "required": False}]
    if service.get("env_file") != expected_env_file:
        errors.append(f"{role}: compose service must use optional per-role env_file {expected_env_file}")
    if service_environment.get("ORCHESTRATOR_ROLE") != role_short_names[role]:
        errors.append(f"{role}: compose ORCHESTRATOR_ROLE mismatch")
    if service_environment.get("ORCHESTRATOR_DB_PATH") != orchestrator_db_path:
        errors.append(f"{role}: compose ORCHESTRATOR_DB_PATH must be {orchestrator_db_path}")
    if service_environment.get("ORCHESTRATOR_LOCK_PATH") != orchestrator_lock_path:
        errors.append(f"{role}: compose ORCHESTRATOR_LOCK_PATH must be {orchestrator_lock_path}")
    if service_environment.get("ORCHESTRATOR_HERMES_URL") != "http://127.0.0.1:8642":
        errors.append(f"{role}: compose ORCHESTRATOR_HERMES_URL must be localhost")
    if service_environment.get("HERMES_WORKSPACE_DIR") != workspace_dir:
        errors.append(f"{role}: compose HERMES_WORKSPACE_DIR must be {workspace_dir}")
    if service_environment.get("ORCHESTRATOR_APPLY_TRANSITIONS") != "${ORCHESTRATOR_APPLY_TRANSITIONS:-false}":
        errors.append(f"{role}: compose ORCHESTRATOR_APPLY_TRANSITIONS must be mapped from .env with false default")
    if service_environment.get("ORCHESTRATOR_TRANSITION_COMMENT_ONLY") != "${ORCHESTRATOR_TRANSITION_COMMENT_ONLY:-true}":
        errors.append(f"{role}: compose ORCHESTRATOR_TRANSITION_COMMENT_ONLY must be mapped from .env with true default")
    expected_container_env = {
        "HERMES_DEFAULT_HERMES_MODEL_ID": f"${{{prefix}_HERMES_MODEL_ID:-${{HERMES_MODEL_ID:?Set HERMES_MODEL_ID in .env}}}}",
        "HERMES_DEFAULT_HERMES_MODEL_BASE_URL": f"${{{prefix}_HERMES_MODEL_BASE_URL:-${{HERMES_MODEL_BASE_URL:?Set HERMES_MODEL_BASE_URL in .env}}}}",
        "HERMES_DEFAULT_HERMES_MODEL_OPENAI_API_KEY": f"${{{prefix}_HERMES_MODEL_OPENAI_API_KEY:-${{HERMES_MODEL_OPENAI_API_KEY:-}}}}",
        "HERMES_DEFAULT_API_SERVER_KEY": f"${{{prefix}_API_SERVER_KEY:?Set {prefix}_API_SERVER_KEY in .env}}",
        "HERMES_DEFAULT_API_SERVER_MODEL_NAME": f"${{{prefix}_API_SERVER_MODEL_NAME:-{role_api_model_names[role]}}}",
        "HERMES_DEFAULT_ORCHESTRATOR_GITHUB_TOKEN": f"${{ORCHESTRATOR_{prefix}_GITHUB_TOKEN:?Set ORCHESTRATOR_{prefix}_GITHUB_TOKEN in .env}}",
        "HERMES_DEFAULT_ORCHESTRATOR_GITLAB_TOKEN": f"${{ORCHESTRATOR_{prefix}_GITLAB_TOKEN:-}}",
        "HERMES_DEFAULT_BRAVE_API_KEY": f"${{{prefix}_BRAVE_API_KEY:-${{BRAVE_API_KEY:-}}}}",
        "HERMES_DEFAULT_CONTEXT7_DEFAULT_MINIMUM_TOKENS": f"${{{prefix}_CONTEXT7_DEFAULT_MINIMUM_TOKENS:-${{CONTEXT7_DEFAULT_MINIMUM_TOKENS:-}}}}",
        "HERMES_DEFAULT_MDB_MCP_CONNECTION_STRING": f"${{{prefix}_MDB_MCP_CONNECTION_STRING:-${{MDB_MCP_CONNECTION_STRING:-}}}}",
        "HERMES_DEFAULT_POSTGRES_MCP_CONNECTION_STRING": f"${{{prefix}_POSTGRES_MCP_CONNECTION_STRING:-${{POSTGRES_MCP_CONNECTION_STRING:-}}}}",
    }
    for key, expected_value in expected_container_env.items():
        if service_environment.get(key) != expected_value:
            errors.append(f"{role}: compose {key} must be mapped from central .env using {prefix} override")
    for key in [
        "HERMES_MODEL_ID",
        "HERMES_MODEL_BASE_URL",
        "HERMES_MODEL_OPENAI_API_KEY",
        "API_SERVER_KEY",
        "API_SERVER_MODEL_NAME",
        "ORCHESTRATOR_GITHUB_TOKEN",
        "ORCHESTRATOR_GITLAB_TOKEN",
        "BRAVE_API_KEY",
        "CONTEXT7_DEFAULT_MINIMUM_TOKENS",
        "MDB_MCP_CONNECTION_STRING",
        "POSTGRES_MCP_CONNECTION_STRING",
    ]:
        if key in service_environment:
            errors.append(f"{role}: compose {key} must stay overridable through the optional role env_file")
    if "GITHUB_PROVIDER_TOKEN" in service_environment:
        errors.append(f"{role}: legacy GitHub adapter token must not be passed to Hermes agents")
    expected_token_expr = f"${{{role_github_token_vars[role]}:?Set {role_github_token_vars[role]} in .env}}"
    if service_environment.get("GIT_PROVIDER_MCP_TOKEN") != expected_token_expr:
        errors.append(f"{role}: GIT_PROVIDER_MCP_TOKEN must be mapped from {role_github_token_vars[role]}")
    service_text = str(service)
    if "/workspace/repo" in service_text or "REPO_DIR" in service_text:
        errors.append(f"{role}: compose local repository mount references must be absent")
    expected_workspace_mount = f"./workspace/{role_short_names[role]}:{workspace_dir}"
    if expected_workspace_mount not in service.get("volumes", []):
        errors.append(f"{role}: workspace must be mounted as {expected_workspace_mount}")
    if "shared-skills:/opt/hermes-shared-skills:ro" not in service.get("volumes", []):
        errors.append(f"{role}: shared-skills volume must be mounted read-only")
    if orchestrator_mount not in service.get("volumes", []):
        errors.append(f"{role}: orchestrator code must be mounted read-only in compose")
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
  opa test \
    "${bundle_root}/policies/mcp-policy.rego" \
    "${bundle_root}/policies/mcp-policy_test.rego" \
    "${bundle_root}/policies/roles.yaml"
else
  echo "OPA not found; skipped Rego compile check."
fi

if command -v docker >/dev/null 2>&1 \
  && docker compose version >/dev/null 2>&1 \
  && [[ -f "${bundle_root}/.env" ]]; then
  docker compose --project-directory "${bundle_root}" --env-file "${bundle_root}/.env" config --quiet
else
  echo "Docker Compose or .env is unavailable; skipped docker compose config check."
fi

echo "Validation complete."
