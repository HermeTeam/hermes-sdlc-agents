from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import Config


class HermesClient:
    def __init__(self, config: Config) -> None:
        self._base_url = config.hermes_url
        self._api_key = config.api_server_key

    def submit_run(self, *, model: str, session_id: str, prompt: str, idempotency_key: str) -> dict:
        body = json.dumps({"model": model, "session_id": session_id, "input": prompt}).encode("utf-8")
        request = Request(
            f"{self._base_url}/v1/runs",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Idempotency-Key": idempotency_key,
            },
        )
        return self._json(request)

    def get_run(self, run_id: str) -> dict:
        request = Request(
            f"{self._base_url}/v1/runs/{run_id}",
            headers={"Authorization": f"Bearer {self._api_key}", "Accept": "application/json"},
        )
        return self._json(request)

    def _json(self, request: Request) -> dict:
        try:
            with urlopen(request, timeout=30) as response:
                if response.status == 204:
                    return {}
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Hermes API request failed: HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError) as exc:
            raise RuntimeError(f"Hermes API request failed: {exc}") from exc


def extract_run_id(response: dict) -> str:
    for key in ("id", "run_id"):
        value = response.get(key)
        if value:
            return str(value)
    raise RuntimeError("Hermes /v1/runs response did not contain id or run_id")
