from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FinalStatus(StrEnum):
    CHARTER_READY = "CHARTER_READY"
    ROADMAP_READY = "ROADMAP_READY"
    READY_FOR_ITERATION = "READY_FOR_ITERATION"
    IN_PROGRESS = "IN_PROGRESS"
    REVIEW = "REVIEW"
    DONE = "DONE"
    REPLAN_REQUIRED = "REPLAN_REQUIRED"
    PAUSED = "PAUSED"
    KILLED = "KILLED"

    READY_FOR_BUILD = "READY_FOR_BUILD"
    PR_READY_FOR_REVIEW = "PR_READY_FOR_REVIEW"
    APPROVE = "APPROVE"
    REQUEST_CHANGES = "REQUEST_CHANGES"

    BLOCKED = "BLOCKED"
    BLOCKED_NO_ACTION = "BLOCKED_NO_ACTION"
    NO_ACTION = "NO_ACTION"
    MONITORING = "MONITORING"
    ESCALATED = "ESCALATED"
    PROPOSED_FOR_HUMAN_REVIEW = "PROPOSED_FOR_HUMAN_REVIEW"


VALID_ROLES = {
    "project-manager",
    "planner",
    "builder",
    "reviewer",
    "release",
    "incident",
    "learning",
}

TERMINAL_LABELS = {"state:done", "state:cancelled", "hermes:blocked", "hermes:manual-only"}

DEFAULT_ROLE_LABELS = {
    "project-manager": {"hermes:project-manager", "state:project-management"},
    "planner": {"hermes:planner", "state:ready-for-planning"},
    "builder": {"hermes:builder", "state:ready-for-build"},
    "reviewer": {"hermes:reviewer", "state:review-needed"},
    "release": {"hermes:release", "state:ready-for-release"},
    "incident": {"hermes:incident"},
    "learning": {"hermes:learning"},
}

DEFAULT_ROLE_ASSIGNEES = {role: f"hermes-{role}" for role in VALID_ROLES}

ROLE_FINAL_STATUSES = {
    "project-manager": {
        FinalStatus.CHARTER_READY,
        FinalStatus.ROADMAP_READY,
        FinalStatus.READY_FOR_ITERATION,
        FinalStatus.IN_PROGRESS,
        FinalStatus.REVIEW,
        FinalStatus.DONE,
        FinalStatus.BLOCKED,
        FinalStatus.REPLAN_REQUIRED,
        FinalStatus.PAUSED,
        FinalStatus.KILLED,
    },
    "planner": {FinalStatus.READY_FOR_BUILD, FinalStatus.BLOCKED},
    "builder": {FinalStatus.PR_READY_FOR_REVIEW, FinalStatus.BLOCKED},
    "reviewer": {FinalStatus.APPROVE, FinalStatus.REQUEST_CHANGES, FinalStatus.BLOCKED},
    "release": {FinalStatus.NO_ACTION, FinalStatus.BLOCKED_NO_ACTION},
    "incident": {FinalStatus.MONITORING, FinalStatus.ESCALATED, FinalStatus.NO_ACTION},
    "learning": {FinalStatus.PROPOSED_FOR_HUMAN_REVIEW, FinalStatus.NO_ACTION},
}

TERMINAL_FINAL_STATUSES = {
    FinalStatus.BLOCKED,
    FinalStatus.BLOCKED_NO_ACTION,
    FinalStatus.NO_ACTION,
    FinalStatus.MONITORING,
    FinalStatus.ESCALATED,
    FinalStatus.PROPOSED_FOR_HUMAN_REVIEW,
    FinalStatus.DONE,
    FinalStatus.PAUSED,
    FinalStatus.KILLED,
}


@dataclass(frozen=True)
class TransitionSpec:
    next_role: str | None
    add_labels: frozenset[str]
    remove_labels: frozenset[str]
    comment_template: str


TRANSITIONS: dict[tuple[str, FinalStatus], TransitionSpec] = {
    ("planner", FinalStatus.READY_FOR_BUILD): TransitionSpec(
        next_role="builder",
        add_labels=frozenset({"state:ready-for-build", "hermes:builder"}),
        remove_labels=frozenset({"state:ready-for-planning", "hermes:planner"}),
        comment_template="Planner completed the spec/plan. Ready for builder.",
    ),
    ("builder", FinalStatus.PR_READY_FOR_REVIEW): TransitionSpec(
        next_role="reviewer",
        add_labels=frozenset({"state:review-needed", "hermes:reviewer"}),
        remove_labels=frozenset({"state:ready-for-build", "hermes:builder"}),
        comment_template="Builder opened a change request with evidence. Ready for reviewer.",
    ),
    ("reviewer", FinalStatus.APPROVE): TransitionSpec(
        next_role="release",
        add_labels=frozenset({"state:ready-for-release", "hermes:release"}),
        remove_labels=frozenset({"state:review-needed", "hermes:reviewer"}),
        comment_template="Reviewer approved the fixed change request. Ready for release evidence check.",
    ),
    ("reviewer", FinalStatus.REQUEST_CHANGES): TransitionSpec(
        next_role="builder",
        add_labels=frozenset({"state:ready-for-build", "hermes:builder"}),
        remove_labels=frozenset({"state:review-needed", "hermes:reviewer"}),
        comment_template="Reviewer requested changes. Returning to builder.",
    ),
}


def env_role_name(role: str) -> str:
    return role.upper().replace("-", "_")


def allowed_status_values(role: str) -> list[str]:
    return sorted(status.value for status in ROLE_FINAL_STATUSES[role])


def validate_final_status(role: str, value: str) -> FinalStatus:
    try:
        status = FinalStatus(value)
    except ValueError as exc:
        raise ValueError(f"unknown final_status: {value}") from exc
    if status not in ROLE_FINAL_STATUSES[role]:
        allowed = ", ".join(allowed_status_values(role))
        raise ValueError(f"final_status {value} is not allowed for {role}; allowed: {allowed}")
    return status
