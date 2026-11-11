"""HTTP client for OpenAI-compatible ``/chat/completions`` endpoints.

Every response body is treated as untrusted data: it is only parsed, never
executed, and all error text passes through
:func:`app.security.secrets.safe_error` so API keys never leak into logs.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime

import httpx

from app.config import Settings, get_settings
from app.models.model_config import HealthCheckResult, ModelConfig
from app.models.result import TokenUsage
from app.security.secrets import safe_error
from app.security.validation import request_with_safe_redirects, validate_endpoint

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 1.0

HEALTH_PROBE_MESSAGE = "Reply with the single word: OK"
HEALTH_MAX_TOKENS = 200  # generous: reasoning models spend tokens before the answer


class InferenceError(RuntimeError):
    """A request to the inference endpoint failed (after retries) or was malformed."""


@dataclass
class CompletionResult:
    """The measured outcome of one chat completion request."""

    content: str
    raw: dict
    latency_ms: float
    time_to_first_token_ms: float | None
    token_usage: TokenUsage
    model_reported: str | None
    finish_reason: str | None
    request_attempt: int


def _int_or_none(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class InferenceClient:
    """Retrying, allowlist-checked client for one registered model endpoint."""

    def __init__(
        self,
        model: ModelConfig,
        allowlist: list[str] | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.model = model
        self.settings = settings or get_settings()
        self.allowlist = (
            list(allowlist) if allowlist is not None else list(self.settings.endpoint_allowlist)
        )
        self.endpoint = validate_endpoint(model.endpoint, self.allowlist)
        #: Capability findings from the last :meth:`health_check`. ``HealthCheckResult``
        #: has no fields for these; the API layer merges this dict into the payload
        #: it passes to ``ModelRepository.record_health``.
        self.capabilities: dict[str, bool | None] = {
            "supports_streaming": None,
            "reports_token_usage": None,
        }

    # -- request plumbing -------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.model.api_key:
            headers["Authorization"] = f"Bearer {self.model.api_key}"
        headers.update(self.model.extra_headers)
        return headers

    def _post_json(self, payload: dict) -> dict:
        """One request attempt. Redirects only via ``request_with_safe_redirects``."""
        with httpx.Client(timeout=self.model.timeout_seconds) as client:
            response = request_with_safe_redirects(
                client,
                "POST",
                f"{self.endpoint}/chat/completions",
                self.allowlist,
                json=payload,
                headers=self._headers(),
            )
        if response.status_code >= 400:
            body = safe_error(response.text[:500])
            raise InferenceError(f"endpoint returned HTTP {response.status_code}: {body}")
        try:
            data = response.json()
        except ValueError as exc:
            raise InferenceError("endpoint returned a non-JSON body") from exc
        if not isinstance(data, dict):
            raise InferenceError("endpoint returned a non-object JSON payload")
        return data

    def chat(self, messages: list[dict], generation_params: dict | None = None) -> CompletionResult:
        """POST ``/chat/completions`` with retries on timeout/connect errors."""
        payload: dict = {"model": self.model.model_identifier, "messages": list(messages)}
        payload.update({**self.model.generation_params, **(generation_params or {})})

        start = time.perf_counter()
        last_error: BaseException | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                data = self._post_json(payload)
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_error = exc
                if attempt < MAX_ATTEMPTS:
                    time.sleep(RETRY_BACKOFF_SECONDS)
                    continue
                raise InferenceError(
                    f"inference failed after {MAX_ATTEMPTS} attempts: {safe_error(exc)}"
                ) from exc
            except InferenceError:
                raise
            except Exception as exc:  # unexpected transport/decoding failure
                raise InferenceError(f"inference request failed: {safe_error(exc)}") from exc

            latency_ms = (time.perf_counter() - start) * 1000
            return self._parse_completion(data, latency_ms, attempt)

        raise InferenceError(
            "inference failed: "
            f"{safe_error(last_error if last_error else RuntimeError('no attempt'))}"
        )

    def _parse_completion(self, data: dict, latency_ms: float, attempt: int) -> CompletionResult:
        choices = data.get("choices")
        message = choices[0].get("message") if isinstance(choices, list) and choices else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise InferenceError("response is missing choices[0].message.content")

        usage = TokenUsage()
        raw_usage = data.get("usage")
        if isinstance(raw_usage, dict):
            prompt_tokens = _int_or_none(raw_usage.get("prompt_tokens"))
            completion_tokens = _int_or_none(raw_usage.get("completion_tokens"))
            total_tokens = _int_or_none(raw_usage.get("total_tokens"))
            if any(v is not None for v in (prompt_tokens, completion_tokens, total_tokens)):
                usage = TokenUsage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    source="measured",
                )

        finish_reason = None
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            finish_reason = choices[0].get("finish_reason")
        model_reported = data.get("model") if isinstance(data.get("model"), str) else None

        return CompletionResult(
            content=content,
            raw=data,
            latency_ms=latency_ms,
            # Time-to-first-token is only observable on streamed responses.
            time_to_first_token_ms=None,
            token_usage=usage,
            model_reported=model_reported,
            finish_reason=finish_reason if isinstance(finish_reason, str) else None,
            request_attempt=attempt,
        )

    # -- health ------------------------------------------------------------

    def health_check(self) -> HealthCheckResult:
        """Real chat request plus a streaming probe. No secrets in error text."""
        ok = False
        api_compatible = False
        error: str | None = None
        model_reported: str | None = None
        latency_ms: float | None = None
        reports_token_usage: bool | None = None

        try:
            result = self.chat(
                [{"role": "user", "content": HEALTH_PROBE_MESSAGE}],
                {"max_tokens": HEALTH_MAX_TOKENS},
            )
            latency_ms = result.latency_ms
            ok = True
            api_compatible = True
            model_reported = result.model_reported
            reports_token_usage = result.token_usage.source == "measured"
        except InferenceError as exc:
            error = safe_error(exc)

        supports_streaming = self._probe_streaming() if ok else None
        self.capabilities = {
            "supports_streaming": supports_streaming,
            "reports_token_usage": reports_token_usage,
        }

        detail = None
        if ok:
            stream_txt = {True: "yes", False: "no", None: "unknown"}[supports_streaming]
            usage_txt = {True: "measured", False: "absent", None: "unknown"}[reports_token_usage]
            detail = f"chat OK; streaming: {stream_txt}; token usage: {usage_txt}"
        return HealthCheckResult(
            model_id=self.model.id,
            ok=ok,
            checked_at=datetime.utcnow(),
            latency_ms=latency_ms,
            model_identifier_reported=model_reported,
            api_compatible=api_compatible,
            error=error,
            detail=detail,
        )

    def _probe_streaming(self) -> bool | None:
        """One streaming request. True/False/None (unknown); never raises."""
        payload = {
            "model": self.model.model_identifier,
            "messages": [{"role": "user", "content": HEALTH_PROBE_MESSAGE}],
            "stream": True,
            "max_tokens": HEALTH_MAX_TOKENS,
        }
        try:
            # Stream probes skip redirect handling: a redirect is reported as
            # unknown rather than followed outside the validated helper.
            with (
                httpx.Client(timeout=self.model.timeout_seconds) as client,
                client.stream(
                    "POST",
                    f"{self.endpoint}/chat/completions",
                    json=payload,
                    headers=self._headers(),
                    follow_redirects=False,
                ) as response,
            ):
                if response.status_code >= 400:
                    return False
                if response.headers.get("location"):
                    return None
                if response.status_code != 200:
                    return None
                for line in response.iter_lines():
                    if line and line.strip():
                        return True
            return None
        except (httpx.TimeoutException, httpx.ConnectError):
            return None
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("stream probe failed: %s", safe_error(exc))
            return None
