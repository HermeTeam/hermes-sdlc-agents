from __future__ import annotations

import fnmatch
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .models import RiskCategory


@dataclass(frozen=True)
class ActionSpec:
    capability: str
    category: RiskCategory
    github_permissions: Mapping[str, str]
    mutation: bool = False


@dataclass(frozen=True)
class InvocationContext:
    agent_id: str
    role: str
    run_id: str
    tool_id: str
    capability: str
    category: RiskCategory
    repository: str
    branch: str | None
    paths: tuple[str, ...]
    args_hash: str
    github_permissions: Mapping[str, str]

    @property
    def request_id(self) -> str:
        material = "\0".join(
            (
                self.agent_id,
                self.run_id,
                self.tool_id,
                self.capability,
                self.repository,
                self.branch or "",
                self.args_hash,
            )
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


BUILDER_ACTIONS: dict[str, ActionSpec] = {
    "get_file_contents": ActionSpec(
        "repository.file.read", RiskCategory.LOW, {"contents": "read"}
    ),
    "get_repository_tree": ActionSpec(
        "repository.tree.read", RiskCategory.LOW, {"contents": "read"}
    ),
    "search_code": ActionSpec(
        "repository.code.search", RiskCategory.LOW, {"contents": "read"}
    ),
    "create_branch": ActionSpec(
        "repository.branch.create", RiskCategory.MEDIUM, {"contents": "write"}, True
    ),
    "push_files": ActionSpec(
        "repository.files.modify", RiskCategory.MEDIUM, {"contents": "write"}, True
    ),
    "create_pull_request": ActionSpec(
        "repository.pull_request.create",
        RiskCategory.MEDIUM,
        {"pull_requests": "write"},
        True,
    ),
    "actions_run_trigger": ActionSpec(
        "ci.workflow.trigger", RiskCategory.HIGH, {"actions": "write"}, True
    ),
    "actions_get": ActionSpec(
        "ci.workflow.read", RiskCategory.LOW, {"actions": "read"}
    ),
    "actions_list": ActionSpec(
        "ci.workflow.read", RiskCategory.LOW, {"actions": "read"}
    ),
    "get_job_logs": ActionSpec(
        "ci.logs.read", RiskCategory.LOW, {"actions": "read"}
    ),
}

# Used only for MCP initialize/tools-list/session traffic. The token never leaves
# the authority gateway. Actual tools/call requests receive the minimal permission
# set from the matching ActionSpec above.
BUILDER_DISCOVERY_PERMISSIONS: dict[str, str] = {
    "contents": "write",
    "pull_requests": "write",
    "actions": "write",
}


class AuthorityDenied(ValueError):
    pass


def canonical_args_hash(tool_name: str, arguments: Mapping[str, Any]) -> str:
    value = {
        "tool": tool_name,
        "arguments": _normalize(arguments),
    }
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def builder_invocation_context(
    *,
    agent_id: str,
    run_id: str,
    tool_name: str,
    arguments: Mapping[str, Any],
    configured_repository: str,
    default_branch: str,
    protected_patterns: tuple[str, ...],
) -> InvocationContext:
    spec = BUILDER_ACTIONS.get(tool_name)
    if spec is None:
        raise AuthorityDenied("tool_not_in_builder_authority_map")

    repository = _repository(arguments)
    if repository != configured_repository:
        raise AuthorityDenied("repository_out_of_scope")

    branch = _branch(tool_name, arguments)
    paths = _paths(arguments)

    if tool_name in {"create_branch", "push_files"}:
        if not branch or not branch.startswith("agent/"):
            raise AuthorityDenied("builder_branch_must_use_agent_prefix")

    if tool_name == "create_pull_request":
        head = _optional_string(arguments.get("head"))
        base = _optional_string(arguments.get("base"))
        if not head or not head.startswith("agent/"):
            raise AuthorityDenied("pull_request_head_must_use_agent_prefix")
        if base != default_branch:
            raise AuthorityDenied("pull_request_base_must_match_default_branch")
        branch = head

    if tool_name == "actions_run_trigger":
        ref = _optional_string(arguments.get("ref"))
        if not ref or not ref.startswith("agent/"):
            raise AuthorityDenied("workflow_dispatch_ref_must_use_agent_prefix")
        branch = ref

    if spec.mutation:
        for path in paths:
            if _is_protected(path, protected_patterns):
                raise AuthorityDenied("protected_path")

    return InvocationContext(
        agent_id=agent_id,
        role="builder",
        run_id=run_id,
        tool_id=f"github:{tool_name}",
        capability=spec.capability,
        category=spec.category,
        repository=repository,
        branch=branch,
        paths=paths,
        args_hash=canonical_args_hash(tool_name, arguments),
        github_permissions=dict(spec.github_permissions),
    )


def load_protected_patterns(path: str | Path) -> tuple[str, ...]:
    value = Path(path)
    if not value.is_file():
        raise RuntimeError(f"protected paths file not found: {value}")
    patterns: list[str] = []
    for raw in value.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return tuple(patterns)


def _repository(arguments: Mapping[str, Any]) -> str:
    owner = _optional_string(arguments.get("owner"))
    repo = _optional_string(arguments.get("repo"))
    if not owner or not repo:
        raise AuthorityDenied("owner_and_repo_are_required")
    return f"{owner}/{repo}"


def _branch(tool_name: str, arguments: Mapping[str, Any]) -> str | None:
    for key in ("branch", "ref", "head"):
        value = _optional_string(arguments.get(key))
        if value:
            return value
    if tool_name == "create_branch":
        return _optional_string(arguments.get("branch"))
    return None


def _paths(arguments: Mapping[str, Any]) -> tuple[str, ...]:
    output: list[str] = []
    direct = arguments.get("path")
    if isinstance(direct, str) and direct.strip():
        output.append(direct.strip().lstrip("/"))
    files = arguments.get("files")
    if isinstance(files, list):
        for item in files:
            if isinstance(item, Mapping):
                path = item.get("path")
                if isinstance(path, str) and path.strip():
                    output.append(path.strip().lstrip("/"))
    return tuple(dict.fromkeys(output))


def _is_protected(path: str, patterns: tuple[str, ...]) -> bool:
    normalized = path.lstrip("/")
    for pattern in patterns:
        candidate = pattern.lstrip("/")
        # Python's fnmatch handles the repository patterns used by HermeTeam well
        # enough for the canary. Exact names and directory prefixes are checked too.
        if fnmatch.fnmatch(normalized, candidate):
            return True
        if candidate.endswith("/**") and normalized.startswith(candidate[:-3].rstrip("/") + "/"):
            return True
        if normalized == candidate:
            return True
    return False


def _normalize(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _normalize(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    return str(value)


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
