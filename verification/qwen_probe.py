#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "verification" / "config" / "models.qwen.yaml"


def load_models() -> list[str]:
    data = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    models = list(data["runtime_roles"].values()) + list(data["verification_roles"].values())
    return sorted(set(models))


def probe(base_url: str, api_key: str, model: str, timeout: int) -> None:
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": "HermeTeam E2E readiness probe. Reply with exactly READY.",
                }
            ],
            "temperature": 0,
            "max_tokens": 16,
        }
    ).encode("utf-8")
    req = Request(
        base_url.rstrip("/") + "/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"{model}: HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"{model}: API unavailable: {exc}") from exc

    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError(f"{model}: response contains no choices")
    content = str((choices[0].get("message") or {}).get("content") or "").strip()
    if not content:
        raise RuntimeError(f"{model}: empty response")
    print(f"Qwen probe PASS: {model}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", action="append", help="Probe only the supplied model id; repeatable.")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    api_key = os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        print("QWEN_API_KEY (or DASHSCOPE_API_KEY) is required", file=sys.stderr)
        return 2
    base_url = os.getenv("QWEN_API_BASE_URL") or "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    for model in args.model or load_models():
        probe(base_url, api_key, model, args.timeout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
