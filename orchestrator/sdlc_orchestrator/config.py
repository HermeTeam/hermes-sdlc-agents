from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlparse

from .statuses import DEFAULT_ROLE_ASSIGNEES, DEFAULT_ROLE_LABELS, TERMINAL_LABELS, VALID_ROLES, env_role_name


class ConfigError(ValueError):
    """Raised when orchestrator configuration is unsafe or incomplete."""


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}")
    return value


def _csv_set(name: str, default: set[str]) -> set[str]:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return set(default)
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


@dataclass(frozen=True)
class Config:
    enabled: bool
    role: str
    provider: str
    repository_id: str
    hermes_url: str
    api_server_key: str
    db_path: Path
    lock_path: Path
    max_starts_per_tick: int
    run_timeout_seconds: int
    github_token: str | None = None
    github_api_base_url: str = "https://api.github.com"
    github_repository_full_name: str | None = None
    gitlab_token: str | None = None
    gitlab_api_base_url: str = "https://gitlab.com/api/v4"
    gitlab_project: str | None = None
    role_labels: set[str] = field(default_factory=set)
    terminal_labels: set[str] = field(default_factory=lambda: set(TERMINAL_LABELS))
    role_assignees: set[str] = field(default_factory=set)
    apply_transitions: bool = False
    transition_comment_only: bool = True

    @classmethod
    def from_env(cls) -> "Config":
        role = os.getenv("ORCHESTRATOR_ROLE", "").strip().lower()
        if role not in VALID_ROLES:
            raise ConfigError(f"ORCHESTRATOR_ROLE must be one of {sorted(VALID_ROLES)}")

        provider = os.getenv("ORCHESTRATOR_PROVIDER", os.getenv("REPOSITORY_PROVIDER", "github")).strip().lower()
        if provider not in {"github", "gitlab"}:
            raise ConfigError("ORCHESTRATOR_PROVIDER must be github or gitlab")

        hermes_url = os.getenv("ORCHESTRATOR_HERMES_URL", "http://127.0.0.1:8642").rstrip("/")
        _validate_local_hermes_url(hermes_url)

        db_path = Path(os.getenv("ORCHESTRATOR_DB_PATH", "/opt/data/sdlc-orchestrator/orchestrator.sqlite"))
        lock_path = Path(os.getenv("ORCHESTRATOR_LOCK_PATH", "/opt/data/sdlc-orchestrator/run_once.lock"))
        _validate_data_path(db_path, "ORCHESTRATOR_DB_PATH")
        _validate_data_path(lock_path, "ORCHESTRATOR_LOCK_PATH")

        repository_id = os.getenv("REPOSITORY_ID") or os.getenv("GITHUB_REPOSITORY_FULL_NAME") or ""
        repository_id = repository_id.strip()
        if not repository_id:
            raise ConfigError("REPOSITORY_ID or GITHUB_REPOSITORY_FULL_NAME is required")

        api_server_key = os.getenv("API_SERVER_KEY", "")
        if not api_server_key:
            raise ConfigError("API_SERVER_KEY is required")

        role_env_name = env_role_name(role)
        role_labels = _csv_set(f"ORCHESTRATOR_{role_env_name}_LABELS", DEFAULT_ROLE_LABELS[role])
        role_assignees = _csv_set(f"ORCHESTRATOR_{role_env_name}_ASSIGNEES", {DEFAULT_ROLE_ASSIGNEES[role]})

        return cls(
            enabled=_bool(os.getenv("ORCHESTRATOR_ENABLED"), False),
            role=role,
            provider=provider,
            repository_id=repository_id,
            hermes_url=hermes_url,
            api_server_key=api_server_key,
            db_path=db_path,
            lock_path=lock_path,
            max_starts_per_tick=_int_env("ORCHESTRATOR_MAX_STARTS_PER_TICK", 1, 0),
            run_timeout_seconds=_int_env("ORCHESTRATOR_RUN_TIMEOUT_SECONDS", 5400, 60),
            github_token=os.getenv("ORCHESTRATOR_GITHUB_TOKEN") or None,
            github_api_base_url=os.getenv("GITHUB_API_BASE_URL", "https://api.github.com").rstrip("/"),
            github_repository_full_name=os.getenv("GITHUB_REPOSITORY_FULL_NAME") or None,
            gitlab_token=os.getenv("ORCHESTRATOR_GITLAB_TOKEN") or None,
            gitlab_api_base_url=os.getenv("GITLAB_API_BASE_URL", "https://gitlab.com/api/v4").rstrip("/"),
            gitlab_project=os.getenv("GITLAB_PROJECT") or None,
            role_labels=role_labels,
            terminal_labels=_csv_set("ORCHESTRATOR_TERMINAL_LABELS", TERMINAL_LABELS),
            role_assignees=role_assignees,
            apply_transitions=_bool(os.getenv("ORCHESTRATOR_APPLY_TRANSITIONS"), False),
            transition_comment_only=_bool(os.getenv("ORCHESTRATOR_TRANSITION_COMMENT_ONLY"), True),
        )


def _validate_local_hermes_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ConfigError("ORCHESTRATOR_HERMES_URL must be http(s)")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ConfigError("ORCHESTRATOR_HERMES_URL must point to localhost")


def _validate_data_path(path: Path, name: str) -> None:
    try:
        path.resolve().relative_to(Path("/opt/data/sdlc-orchestrator").resolve())
    except ValueError as exc:
        raise ConfigError(f"{name} must be under /opt/data/sdlc-orchestrator") from exc
