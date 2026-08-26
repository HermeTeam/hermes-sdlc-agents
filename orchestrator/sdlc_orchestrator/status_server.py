"""A tiny role-local, read-only HTTP facade over the status snapshot.

Only ``GET /health`` and ``GET /status`` are exposed.  The transport layer
does not inspect request bodies, configuration values, or database rows beyond
the already-sanitized T02 snapshot.  It intentionally has no lifecycle wiring;
T04 owns process supervision and Compose/network changes.
"""

from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from typing import Final

from .config import Config, ConfigError, StatusServerConfig
from .status_snapshot import StatusSnapshotError, read_role_status_snapshot
from .statuses import VALID_ROLES


MAX_RESPONSE_BYTES: Final = 131_072
SQLITE_BUSY_RETRY_AFTER_SECONDS: Final = 1
UNAVAILABLE_RETRY_AFTER_SECONDS: Final = 5


def create_status_server(config: Config, network: StatusServerConfig) -> ThreadingHTTPServer:
    """Create, but do not start, a configured status server.

    The factory permits port ``0`` only for ephemeral test servers. Environment
    startup rejects it because production role endpoints use the fixed internal
    port 8650 by default.
    """

    _validate_startup_config(config, network)
    handler = _make_handler(config)
    return ThreadingHTTPServer((network.bind, network.port), handler)


def serve(config: Config, network: StatusServerConfig) -> None:
    """Run the server until its owner calls ``shutdown`` or the process stops."""

    server = create_status_server(config, network)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    """CLI entry point reserved for the T04 role-wrapper supervisor."""

    parser = argparse.ArgumentParser(prog="sdlc-status-server")
    parser.parse_args(argv)
    try:
        config = Config.from_env()
        network = StatusServerConfig.from_env()
        serve(config, network)
    except ConfigError:
        # Configuration errors are intentionally concise: environment values
        # can include secrets and must never reach a role status response/log.
        return 2
    return 0


def _validate_startup_config(config: Config, network: StatusServerConfig) -> None:
    if config.role not in VALID_ROLES:
        raise ConfigError("ORCHESTRATOR_ROLE must be a canonical role")
    if type(network.port) is not int or not 0 <= network.port <= 65_535:
        raise ConfigError("ORCHESTRATOR_STATUS_PORT must be from 1 to 65535")
    # ``StatusServerConfig.from_env`` performs the same validation for CLI use;
    # repeat it for callers constructing the dataclass directly.
    from .config import _validate_status_bind

    _validate_status_bind(network.bind)


def _make_handler(config: Config) -> type[BaseHTTPRequestHandler]:
    class StatusHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            if self.path == "/health":
                self._send_json(HTTPStatus.OK, {"status": "ok", "role": config.role})
                return
            if self.path == "/status":
                self._send_status_snapshot()
                return
            self._send_json(HTTPStatus.NOT_FOUND, _error_payload("not_found"))

        def do_STATUS_METHOD_NOT_ALLOWED(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            self._method_not_allowed()

        def parse_request(self) -> bool:
            """Convert every syntactically valid non-GET request into 405.

            BaseHTTPRequestHandler otherwise produces its identifying 501 page
            for unknown methods, which would violate the narrow JSON contract.
            """

            parsed = super().parse_request()
            if parsed and self.command != "GET":
                self.command = "STATUS_METHOD_NOT_ALLOWED"
            return parsed

        def _send_status_snapshot(self) -> None:
            try:
                self._send_json(HTTPStatus.OK, read_role_status_snapshot(config))
            except StatusSnapshotError as exc:
                status, payload, retry_after = _snapshot_error_response(exc.code)
                self._send_json(status, payload, retry_after=retry_after)
            except Exception:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, _error_payload("status_read_failed"))

        def _method_not_allowed(self) -> None:
            self._send_json(
                HTTPStatus.METHOD_NOT_ALLOWED,
                _error_payload("method_not_allowed"),
                allow="GET",
            )

        def _send_json(
            self,
            status: HTTPStatus,
            payload: dict[str, object],
            *,
            allow: str | None = None,
            retry_after: int | None = None,
        ) -> None:
            try:
                body = _encode_json(payload)
            except ValueError:
                status = HTTPStatus.INTERNAL_SERVER_ERROR
                body = _encode_json(_error_payload("status_read_failed"))
                allow = None
                retry_after = None

            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Pragma", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.send_header("Connection", "close")
            if allow is not None:
                self.send_header("Allow", allow)
            if retry_after is not None:
                self.send_header("Retry-After", str(retry_after))
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True

        def send_response(self, code: int, message: str | None = None) -> None:
            """Write the status line and date without BaseHTTP's Server banner."""

            self.log_request(code)
            self.send_response_only(code, message)
            self.send_header("Date", self.date_time_string())

        def log_message(self, _format: str, *args: object) -> None:
            """Never log request targets or request-controlled data."""

    return StatusHandler


def _encode_json(payload: dict[str, object]) -> bytes:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("response exceeds bound")
    return body


def _error_payload(code: str) -> dict[str, object]:
    return {"error": {"code": code}}


def _snapshot_error_response(code: str) -> tuple[HTTPStatus, dict[str, object], int | None]:
    """Map T02's typed errors without exposing paths, SQL, or exception detail."""

    if code == "sqlite_busy":
        return HTTPStatus.SERVICE_UNAVAILABLE, _error_payload("sqlite_busy"), SQLITE_BUSY_RETRY_AFTER_SECONDS
    if code in {"missing_database", "schema_incompatible"}:
        return HTTPStatus.SERVICE_UNAVAILABLE, _error_payload("status_unavailable"), UNAVAILABLE_RETRY_AFTER_SECONDS
    return HTTPStatus.INTERNAL_SERVER_ERROR, _error_payload("status_read_failed"), None


if __name__ == "__main__":
    raise SystemExit(main())
