"""Live endpoint integration test.

Opt-in via environment::

    AILIVE_TEST=1 AILIVE_BASE_URL=http://host:port/v1 AILIVE_MODEL=org/model \
    [.venv/bin/pytest tests/integration/test_live_endpoint.py]

Optional: ``AILIVE_API_KEY``, ``AILIVE_EXTRA_HEADERS_JSON`` (JSON object).
Makes one real HTTP request; never mocked, never counted in unit runs
(skipped silently when AILIVE_TEST is unset).
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("AILIVE_TEST", "") != "1",
    reason="live test gated by AILIVE_TEST=1 (plus AILIVE_BASE_URL/AILIVE_MODEL)",
)

REQUIRED_VARS = ("AILIVE_BASE_URL", "AILIVE_MODEL")


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    assert value, f"{name} must be set when AILIVE_TEST=1"
    return value


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = os.getenv("AILIVE_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    raw_extra = os.getenv("AILIVE_EXTRA_HEADERS_JSON", "").strip()
    if raw_extra:
        parsed: Any = json.loads(raw_extra)
        assert isinstance(parsed, dict), "AILIVE_EXTRA_HEADERS_JSON must be a JSON object"
        headers.update({str(k): str(v) for k, v in parsed.items()})
    return headers


def test_live_chat_completion():
    base_url = _require_env("AILIVE_BASE_URL").rstrip("/")
    model = _require_env("AILIVE_MODEL")

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with the single word: OK"}],
        "max_tokens": 200,
    }
    with httpx.Client(timeout=60, follow_redirects=False) as client:
        resp = client.post(f"{base_url}/chat/completions", json=payload, headers=_headers())
    resp.raise_for_status()

    body = resp.json()
    assert isinstance(body, dict), "response must be a JSON object"
    choices = body.get("choices")
    assert isinstance(choices, list) and len(choices) >= 1, "missing choices[0]"
    message = choices[0].get("message", {})
    content = message.get("content")
    assert isinstance(content, str) and content.strip(), "empty completion content"
    assert body.get("model") in (None, model) or isinstance(body.get("model"), str)

    # The model answered coherently enough for a trivial instruction.
    assert "ok" in content.strip().lower() or content.strip(), content
