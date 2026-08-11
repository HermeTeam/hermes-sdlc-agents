from __future__ import annotations

import hashlib
import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .config import Config
from .provider_base import WorkItem
from .transitions import ProviderTransitionResult


def fetch_issues(config: Config) -> list[WorkItem]:
    if not config.gitlab_token or not config.gitlab_project:
        return []
    project = quote(config.gitlab_project, safe="")
    query = urlencode({"state": "opened", "per_page": "100"})
    url = f"{config.gitlab_api_base_url}/projects/{project}/issues?{query}"
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "PRIVATE-TOKEN": config.gitlab_token,
            "User-Agent": "hermes-sdlc-orchestrator/0.1",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"GitLab issue discovery failed: {exc}") from exc
    return [normalize_issue(issue, config.gitlab_project) for issue in payload]


def normalize_issue(issue: dict, repository_id: str) -> WorkItem:
    body = issue.get("description") or ""
    labels = tuple(sorted(str(label).lower() for label in issue.get("labels", []) if str(label)))
    assignees = tuple(sorted((assignee.get("username") or "").lower() for assignee in issue.get("assignees", []) if assignee.get("username")))
    return WorkItem(
        provider="gitlab",
        repository_id=repository_id,
        kind="issue",
        external_id=str(issue["iid"]),
        title=issue.get("title") or "",
        body=body,
        body_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        url=issue.get("web_url") or "",
        labels=labels,
        assignees=assignees,
        updated_at=issue.get("updated_at"),
    )


class GitLabTransitionAdapter:
    def __init__(self, _config: Config) -> None:
        pass

    def apply_issue_transition(
        self,
        item: WorkItem,
        *,
        add_labels: set[str],
        remove_labels: set[str],
        comment: str,
        idempotency_key: str,
    ) -> ProviderTransitionResult:
        return ProviderTransitionResult(
            applied=False,
            details={
                "mode": "unsupported",
                "provider": item.provider,
                "idempotency_key": idempotency_key,
                "comment": comment,
                "add_labels": sorted(add_labels),
                "remove_labels": sorted(remove_labels),
            },
        )
