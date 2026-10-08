"""Bounded GitHub REST authority facade for role-local orchestrators.

Orchestrators submit typed requests authenticated with *internal* role-specific
keys. Only this process holds GitHub App credentials. All writes require an
exact one-shot human execution grant; no raw path or arbitrary URL is accepted.
"""
from __future__ import annotations

import hmac
import json
import os
import re
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .authority import InvocationContext, canonical_args_hash
from .github_app import GitHubAppTokenBroker, GitHubAppUnavailable
from .governance import GovernanceStore
from .models import RiskCategory


ROLES = ("planner", "project-manager", "builder", "reviewer", "release", "incident", "learning")
ROLE_ENV = {
    role: "ORCHESTRATOR_" + role.upper().replace("-", "_") + "_GATEWAY_KEY"
    for role in ROLES
}
LABEL = re.compile(r"^[a-zA-Z0-9_.:/+ -]{1,100}$")
OPS = {
    "list_issues": ("GET", {"issues": "read"}, False),
    "list_comments": ("GET", {"issues": "read"}, False),
    "add_comment": ("POST", {"issues": "write"}, True),
    "add_labels": ("POST", {"issues": "write"}, True),
    "remove_label": ("DELETE", {"issues": "write"}, True),
}


class OrchestratorAuthorityError(RuntimeError):
    def __init__(self, code: str, *, request_id: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.request_id = request_id


class OrchestratorGitHubFacade:
    def __init__(
        self,
        *,
        store: GovernanceStore,
        broker: GitHubAppTokenBroker,
        repository: str,
        role_keys: Mapping[str, str],
        github_base_url: str = "https://api.github.com",
    ) -> None:
        if not repository or repository.count("/") != 1:
            raise ValueError("orchestrator repository must be owner/repo")
        if not github_base_url.startswith("https://"):
            raise ValueError("GitHub upstream requires HTTPS")
        if not role_keys or any(role not in ROLES or len(key) < 24 for role, key in role_keys.items()):
            raise ValueError("invalid orchestrator role identities")
        if len(set(role_keys.values())) != len(role_keys):
            raise ValueError("orchestrator role keys must be distinct")
        self.store = store
        self.broker = broker
        self.repository = repository
        self.role_keys = dict(role_keys)
        self.github_base_url = github_base_url.rstrip("/")

    @classmethod
    def from_environment(cls, *, store: GovernanceStore, broker: GitHubAppTokenBroker):
        keys = {role: value for role, name in ROLE_ENV.items() if (value := os.getenv(name, "").strip())}
        if not keys:
            return None
        return cls(
            store=store,
            broker=broker,
            repository=os.environ.get("GITHUB_REPOSITORY_FULL_NAME", ""),
            role_keys=keys,
            github_base_url=os.environ.get("GITHUB_API_BASE_URL", "https://api.github.com"),
        )

    def _identity(self, headers: Mapping[str, str]) -> str:
        provided = headers.get("Authorization", "")
        claim = headers.get("X-HermeTeam-Orchestrator-Role", "").removeprefix("hermes-")
        identity = None
        for role, secret in self.role_keys.items():
            if hmac.compare_digest(provided, "Bearer " + secret):
                identity = role
        if identity is None or identity != claim:
            raise OrchestratorAuthorityError("unauthorized_orchestrator")
        return identity

    def execute(self, *, headers: Mapping[str, str], request: Mapping[str, Any]) -> dict[str, Any]:
        role = self._identity(headers)
        if self.store.snapshot().emergency_stop:
            raise OrchestratorAuthorityError("emergency_stop")
        op = request.get("op")
        if not isinstance(op, str) or op not in OPS:
            raise OrchestratorAuthorityError("unknown_orchestrator_operation")
        if request.get("repository") != self.repository:
            raise OrchestratorAuthorityError("repository_out_of_scope")

        method, permissions, mutation = OPS[op]
        issue = request.get("issue_number")
        if op != "list_issues" and (not isinstance(issue, int) or isinstance(issue, bool) or issue <= 0):
            raise OrchestratorAuthorityError("invalid_issue_number")
        label = request.get("label")
        labels = request.get("labels")
        comment = request.get("comment")

        if op == "remove_label" and (not isinstance(label, str) or not LABEL.fullmatch(label)):
            raise OrchestratorAuthorityError("invalid_label")
        if op == "add_labels" and (
            not isinstance(labels, list) or not 0 < len(labels) <= 20
            or any(not isinstance(v, str) or not LABEL.fullmatch(v) for v in labels)
        ):
            raise OrchestratorAuthorityError("invalid_labels")
        if op == "add_comment" and (
            not isinstance(comment, str) or not comment.strip() or len(comment) > 10000
        ):
            raise OrchestratorAuthorityError("invalid_comment")

        params: dict[str, Any] = {"op": op, "repository": self.repository}
        if issue is not None and op != "list_issues":
            params["issue_number"] = issue
        if op == "add_labels":
            params["labels"] = labels
        if op == "remove_label":
            params["label"] = label
        if op == "add_comment":
            params["comment"] = comment

        context = InvocationContext(
            agent_id="orchestrator-" + role,
            role="orchestrator-" + role,
            run_id=str(request.get("run_id") or "orchestrator-session")[:200],
            tool_id="github:orchestrator." + op,
            capability="repository.issues." + op,
            category=RiskCategory.HIGH if mutation else RiskCategory.LOW,
            repository=self.repository,
            branch=None,
            paths=(),
            args_hash=canonical_args_hash("orchestrator." + op, params),
            github_permissions=permissions,
        )
        if mutation and not self.store.has_execution_grant(context):
            self.store.record_execution_approval(
                context=context,
                allowed_category=RiskCategory.MEDIUM,
                reason="role-local orchestrator write requires exact human authority",
                intent="orchestrator." + op,
            )
            raise OrchestratorAuthorityError("approval_required", request_id=context.request_id)

        # No provider token is minted before validation and approval checks.
        provider_token = self.broker.mint(repository=self.repository, permissions=permissions)
        if mutation and self.store.consume_execution_grant(context) is None:
            raise OrchestratorAuthorityError("approval_already_consumed", request_id=context.request_id)
        if not mutation:
            self.store.record_auto_execution(context, authority_source="AUTO")

        repo_path = "/repos/" + "/".join(quote(p, safe="") for p in self.repository.split("/"))
        path = repo_path + "/issues"
        body = None
        if op == "list_issues":
            path += "?state=open&per_page=100"
        else:
            path += "/" + str(issue)
            if op == "list_comments":
                path += "/comments?per_page=100"
            elif op == "add_comment":
                path += "/comments"
                body = {"body": comment}
            elif op == "add_labels":
                path += "/labels"
                body = {"labels": labels}
            else:
                path += "/labels/" + quote(label, safe="")

        wire = None if body is None else json.dumps(body).encode("utf-8")
        outgoing = Request(
            self.github_base_url + path,
            data=wire,
            method=method,
            headers={
                "Authorization": "Bearer " + provider_token.token,
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "HermeTeam-Orchestrator-Facade/0.1",
            },
        )
        try:
            with urlopen(outgoing, timeout=30) as response:
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise OrchestratorAuthorityError("upstream_response_too_large")
                return {"data": json.loads(raw) if raw else {}}
        except HTTPError as exc:
            if op == "remove_label" and exc.code == 404:
                return {"data": {"not_found": True}}
            raise OrchestratorAuthorityError("github_upstream_http_" + str(exc.code)) from exc
        except (URLError, TimeoutError) as exc:
            raise OrchestratorAuthorityError("github_upstream_unavailable") from exc
