from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .models import ToolDescriptor


class CatalogUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ServerCandidate:
    source: str
    server_id: str
    description: str
    version: str | None
    raw: dict[str, Any]


def _get_json(url: str, timeout_seconds: float = 8.0) -> Any:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "HermeTeam-Capability-Gateway/0.1",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read(1_048_576))
    except Exception as exc:  # network/parser details must not leak into agent output
        raise CatalogUnavailable(f"catalog request failed for {url.split('/')[2]}") from exc


class OfficialRegistryCatalog:
    """Official MCP Registry discovery.

    The official Registry is authoritative for published server metadata but does not
    guarantee inspected tool schemas. Results are therefore discovery candidates only;
    they are never executable until an inspector/catalog supplies concrete tools.
    """

    base_url = "https://registry.modelcontextprotocol.io"

    def search_servers(self, query: str, limit: int = 20) -> tuple[ServerCandidate, ...]:
        params = urlencode({"search": query, "version": "latest", "limit": min(limit, 100)})
        payload = _get_json(f"{self.base_url}/v0.1/servers?{params}")
        servers = payload.get("servers", []) if isinstance(payload, dict) else []
        results: list[ServerCandidate] = []
        for item in servers:
            if not isinstance(item, dict):
                continue
            server = item.get("server", item)
            if not isinstance(server, dict):
                continue
            name = server.get("name")
            if not isinstance(name, str) or not name:
                continue
            description = server.get("description") if isinstance(server.get("description"), str) else ""
            version = server.get("version") if isinstance(server.get("version"), str) else None
            results.append(ServerCandidate("official", name, description, version, item))
        return tuple(results)


class GlamaCatalog:
    """Glama directory adapter.

    Glama exposes inspected server schemas/tools for many entries. The adapter accepts
    multiple response shapes intentionally because the public directory API evolves.
    Unrecognised fields are ignored; missing tool schemas fail closed by producing no
    executable ToolDescriptor.
    """

    base_url = "https://glama.ai/api/mcp/v1"

    def search_servers(self, query: str, limit: int = 20) -> tuple[ServerCandidate, ...]:
        params = urlencode({"query": query, "limit": min(limit, 50)})
        payload = _get_json(f"{self.base_url}/servers?{params}")
        values = _array_from(payload, "servers", "data", "results")
        output: list[ServerCandidate] = []
        for item in values:
            if not isinstance(item, dict):
                continue
            namespace = item.get("namespace") or item.get("owner")
            slug = item.get("slug") or item.get("name")
            if not isinstance(slug, str) or not slug:
                continue
            server_id = f"{namespace}/{slug}" if isinstance(namespace, str) and namespace else slug
            description = item.get("description") if isinstance(item.get("description"), str) else ""
            version = item.get("version") if isinstance(item.get("version"), str) else None
            output.append(ServerCandidate("glama", server_id, description, version, item))
        return tuple(output)

    def inspect_tools(self, candidate: ServerCandidate) -> tuple[ToolDescriptor, ...]:
        if candidate.source != "glama":
            return ()
        parts = candidate.server_id.split("/", 1)
        if len(parts) != 2:
            return ()
        payload = _get_json(
            f"{self.base_url}/servers/{quote(parts[0], safe='')}/{quote(parts[1], safe='')}"
        )
        tools = _find_tools(payload)
        output: list[ToolDescriptor] = []
        for item in tools:
            name = item.get("name")
            if not isinstance(name, str) or not name:
                continue
            description = item.get("description") if isinstance(item.get("description"), str) else ""
            input_schema = item.get("inputSchema") or item.get("input_schema") or {}
            annotations = item.get("annotations") or {}
            if not isinstance(input_schema, dict):
                input_schema = {}
            if not isinstance(annotations, dict):
                annotations = {}
            output.append(
                ToolDescriptor(
                    server_id=candidate.server_id,
                    tool_name=name,
                    description=description,
                    input_schema=input_schema,
                    annotations=annotations,
                    source="glama",
                    version=candidate.version,
                )
            )
        return tuple(output)


def discover_tools(query: str, *, max_servers: int = 8) -> tuple[ToolDescriptor, ...]:
    """Discover externally catalogued tools without installing or executing servers."""
    glama = GlamaCatalog()
    tools: list[ToolDescriptor] = []
    for server in glama.search_servers(query, limit=max_servers):
        tools.extend(glama.inspect_tools(server))
    return tuple(tools)


def _array_from(payload: Any, *keys: str) -> Iterable[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return ()


def _find_tools(payload: Any) -> Iterable[dict[str, Any]]:
    if isinstance(payload, dict):
        direct = payload.get("tools")
        if isinstance(direct, list):
            return [item for item in direct if isinstance(item, dict)]
        for key in ("server", "schema", "capabilities", "data"):
            nested = payload.get(key)
            found = list(_find_tools(nested))
            if found:
                return found
    return ()
