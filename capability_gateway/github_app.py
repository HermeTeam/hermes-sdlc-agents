from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class GitHubAppUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderToken:
    token: str
    expires_at: str
    fingerprint: str
    repository: str
    permissions: Mapping[str, str]


@dataclass
class _CacheEntry:
    value: ProviderToken
    reusable_until: float


class GitHubAppTokenBroker:
    """Server-side GitHub App installation-token broker.

    Provider tokens never leave the capability gateway. A token is narrowed to one
    repository and the minimum GitHub App permission set required by the request.
    Small server-side reuse is allowed because exact per-request authority is enforced
    separately by HermeTeam execution grants.
    """

    def __init__(
        self,
        *,
        app_id: str,
        installation_id: str,
        private_key_path: str | Path,
        api_base_url: str = "https://api.github.com",
        timeout_seconds: float = 10.0,
        cache_seconds: int = 300,
        jwt_factory: Callable[[], str] | None = None,
    ) -> None:
        self.app_id = app_id
        self.installation_id = installation_id
        self.private_key_path = Path(private_key_path)
        self.api_base_url = api_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.cache_seconds = max(0, min(cache_seconds, 900))
        self._jwt_factory = jwt_factory
        self._cache: dict[tuple[str, tuple[tuple[str, str], ...]], _CacheEntry] = {}
        self._lock = threading.RLock()
        if not self.app_id or not self.installation_id:
            raise GitHubAppUnavailable("GITHUB_APP_ID and GITHUB_APP_INSTALLATION_ID are required")
        if not self.private_key_path.is_file():
            raise GitHubAppUnavailable("GitHub App private key file is missing")

    @classmethod
    def from_environment(cls) -> "GitHubAppTokenBroker":
        return cls(
            app_id=os.environ.get("GITHUB_APP_ID", "").strip(),
            installation_id=os.environ.get("GITHUB_APP_INSTALLATION_ID", "").strip(),
            private_key_path=os.environ.get(
                "GITHUB_APP_PRIVATE_KEY_PATH", "/run/secrets/github-app-private-key.pem"
            ),
            api_base_url=os.environ.get("GITHUB_API_BASE_URL", "https://api.github.com"),
            timeout_seconds=float(os.environ.get("CAPABILITY_PROVIDER_TIMEOUT_SECONDS", "10")),
            cache_seconds=int(os.environ.get("CAPABILITY_PROVIDER_TOKEN_CACHE_SECONDS", "300")),
        )

    def mint(self, *, repository: str, permissions: Mapping[str, str]) -> ProviderToken:
        owner, sep, repo = repository.partition("/")
        if not sep or not owner or not repo or "/" in repo:
            raise ValueError("repository must be owner/name")
        normalized_permissions = _normalize_permissions(permissions)
        cache_key = (repository, tuple(sorted(normalized_permissions.items())))
        now = time.time()
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and cached.reusable_until > now:
                return cached.value

        body = json.dumps(
            {
                "repositories": [repo],
                "permissions": normalized_permissions,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        app_jwt = self._jwt_factory() if self._jwt_factory else self._app_jwt()
        request = Request(
            f"{self.api_base_url}/app/installations/{self.installation_id}/access_tokens",
            data=body,
            method="POST",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {app_jwt}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "HermeTeam-Capability-Gateway/0.2",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read(262_144)
        except (HTTPError, URLError, TimeoutError) as exc:
            raise GitHubAppUnavailable(f"installation token request failed: {type(exc).__name__}") from exc
        try:
            payload = json.loads(raw)
            token = payload["token"]
            expires_at = payload["expires_at"]
            returned_permissions = payload.get("permissions", normalized_permissions)
            if not isinstance(token, str) or not token or not isinstance(expires_at, str):
                raise ValueError("invalid provider token response")
            if not isinstance(returned_permissions, dict):
                returned_permissions = normalized_permissions
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise GitHubAppUnavailable("installation token response was malformed") from exc

        value = ProviderToken(
            token=token,
            expires_at=expires_at,
            fingerprint=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            repository=repository,
            permissions=dict(returned_permissions),
        )
        expiry_epoch = _parse_github_time(expires_at)
        reusable_until = min(expiry_epoch - 60.0, now + self.cache_seconds)
        with self._lock:
            if reusable_until > now:
                self._cache[cache_key] = _CacheEntry(value=value, reusable_until=reusable_until)
        return value

    def _app_jwt(self) -> str:
        now = int(time.time())
        header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
        payload = _b64url(
            json.dumps(
                {
                    # Backdate slightly for clock skew and keep the App JWT short-lived.
                    "iat": now - 30,
                    "exp": now + 540,
                    "iss": self.app_id,
                },
                separators=(",", ":"),
            ).encode()
        )
        signing_input = f"{header}.{payload}".encode("ascii")
        try:
            process = subprocess.run(
                [
                    "openssl",
                    "dgst",
                    "-sha256",
                    "-sign",
                    str(self.private_key_path),
                ],
                input=signing_input,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise GitHubAppUnavailable("failed to sign GitHub App JWT") from exc
        return f"{header}.{payload}.{_b64url(process.stdout)}"


def _normalize_permissions(value: Mapping[str, str]) -> dict[str, str]:
    allowed = {"read", "write"}
    output: dict[str, str] = {}
    for name, level in value.items():
        if not isinstance(name, str) or not name or not isinstance(level, str):
            raise ValueError("invalid GitHub App permissions")
        normalized = level.lower()
        if normalized not in allowed:
            raise ValueError("GitHub App permission level must be read or write")
        output[name] = normalized
    if not output:
        raise ValueError("at least one GitHub App permission is required")
    return output


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _parse_github_time(value: str) -> float:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GitHubAppUnavailable("invalid GitHub token expiry") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()
