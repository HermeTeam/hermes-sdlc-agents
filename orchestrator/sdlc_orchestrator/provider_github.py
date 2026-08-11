from __future__ import annotations

import hashlib
import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .config import Config, ConfigError
from .provider_base import WorkItem
from .transitions import ProviderTransitionResult


def fetch_issues(config: Config) -> list[WorkItem]:
    if not config.github_token:
        raise ConfigError("ORCHESTRATOR_GITHUB_TOKEN is required when GitHub discovery is enabled")
    repository = config.github_repository_full_name or config.repository_id
    if "/" not in repository:
        raise ConfigError("GITHUB_REPOSITORY_FULL_NAME must be owner/repo for GitHub discovery")

    url = f"{config.github_api_base_url}/repos/{repository}/issues?{urlencode({'state': 'open', 'per_page': '100'})}"
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {config.github_token}",
            "User-Agent": "hermes-sdlc-orchestrator/0.1",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"GitHub issue discovery failed: {exc}") from exc

    items: list[WorkItem] = []
    for issue in payload:
        normalized = normalize_issue(issue, repository)
        if normalized is not None:
            items.append(normalized)
    return items


def normalize_issue(issue: dict, repository_id: str) -> WorkItem | None:
    if "pull_request" in issue:
        return None
    body = issue.get("body") or ""
    labels = tuple(sorted((label.get("name") or "").lower() for label in issue.get("labels", []) if label.get("name")))
    assignees = tuple(sorted((assignee.get("login") or "").lower() for assignee in issue.get("assignees", []) if assignee.get("login")))
    return WorkItem(
        provider="github",
        repository_id=repository_id,
        kind="issue",
        external_id=str(issue["number"]),
        title=issue.get("title") or "",
        body=body,
        body_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        url=issue.get("html_url") or issue.get("url") or "",
        labels=labels,
        assignees=assignees,
        updated_at=issue.get("updated_at"),
    )


class GitHubTransitionAdapter:
    def __init__(self, config: Config) -> None:
        if not config.github_token:
            raise ConfigError("ORCHESTRATOR_GITHUB_TOKEN is required for GitHub transitions")
        self._token = config.github_token
        self._base_url = config.github_api_base_url
        self._repository = config.github_repository_full_name or config.repository_id

    def apply_issue_transition(
        self,
        item: WorkItem,
        *,
        add_labels: set[str],
        remove_labels: set[str],
        comment: str,
        idempotency_key: str,
    ) -> ProviderTransitionResult:
        if item.kind != "issue":
            raise RuntimeError("GitHub transitions currently support issue work items only")
        issue = quote(item.external_id, safe="")
        marker = f"<!-- hermes-transition:{idempotency_key} -->"
        marked_comment = f"{comment}\n\n{marker}"
        details: dict[str, object] = {
            "idempotency_key": idempotency_key,
            "comment": "pending",
            "added_labels": [],
            "removed_labels": [],
        }
        if add_labels:
            self._request(
                f"/repos/{self._repository}/issues/{issue}/labels",
                method="POST",
                body={"labels": sorted(add_labels)},
            )
            details["added_labels"] = sorted(add_labels)
        for label in sorted(remove_labels):
            result = self._request(
                f"/repos/{self._repository}/issues/{issue}/labels/{quote(label, safe='')}",
                method="DELETE",
                tolerate_404=True,
            )
            details["removed_labels"].append({"label": label, "status": "already_absent" if result.get("not_found") else "removed"})  # type: ignore[attr-defined]
        if self._comment_exists(issue, marker):
            details["comment"] = "already_exists"
        else:
            self._request(
                f"/repos/{self._repository}/issues/{issue}/comments",
                method="POST",
                body={"body": marked_comment},
            )
            details["comment"] = "created"
        return ProviderTransitionResult(applied=True, details=details)

    def _comment_exists(self, issue: str, marker: str) -> bool:
        comments = self._request(f"/repos/{self._repository}/issues/{issue}/comments?per_page=100", method="GET")
        if not isinstance(comments, list):
            return False
        return any(marker in str(comment.get("body") or "") for comment in comments if isinstance(comment, dict))

    def _request(self, path: str, *, method: str, body: dict | None = None, tolerate_404: bool = False):
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(
            f"{self._base_url}{path}",
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "User-Agent": "hermes-sdlc-orchestrator/0.1",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                if response.status == 204:
                    return {}
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if tolerate_404 and exc.code == 404:
                return {"not_found": True}
            raise RuntimeError(f"GitHub transition failed: HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}") from exc
        except (URLError, TimeoutError) as exc:
            raise RuntimeError(f"GitHub transition failed: {exc}") from exc
