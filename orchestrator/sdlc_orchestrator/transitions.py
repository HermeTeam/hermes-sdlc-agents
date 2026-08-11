from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Protocol

from . import db
from .config import Config
from .final_response import FinalResponse
from .provider_base import WorkItem
from .statuses import FinalStatus, TERMINAL_FINAL_STATUSES, TRANSITIONS, TransitionSpec


@dataclass(frozen=True)
class ProviderTransitionResult:
    applied: bool
    details: dict


class ProviderTransitionAdapter(Protocol):
    def apply_issue_transition(
        self,
        item: WorkItem,
        *,
        add_labels: set[str],
        remove_labels: set[str],
        comment: str,
        idempotency_key: str,
    ) -> ProviderTransitionResult:
        ...


def resolve_transition(role: str, final_status: FinalStatus) -> TransitionSpec | None:
    if (role, final_status) in TRANSITIONS:
        return TRANSITIONS[(role, final_status)]
    if final_status in TERMINAL_FINAL_STATUSES:
        add_labels = frozenset({"hermes:blocked"}) if final_status == FinalStatus.BLOCKED else frozenset()
        return TransitionSpec(
            next_role=None,
            add_labels=add_labels,
            remove_labels=frozenset(),
            comment_template=f"Hermes {role} finished with {final_status.value}.",
        )
    return None


def apply_transition(
    conn: sqlite3.Connection,
    *,
    item: WorkItem,
    final_response: FinalResponse,
    config: Config,
    provider_adapter: ProviderTransitionAdapter | None,
) -> None:
    spec = resolve_transition(final_response.role, final_response.final_status)
    if spec is None:
        return
    comment = _render_comment(spec, final_response)
    if not config.apply_transitions:
        db.record_transition(
            conn,
            assignment_key=final_response.assignment_key,
            from_role=final_response.role,
            final_status=final_response.final_status.value,
            next_role=spec.next_role,
            provider_applied=False,
            provider_result=json.dumps({"mode": "disabled", "comment": comment}, ensure_ascii=False, sort_keys=True),
        )
        return
    if provider_adapter is None:
        db.record_transition(
            conn,
            assignment_key=final_response.assignment_key,
            from_role=final_response.role,
            final_status=final_response.final_status.value,
            next_role=spec.next_role,
            provider_applied=False,
            error="provider transition adapter unavailable",
        )
        return
    add_labels = set() if config.transition_comment_only else set(spec.add_labels)
    remove_labels = set() if config.transition_comment_only else set(spec.remove_labels)
    try:
        result = provider_adapter.apply_issue_transition(
            item,
            add_labels=add_labels,
            remove_labels=remove_labels,
            comment=comment,
            idempotency_key=f"transition:{final_response.assignment_key}:{final_response.final_status.value}",
        )
    except Exception as exc:  # provider errors must not erase the reconciled final response
        db.record_transition(
            conn,
            assignment_key=final_response.assignment_key,
            from_role=final_response.role,
            final_status=final_response.final_status.value,
            next_role=spec.next_role,
            provider_applied=False,
            error=str(exc),
        )
        return
    db.record_transition(
        conn,
        assignment_key=final_response.assignment_key,
        from_role=final_response.role,
        final_status=final_response.final_status.value,
        next_role=spec.next_role,
        provider_applied=result.applied,
        provider_result=json.dumps(result.details, ensure_ascii=False, sort_keys=True),
    )


def apply_failure_transition(
    conn: sqlite3.Connection,
    *,
    item: WorkItem,
    assignment_key: str,
    role: str,
    failure_status: str,
    summary: str,
    config: Config,
    provider_adapter: ProviderTransitionAdapter | None,
) -> None:
    comment = _render_failure_comment(assignment_key, failure_status, summary)
    if not config.apply_transitions:
        db.record_transition(
            conn,
            assignment_key=assignment_key,
            from_role=role,
            final_status=failure_status,
            next_role=None,
            provider_applied=False,
            provider_result=json.dumps({"mode": "disabled", "comment": comment}, ensure_ascii=False, sort_keys=True),
        )
        return
    if provider_adapter is None:
        db.record_transition(
            conn,
            assignment_key=assignment_key,
            from_role=role,
            final_status=failure_status,
            next_role=None,
            provider_applied=False,
            error="provider transition adapter unavailable",
        )
        return
    try:
        result = provider_adapter.apply_issue_transition(
            item,
            add_labels=set() if config.transition_comment_only else {"hermes:blocked"},
            remove_labels=set(),
            comment=comment,
            idempotency_key=f"transition:{assignment_key}:{failure_status}",
        )
    except Exception as exc:
        db.record_transition(
            conn,
            assignment_key=assignment_key,
            from_role=role,
            final_status=failure_status,
            next_role=None,
            provider_applied=False,
            error=str(exc),
        )
        return
    db.record_transition(
        conn,
        assignment_key=assignment_key,
        from_role=role,
        final_status=failure_status,
        next_role=None,
        provider_applied=result.applied,
        provider_result=json.dumps(result.details, ensure_ascii=False, sort_keys=True),
    )


def _render_comment(spec: TransitionSpec, final_response: FinalResponse) -> str:
    lines = [
        spec.comment_template,
        "",
        f"Assignment: {final_response.assignment_key}",
        f"Final status: {final_response.final_status.value}",
        f"Summary: {final_response.summary}",
    ]
    if final_response.block_reason:
        lines.append(f"Block reason: {final_response.block_reason}")
    if final_response.evidence:
        lines.append(f"Evidence items: {len(final_response.evidence)}")
    return "\n".join(lines)


def _render_failure_comment(assignment_key: str, failure_status: str, summary: str) -> str:
    return "\n".join(
        [
            f"Hermes orchestration failure: {failure_status}.",
            "",
            f"Assignment: {assignment_key}",
            f"Summary: {summary}",
        ]
    )
