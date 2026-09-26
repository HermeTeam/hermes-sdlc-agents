from __future__ import annotations

import json
import unittest

from subscription_gateway.server import PUBLIC_MODEL, RelayConfig, normalize_request


class SubscriptionRelayTests(unittest.TestCase):
    def test_subscription_is_fixed_and_internal_alias_is_replaced(self) -> None:
        raw = json.dumps({"model": PUBLIC_MODEL, "messages": [{"role": "user", "content": "hi"}]}).encode()
        result = json.loads(normalize_request(raw, upstream_model="operator-selected-model"))
        self.assertEqual(result["model"], "operator-selected-model")

    def test_builder_cannot_select_another_provider_or_model(self) -> None:
        with self.assertRaisesRegex(ValueError, "subscription-assigned"):
            normalize_request(
                b'{"model":"arbitrary-other-model","messages":[{"role":"user","content":"x"}]}',
                upstream_model="operator-selected-model",
            )

    def test_missing_messages_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "messages"):
            normalize_request(b'{"model":"hermeteam-subscribed","messages":[]}', upstream_model="fixed")

    def test_subscription_endpoint_must_use_https(self) -> None:
        config = RelayConfig("http://example.org/v1", "fixed", "x" * 32, "y" * 32)
        with self.assertRaisesRegex(RuntimeError, "HTTPS"):
            config.validate()

    def test_operator_model_and_internal_key_are_required(self) -> None:
        config = RelayConfig("https://service.example.org/v1", "", "x" * 32, "y" * 32)
        with self.assertRaisesRegex(RuntimeError, "model"):
            config.validate()


if __name__ == "__main__":
    unittest.main()
