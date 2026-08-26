from __future__ import annotations

import http.client
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sdlc_orchestrator.config import Config, ConfigError, StatusServerConfig
from sdlc_orchestrator.db import connect, ensure_assignment, init_db, upsert_work_item
from sdlc_orchestrator.provider_base import WorkItem
from sdlc_orchestrator.status_server import (
    MAX_RESPONSE_BYTES,
    create_status_server,
)
from sdlc_orchestrator.status_snapshot import StatusSnapshotError


def make_config(path: Path, *, role: str = "builder", enabled: bool = True) -> Config:
    return Config(
        enabled=enabled,
        role=role,
        provider="github",
        repository_id="org/repository",
        hermes_url="http://127.0.0.1:8642",
        api_server_key="test-api-key-must-not-leak",
        db_path=path,
        lock_path=path.with_suffix(".lock"),
        max_starts_per_tick=1,
        run_timeout_seconds=5400,
    )


def add_assignment(path: Path, *, title: str = "Планирование") -> None:
    item = WorkItem(
        provider="github",
        repository_id="org/repository",
        kind="issue",
        external_id="1",
        title=title,
        body="canary-secret request body",
        body_hash="canary-hash",
        url="https://github.com/org/repository/issues/1",
        labels=("hermes:builder",),
        assignees=("hermes-builder",),
        updated_at="2026-08-26T00:00:00Z",
    )
    with connect(path) as database:
        init_db(database)
        item_id = upsert_work_item(database, item)
        ensure_assignment(database, "assignment-1", item_id, "builder")


class RunningStatusServer:
    def __init__(self, config: Config) -> None:
        self.server = create_status_server(config, StatusServerConfig(bind="127.0.0.1", port=0))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def address(self) -> tuple[str, int]:
        host, port = self.server.server_address[:2]
        return str(host), int(port)

    def __enter__(self) -> "RunningStatusServer":
        self.thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method: str, path: str, body: bytes | None = None) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection(*self.address, timeout=2)
        try:
            connection.request(method, path, body=body, headers={"Content-Type": "text/plain"} if body else {})
            response = connection.getresponse()
            return response.status, {name.lower(): value for name, value in response.getheaders()}, response.read()
        finally:
            connection.close()


class StatusServerTests(unittest.TestCase):
    def test_health_and_status_are_valid_utf8_json_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "orchestrator.sqlite"
            add_assignment(path)
            with RunningStatusServer(make_config(path)) as service:
                status, headers, body = service.request("GET", "/health")
                self.assertEqual(status, 200)
                self.assertEqual(headers["content-type"], "application/json; charset=utf-8")
                self.assertEqual(json.loads(body), {"status": "ok", "role": "builder"})

                status, headers, body = service.request("GET", "/status")
                self.assertEqual(status, 200)
                self.assertEqual(headers["content-type"], "application/json; charset=utf-8")
                self.assertEqual(json.loads(body)["items"][0]["workItem"]["title"], "Планирование")
                self.assertIn("Планирование".encode("utf-8"), body)

    def test_only_supported_routes_and_get_method_are_available(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "orchestrator.sqlite"
            add_assignment(path)
            with RunningStatusServer(make_config(path)) as service:
                status, _, body = service.request("GET", "/not-a-route?token=canary-secret")
                self.assertEqual(status, 404)
                self.assertEqual(json.loads(body), {"error": {"code": "not_found"}})

                status, headers, body = service.request("HEAD", "/status", b"canary-body")
                self.assertEqual(status, 405)
                self.assertEqual(headers["allow"], "GET")
                # http.client correctly suppresses a response body for HEAD;
                # the handler still emits its bounded JSON representation.
                self.assertEqual(body, b"")

                for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "BREW"):
                    status, headers, body = service.request(method, "/status", b"canary-body")
                    self.assertEqual(status, 405, method)
                    self.assertEqual(headers["allow"], "GET")
                    self.assertEqual(json.loads(body), {"error": {"code": "method_not_allowed"}})
                    self.assertNotIn(b"canary-body", body)

    def test_security_headers_banner_and_response_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "orchestrator.sqlite"
            add_assignment(path, title="canary-secret")
            with RunningStatusServer(make_config(path)) as service:
                status, headers, body = service.request("GET", "/status")
            self.assertEqual(status, 200)
            self.assertLessEqual(len(body), MAX_RESPONSE_BYTES)
            self.assertEqual(headers["cache-control"], "no-store")
            self.assertEqual(headers["x-content-type-options"], "nosniff")
            self.assertEqual(headers["x-frame-options"], "DENY")
            self.assertEqual(headers["referrer-policy"], "no-referrer")
            self.assertNotIn("access-control-allow-origin", headers)
            self.assertNotIn("server", headers)
            self.assertNotIn(b"test-api-key-must-not-leak", body)
            self.assertNotIn(b"canary-secret request body", body)
            self.assertNotIn(b"canary-hash", body)

    def test_snapshot_errors_have_bounded_classifications(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "orchestrator.sqlite"
            with RunningStatusServer(make_config(path)) as service:
                status, headers, body = service.request("GET", "/status")
                self.assertEqual(status, 503)
                self.assertEqual(headers["retry-after"], "5")
                self.assertEqual(json.loads(body), {"error": {"code": "status_unavailable"}})

            sqlite3.connect(path).close()
            with RunningStatusServer(make_config(path)) as service:
                status, headers, body = service.request("GET", "/status")
                self.assertEqual(status, 503)
                self.assertEqual(headers["retry-after"], "5")
                self.assertEqual(json.loads(body), {"error": {"code": "status_unavailable"}})

            add_assignment(path)
            with patch(
                "sdlc_orchestrator.status_server.read_role_status_snapshot",
                side_effect=StatusSnapshotError("sqlite_busy"),
            ):
                with RunningStatusServer(make_config(path)) as service:
                    status, headers, body = service.request("GET", "/status")
            self.assertEqual(status, 503)
            self.assertEqual(headers["retry-after"], "1")
            self.assertEqual(json.loads(body), {"error": {"code": "sqlite_busy"}})

    def test_unexpected_read_failure_is_bounded_without_detail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "orchestrator.sqlite"
            with patch(
                "sdlc_orchestrator.status_server.read_role_status_snapshot",
                side_effect=RuntimeError("database /private/path token=canary-secret"),
            ):
                with RunningStatusServer(make_config(path)) as service:
                    status, _, body = service.request("GET", "/status")
            self.assertEqual(status, 500)
            self.assertEqual(json.loads(body), {"error": {"code": "status_read_failed"}})
            self.assertNotIn(b"canary-secret", body)
            self.assertNotIn(b"/private/path", body)

    def test_sequential_and_concurrent_requests_complete_and_shutdown_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "orchestrator.sqlite"
            add_assignment(path)
            with RunningStatusServer(make_config(path)) as service:
                for _ in range(3):
                    self.assertEqual(service.request("GET", "/status")[0], 200)

                results: list[int] = []
                threads = [threading.Thread(target=lambda: results.append(service.request("GET", "/health")[0])) for _ in range(8)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=2)
                self.assertEqual(results, [200] * 8)

    def test_startup_rejects_invalid_role_port_and_bind(self) -> None:
        path = Path("/opt/data/sdlc-orchestrator/orchestrator.sqlite")
        with self.assertRaises(ConfigError):
            create_status_server(make_config(path, role="unknown"), StatusServerConfig(bind="127.0.0.1", port=0))
        with self.assertRaises(ConfigError):
            create_status_server(make_config(path), StatusServerConfig(bind="127.0.0.1", port=65_536))
        with self.assertRaises(ConfigError):
            create_status_server(make_config(path), StatusServerConfig(bind="status.internal", port=0))

    def test_environment_network_configuration_rejects_invalid_values(self) -> None:
        with patch.dict("os.environ", {"ORCHESTRATOR_STATUS_PORT": "0"}, clear=True):
            with self.assertRaises(ConfigError):
                StatusServerConfig.from_env()
        with patch.dict("os.environ", {"ORCHESTRATOR_STATUS_BIND": "localhost"}, clear=True):
            with self.assertRaises(ConfigError):
                StatusServerConfig.from_env()


if __name__ == "__main__":
    unittest.main()
