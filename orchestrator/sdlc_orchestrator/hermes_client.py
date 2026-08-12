from __future__ import annotations

import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import Config


class HermesRunNotFound(RuntimeError):
    def __init__(self, run_id: str, detail: str) -> None:
        super().__init__(f"Hermes run not found: {run_id}: {detail}")
        self.run_id = run_id
        self.detail = detail


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
        return self._json(request, missing_run_id=run_id)

    def repair_final_response(
        self,
        *,
        model: str,
        session_id: str,
        prompt: str,
        idempotency_key: str,
        timeout_seconds: int,
    ) -> dict:
        submitted = self.submit_run(model=model, session_id=session_id, prompt=prompt, idempotency_key=idempotency_key)
        repair_run_id = extract_run_id(submitted)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() <= deadline:
            payload = self.get_run(repair_run_id)
            status = str(payload.get("status") or payload.get("state") or "").lower()
            if status in {"completed", "succeeded", "success", "done"}:
                return payload
            if status in {"failed", "error", "cancelled", "canceled"}:
                raise RuntimeError(f"Repair run ended with status {status}: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}")
            time.sleep(2)
        raise TimeoutError(f"Repair run timed out after {timeout_seconds} seconds")

    def _json(self, request: Request, *, missing_run_id: str | None = None) -> dict:
        try:
            with urlopen(request, timeout=30) as response:
                if response.status == 204:
                    return {}
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code == 404 and missing_run_id is not None and "run_not_found" in detail:
                raise HermesRunNotFound(missing_run_id, detail) from exc
            raise RuntimeError(f"Hermes API request failed: HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError) as exc:
            raise RuntimeError(f"Hermes API request failed: {exc}") from exc


def extract_run_id(response: dict) -> str:
    for key in ("id", "run_id"):
        value = response.get(key)
        if value:
            return str(value)
    raise RuntimeError("Hermes /v1/runs response did not contain id or run_id")
