from __future__ import annotations

import hashlib
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import Config, ConfigError
from .provider_base import WorkItem


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
