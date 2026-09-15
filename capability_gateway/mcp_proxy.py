from __future__ import annotations

import hmac
import http.client
import json
import os
import ssl
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from typing import Any, Mapping
from urllib.parse import urlsplit

from .authority import (
    BUILDER_DISCOVERY_PERMISSIONS,
    AuthorityDenied,
    InvocationContext,
    builder_invocation_context,
    load_protected_patterns,
)
from .github_app import GitHubAppTokenBroker, GitHubAppUnavailable, ProviderToken
from .governance import GovernanceStore
from .models import RiskCategory


MAX_MCP_REQUEST_BYTES = 2 * 1024 * 1024
MAX_MCP_RESPONSE_BYTES = 16 * 1024 * 1024


class MCPProxyUnavailable(RuntimeError):
    pass


class MCPAuthorityBlocked(RuntimeError):
    def __init__(self, code: str, message: str, *, data: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = dict(data or {})


@dataclass(frozen=True)
class ExecutionPermit:
    provider_token: ProviderToken
    grant_id: str | None
    authority_source: str
    context: InvocationContext | None


class DynamicAuthorityProxy:
    """Terminate agent authority and inject provider authority server-side.

    The downstream agent authenticates to HermeTeam with a role-local gateway key.
    GitHub App installation tokens are minted only after the actual MCP invocation is
    validated and are never returned to the agent.
    """

    def __init__(
        self,
        *,
        store: GovernanceStore,
        max_auto_category: RiskCategory,
        token_broker: GitHubAppTokenBroker,
        upstream_url: str,
        builder_key: str,
        configured_repository: str,
        default_branch: str,
        protected_patterns: tuple[str, ...],
        execution_grant_ttl_seconds: int = 60,
        upstream_timeout_seconds: float = 180.0,
    ) -> None:
        parsed = urlsplit(upstream_url)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            raise MCPProxyUnavailable("CAPABILITY_UPSTREAM_MCP_URL must be http(s)")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise MCPProxyUnavailable("cleartext upstream MCP is allowed only on loopback")
        if len(builder_key) < 24:
            raise MCPProxyUnavailable("BUILDER_CAPABILITY_GATEWAY_KEY must contain at least 24 characters")
        if "/" not in configured_repository:
            raise MCPProxyUnavailable("GITHUB_REPOSITORY_FULL_NAME must be owner/name")

        self.store = store
        self.max_auto_category = max_auto_category
        self.token_broker = token_broker
        self.upstream_url = upstream_url
        self.builder_key = builder_key
        self.configured_repository = configured_repository
        self.default_branch = default_branch
        self.protected_patterns = protected_patterns
        self.execution_grant_ttl_seconds = max(10, min(execution_grant_ttl_seconds, 900))
        self.upstream_timeout_seconds = max(5.0, min(upstream_timeout_seconds, 600.0))

    @classmethod
    def from_environment(
        cls,
        *,
        store: GovernanceStore,
        max_auto_category: RiskCategory,
    ) -> "DynamicAuthorityProxy":
        protected_path = os.environ.get(
            "HERMETEAM_PROTECTED_PATHS_FILE", "/opt/hermeteam/policies/protected-paths.txt"
        )
        return cls(
            store=store,
            max_auto_category=max_auto_category,
            token_broker=GitHubAppTokenBroker.from_environment(),
            upstream_url=os.environ.get("CAPABILITY_UPSTREAM_MCP_URL", "").strip(),
            builder_key=os.environ.get("BUILDER_CAPABILITY_GATEWAY_KEY", "").strip(),
            configured_repository=os.environ.get("GITHUB_REPOSITORY_FULL_NAME", "").strip(),
            default_branch=os.environ.get("REPOSITORY_DEFAULT_BRANCH", "main").strip() or "main",
            protected_patterns=load_protected_patterns(protected_path),
            execution_grant_ttl_seconds=int(
                os.environ.get("CAPABILITY_EXECUTION_GRANT_TTL_SECONDS", "60")
            ),
            upstream_timeout_seconds=float(
                os.environ.get("CAPABILITY_UPSTREAM_TIMEOUT_SECONDS", "180")
            ),
        )

    def permit(self, *, headers: Mapping[str, str], body: bytes | None) -> ExecutionPermit:
        self._authenticate(headers)
        snapshot = self.store.snapshot()
        if snapshot.emergency_stop:
            raise MCPAuthorityBlocked("emergency_stop", "all capability execution is disabled")

        rpc = _parse_rpc(body)
        if rpc is None or rpc.get("method") != "tools/call":
            token = self.token_broker.mint(
                repository=self.configured_repository,
                permissions=BUILDER_DISCOVERY_PERMISSIONS,
            )
            return ExecutionPermit(token, None, "DISCOVERY", None)

        params = rpc.get("params")
        if not isinstance(params, dict):
            raise MCPAuthorityBlocked("invalid_tool_call", "tools/call params must be an object")
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(tool_name, str) or not tool_name:
            raise MCPAuthorityBlocked("invalid_tool_call", "tools/call name is required")
        if not isinstance(arguments, dict):
            raise MCPAuthorityBlocked("invalid_tool_call", "tools/call arguments must be an object")

        run_id = _bounded_header(headers, "X-HermeTeam-Run-Id", 200)
        if run_id is None:
            run_id = _bounded_header(headers, "Mcp-Session-Id", 200) or "sessionless"
        intent = _bounded_header(headers, "X-HermeTeam-Intent", 1000)
        try:
            context = builder_invocation_context(
                agent_id="hermes-builder",
                run_id=run_id,
                tool_name=tool_name,
                arguments=arguments,
                configured_repository=self.configured_repository,
                default_branch=self.default_branch,
                protected_patterns=self.protected_patterns,
            )
        except AuthorityDenied as exc:
            raise MCPAuthorityBlocked(
                "authority_denied",
                str(exc),
                data={"tool_id": f"github:{tool_name}"},
            ) from exc

        effective = snapshot.capability_overrides.get(context.capability, context.category)
        excepted = context.tool_id in snapshot.tool_exceptions
        requires_human = effective > self.max_auto_category and not excepted

        if requires_human and not self.store.has_execution_grant(context):
            self.store.record_execution_approval(
                context=context,
                allowed_category=self.max_auto_category,
                reason="actual invocation exceeds configured automatic risk ceiling",
                intent=intent,
            )
            raise MCPAuthorityBlocked(
                "approval_required",
                "explicit human authority is required for this exact invocation",
                data={
                    "request_id": context.request_id,
                    "tool_id": context.tool_id,
                    "capability": context.capability,
                    "requested_category": effective.name,
                    "allowed_category": self.max_auto_category.name,
                    "repository": context.repository,
                    "branch": context.branch,
                    "args_hash": context.args_hash,
                },
            )

        # Acquire provider authority before consuming a human one-shot grant. A token
        # broker outage therefore does not spend the user's approval. The grant is
        # consumed immediately before the upstream request is released.
        token = self.token_broker.mint(
            repository=context.repository,
            permissions=context.github_permissions,
        )

        if requires_human:
            grant_id = self.store.consume_execution_grant(context)
            if grant_id is None:
                raise MCPAuthorityBlocked(
                    "approval_already_consumed",
                    "the exact one-shot grant is no longer available",
                    data={"request_id": context.request_id},
                )
            source = "HUMAN"
        else:
            if excepted:
                source = "EXCEPTION"
            elif context.capability in snapshot.capability_overrides:
                source = "CAPABILITY_OVERRIDE"
            else:
                source = "AUTO"
            grant_id = self.store.record_auto_execution(context, authority_source=source)

        return ExecutionPermit(token, grant_id, source, context)

    def _authenticate(self, headers: Mapping[str, str]) -> None:
        role = _bounded_header(headers, "X-Hermes-Role", 100)
        if role not in {"builder", "hermes-builder"}:
            raise MCPAuthorityBlocked("unauthorized_agent", "only hermes-builder is enabled in this canary")
        supplied = headers.get("Authorization", "")
        expected = f"Bearer {self.builder_key}"
        if not hmac.compare_digest(supplied, expected):
            raise MCPAuthorityBlocked("unauthorized_agent", "invalid gateway agent credential")

    def forward(
        self,
        *,
        handler: BaseHTTPRequestHandler,
        method: str,
        body: bytes | None,
        permit: ExecutionPermit,
    ) -> None:
        _forward_upstream(
            handler=handler,
            upstream_url=self.upstream_url,
            method=method,
            body=body,
            provider_token=permit.provider_token.token,
            timeout_seconds=self.upstream_timeout_seconds,
        )


def read_mcp_body(handler: BaseHTTPRequestHandler) -> bytes | None:
    if handler.command in {"GET", "DELETE"}:
        return None
    raw_length = handler.headers.get("Content-Length")
    if raw_length is None:
        raise MCPAuthorityBlocked("invalid_request", "Content-Length is required")
    try:
        length = int(raw_length)
    except ValueError as exc:
        raise MCPAuthorityBlocked("invalid_request", "invalid Content-Length") from exc
    if length <= 0 or length > MAX_MCP_REQUEST_BYTES:
        raise MCPAuthorityBlocked("invalid_request", "MCP request body exceeds allowed size")
    return handler.rfile.read(length)


def send_mcp_error(
    handler: BaseHTTPRequestHandler,
    blocked: MCPAuthorityBlocked,
    *,
    request_id: Any = None,
    http_status: int = 200,
) -> None:
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": -32001,
            "message": blocked.code,
            "data": {"detail": blocked.message, **blocked.data},
        },
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    handler.send_response(http_status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def rpc_request_id(body: bytes | None) -> Any:
    rpc = _parse_rpc(body)
    return rpc.get("id") if rpc else None


def _parse_rpc(body: bytes | None) -> dict[str, Any] | None:
    if not body:
        return None
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MCPAuthorityBlocked("invalid_jsonrpc", "request body is not valid JSON") from exc
    if isinstance(value, list):
        # Batch tool execution complicates exact one-shot semantics. Fail closed until
        # each entry can be authorized and independently consumed.
        if any(isinstance(item, dict) and item.get("method") == "tools/call" for item in value):
            raise MCPAuthorityBlocked("batch_tool_calls_not_supported", "batch tools/call is disabled")
        return None
    if not isinstance(value, dict):
        raise MCPAuthorityBlocked("invalid_jsonrpc", "JSON-RPC request must be an object")
    return value


def _bounded_header(headers: Mapping[str, str], name: str, limit: int) -> str | None:
    value = headers.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise MCPAuthorityBlocked("invalid_request", f"invalid {name} header")
    if any(ord(char) < 32 for char in value):
        raise MCPAuthorityBlocked("invalid_request", f"invalid {name} header")
    return value.strip()


def _forward_upstream(
    *,
    handler: BaseHTTPRequestHandler,
    upstream_url: str,
    method: str,
    body: bytes | None,
    provider_token: str,
    timeout_seconds: float,
) -> None:
    parsed = urlsplit(upstream_url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if parsed.scheme == "https":
        connection: http.client.HTTPConnection = http.client.HTTPSConnection(
            parsed.hostname,
            port,
            timeout=timeout_seconds,
            context=ssl.create_default_context(),
        )
    else:
        connection = http.client.HTTPConnection(parsed.hostname, port, timeout=timeout_seconds)

    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    outgoing_headers: dict[str, str] = {
        "Authorization": f"Bearer {provider_token}",
        "Accept-Encoding": "identity",
        "User-Agent": "HermeTeam-Dynamic-Authority/0.1",
    }
    for name, value in handler.headers.items():
        lower = name.lower()
        if lower in {
            "accept",
            "content-type",
            "mcp-session-id",
            "mcp-protocol-version",
            "last-event-id",
            "mcp-method",
            "mcp-name",
            "x-mcp-toolsets",
            "x-mcp-tools",
            "x-mcp-exclude-tools",
            "x-mcp-features",
            "x-mcp-lockdown",
            "x-mcp-insiders",
        } or lower.startswith("mcp-param-"):
            outgoing_headers[name] = value
    if body is not None:
        outgoing_headers["Content-Length"] = str(len(body))

    try:
        connection.request(method, path, body=body, headers=outgoing_headers)
        response = connection.getresponse()
        handler.send_response(response.status)
        content_type = response.getheader("Content-Type") or "application/octet-stream"
        handler.send_header("Content-Type", content_type)
        for name in ("Mcp-Session-Id", "Mcp-Protocol-Version", "Cache-Control"):
            value = response.getheader(name)
            if value:
                handler.send_header(name, value)
        handler.send_header("X-Content-Type-Options", "nosniff")

        if method == "GET" or content_type.lower().startswith("text/event-stream"):
            handler.send_header("Connection", "close")
            handler.end_headers()
            total = 0
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_MCP_RESPONSE_BYTES:
                    break
                handler.wfile.write(chunk)
                handler.wfile.flush()
            handler.close_connection = True
            return

        raw = response.read(MAX_MCP_RESPONSE_BYTES + 1)
        if len(raw) > MAX_MCP_RESPONSE_BYTES:
            raise MCPProxyUnavailable("upstream MCP response exceeded allowed size")
        handler.send_header("Content-Length", str(len(raw)))
        handler.end_headers()
        handler.wfile.write(raw)
    except (OSError, http.client.HTTPException, GitHubAppUnavailable) as exc:
        raise MCPProxyUnavailable(f"upstream MCP request failed: {type(exc).__name__}") from exc
    finally:
        connection.close()
