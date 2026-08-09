from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkItem:
    provider: str
    repository_id: str
    kind: str
    external_id: str
    title: str
    body: str
    body_hash: str
    url: str
    labels: tuple[str, ...]
    assignees: tuple[str, ...]
    updated_at: str | None = None

    def assignment_key(self, role: str) -> str:
        return f"{self.provider}:{self.repository_id}:{self.kind}:{self.external_id}:{role}:v1"
