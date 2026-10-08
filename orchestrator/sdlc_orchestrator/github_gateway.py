"""Typed, role-authenticated orchestrator client. Never receives a GitHub token."""
from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .config import Config, ConfigError


def gateway_request(config: Config, operation: str, **arguments):
    if config.github_auth_mode != "gateway":
        raise ConfigError("orchestrator is not configured for GitHub Gateway authority")
    if not config.github_gateway_key or len(config.github_gateway_key) < 24:
        raise ConfigError("ORCHESTRATOR_GITHUB_GATEWAY_KEY must be configured for gateway mode")
    gateway = (config.github_gateway_url or "").rstrip("/")
    url = urlsplit(gateway)
    if (
        not url.hostname or url.path or url.query or url.fragment
        or (url.scheme == "http" and url.hostname != "capability-gateway")
        or url.scheme not in {"http", "https"}
    ):
        raise ConfigError("ORCHESTRATOR_GITHUB_GATEWAY_URL must be a dedicated Gateway origin")
    repository = config.github_repository_full_name or config.repository_id
    payload = {"op": operation, "repository": repository, **arguments}
    request = Request(
        gateway + "/v1/orchestrator/github",
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + config.github_gateway_key,
            "X-HermeTeam-Orchestrator-Role": "hermes-" + config.role,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            reply = json.loads(response.read(2_000_001))
    except HTTPError as exc:
        # No credentials or provider response bodies are echoed to logs.
        raise RuntimeError(f"Gateway authority request blocked: HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError("Gateway authority unavailable") from exc
    if not isinstance(reply, dict) or "data" not in reply:
        raise RuntimeError("Gateway authority response is malformed")
    return reply["data"]
