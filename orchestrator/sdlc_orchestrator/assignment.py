from __future__ import annotations

from .config import Config
from .provider_base import WorkItem


def matches_role(item: WorkItem, config: Config) -> bool:
    labels = {label.lower() for label in item.labels}
    if labels & config.terminal_labels:
        return False
    assignees = {assignee.lower() for assignee in item.assignees}
    return bool((labels & config.role_labels) or (assignees & config.role_assignees))


def assignment_key(item: WorkItem, role: str) -> str:
    return item.assignment_key(role)
