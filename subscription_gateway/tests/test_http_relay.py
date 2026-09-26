from __future__ import annotations

import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from subscription_gateway.server import PUBLIC_MODEL, RelayConfig, make_handler


class FakeConnection:
    requests: list[tuple[str, str, bytes, dict[str, str]]] = []

    def __init__(self, *_args, **_kwargs) -> None:
        return

    def request(self, method: str, url: str, body: bytes, headers: dict[str, str]) -> None:
        self.requests.append((method, url, body, headers))

    def getresponse(self):
        class Response:
            status = 200

            def getheader(self, name: str) -> str | None:
                return "application/json" if name.lower() == "content-type" else None

            def read(self, _limit: int) -> bytes:
                return b'{"choices":[{"message":{"role":"assistant","content":"READY"}}]}'

        return Response()

    def close(self) -> None:
        return


class SubscriptionHTTPBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeConnection.requests = []
        self.config = RelayConfig(
            "https://operator-provisioned.example.org/v1",
            "upstream-fixed-model",
            "upstream-only-token-123456789",
            "local-only-key-" + "z" * 64,
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.config))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.stub = patch("subscription_gateway.server.http.client.HTTPSConnection", FakeConnection)
        self.stub.start()
        self.addCleanup(self.stub.stop)

    def stop_server(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def send(self, *, token: str, model: str = PUBLIC_MODEL) -> dict:
        payload = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": "safe canary"}],
            "stream": False,
        }).encode()
        req = Request(
            f"http://127.0.0.1:{self.server.server_address[1]}/v1/chat/completions",
            data=payload,
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
            },
        )
        with urlopen(req, timeout=5) as res:
            return json.load(res)

    def test_bad_internal_auth_does_not_contact_subscribed_provider(self) -> None:
        with self.assertRaises(HTTPError) as caught:
            self.send(token="incorrect-token")
        self.assertEqual(caught.exception.code, 401)
        self.assertEqual(FakeConnection.requests, [])

    def test_other_model_is_denied_before_provider_call(self) -> None:
        with self.assertRaises(HTTPError) as caught:
            self.send(token=self.config.internal_key, model="different-provider-model")
        self.assertEqual(caught.exception.code, 400)
        self.assertEqual(FakeConnection.requests, [])

    def test_provider_token_stays_upstream_and_model_is_subscription_fixed(self) -> None:
        output = self.send(token=self.config.internal_key)
        self.assertEqual(output["choices"][0]["message"]["content"], "READY")
        self.assertEqual(len(FakeConnection.requests), 1)
        method, url, body, headers = FakeConnection.requests[0]
        self.assertEqual((method, url), ("POST", "/v1/chat/completions"))
        self.assertEqual(headers["Authorization"], "Bearer " + self.config.upstream_token)
        self.assertNotIn(self.config.internal_key, json.dumps(headers))
        self.assertEqual(json.loads(body)["model"], "upstream-fixed-model")
        self.assertNotIn(self.config.upstream_token, json.dumps(output))


if __name__ == "__main__":
    unittest.main()
