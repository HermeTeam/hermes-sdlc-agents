"""Fixed-model OpenAI-compatible relay for an operator-provisioned HermeTeam subscription.

The Builder and capability judge know only an internal relay credential. The
upstream subscription token and provider/model selection belong exclusively to
this service, in an operator-provisioned Docker secret and config file.
"""
from __future__ import annotations

import hmac
import http.client
import json
import os
import ssl
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

PUBLIC_MODEL = "hermeteam-subscribed"
MAX_REQUEST_BYTES = 2 * 1024 * 1024
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_STREAM_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True)
class RelayConfig:
    base_url: str
    upstream_model: str
    upstream_token: str
    internal_key: str

    @classmethod
    def from_environment(cls) -> "RelayConfig":
        token_file = Path(os.environ.get("SMB_SUBSCRIPTION_TOKEN_FILE", "/run/secrets/smb_subscription_token"))
        if not token_file.is_file():
            raise RuntimeError("operator-provisioned subscription token secret is missing")
        config = cls(
            base_url=os.environ.get("SMB_SUBSCRIPTION_BASE_URL", "").strip().rstrip("/"),
            upstream_model=os.environ.get("SMB_SUBSCRIPTION_MODEL", "").strip(),
            upstream_token=token_file.read_text(encoding="utf-8").strip(),
            internal_key=os.environ.get("SMB_MODEL_RELAY_KEY", "").strip(),
        )
        config.validate()
        return config

    def validate(self) -> None:
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not parsed.path.endswith("/v1")
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise RuntimeError("subscription Base URL must be an operator-provisioned HTTPS /v1 endpoint")
        if not self.upstream_model or len(self.upstream_model) > 150:
            raise RuntimeError("subscription model must be provisioned by HermeTeam")
        if len(self.upstream_token) < 16 or len(self.internal_key) < 32:
            raise RuntimeError("subscription or internal relay credential missing")


def normalize_request(body: bytes, *, upstream_model: str) -> bytes:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid JSON body") from exc
    if not isinstance(value, dict) or value.get("model") != PUBLIC_MODEL:
        raise ValueError("only the subscription-assigned model route is available")
    if not isinstance(value.get("messages"), list) or not value["messages"]:
        raise ValueError("messages must be a nonempty array")
    value["model"] = upstream_model
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def make_handler(config: RelayConfig):
    class Handler(BaseHTTPRequestHandler):
        server_version = "HermeTeamSubscriptionRelay/1.0"
        protocol_version = "HTTP/1.1"

        def log_message(self, _format: str, *_args: object) -> None:
            # Never log prompts, secrets, provider errors or authorization headers.
            return

        def reply(self, status: int, payload: dict[str, str]) -> None:
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:  # noqa: N802
            if self.path != "/health":
                return self.reply(404, {"error": "not_found"})
            self.reply(200, {"status": "ok", "model": PUBLIC_MODEL})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/v1/chat/completions":
                return self.reply(404, {"error": "not_found"})
            if not hmac.compare_digest(
                self.headers.get("Authorization", ""),
                "Bearer " + config.internal_key,
            ):
                return self.reply(401, {"error": "unauthorized"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length < 1 or length > MAX_REQUEST_BYTES:
                return self.reply(413, {"error": "invalid_request_size"})
            try:
                outbound_body = normalize_request(
                    self.rfile.read(length), upstream_model=config.upstream_model
                )
            except ValueError:
                return self.reply(400, {"error": "invalid_subscription_model_or_request"})

            upstream = urlsplit(config.base_url)
            connection = http.client.HTTPSConnection(
                upstream.hostname,
                upstream.port or 443,
                timeout=120,
                context=ssl.create_default_context(),
            )
            try:
                connection.request(
                    "POST",
                    upstream.path.rstrip("/") + "/chat/completions",
                    body=outbound_body,
                    headers={
                        "Authorization": "Bearer " + config.upstream_token,
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream",
                        "Accept-Encoding": "identity",
                        "User-Agent": "HermeTeam-Subscription-Relay/1.0",
                    },
                )
                upstream_response = connection.getresponse()
                content_type = (upstream_response.getheader("Content-Type") or "").lower()
                if upstream_response.status != 200:
                    # Never return provider error bodies to the agent.
                    return self.reply(502, {"error": "subscription_upstream_unavailable"})
                if content_type.startswith("text/event-stream"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    total = 0
                    while True:
                        chunk = upstream_response.read(16 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > MAX_STREAM_BYTES:
                            break
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    self.close_connection = True
                    return
                if not content_type.startswith("application/json"):
                    return self.reply(502, {"error": "unsupported_subscription_response"})
                raw = upstream_response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    return self.reply(502, {"error": "subscription_response_too_large"})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            except (OSError, http.client.HTTPException):
                # No hostnames, credentials or prompts in errors.
                try:
                    self.reply(502, {"error": "subscription_upstream_unavailable"})
                except OSError:
                    pass
            finally:
                connection.close()

    return Handler


def main() -> None:
    config = RelayConfig.from_environment()
    ThreadingHTTPServer(("0.0.0.0", 8085), make_handler(config)).serve_forever()


if __name__ == "__main__":
    main()
