"""Domain models for registered inference endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

HostingType = Literal["local", "hosted"]


class ModelConfig(BaseModel):
    """A registered model endpoint. Credentials never appear in reports."""

    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9._-]+$")
    display_name: str = Field(min_length=1, max_length=120)
    provider: str = "OpenAI Compatible"
    model_identifier: str = Field(min_length=1)
    endpoint: str = Field(min_length=1)
    #: Bearer token / API key for hosted endpoints. Redacted in all outputs.
    api_key: str | None = None
    hosting_type: HostingType = "local"
    context_window: int | None = None
    input_cost_per_million_tokens: float | None = None
    output_cost_per_million_tokens: float | None = None
    currency: str = "USD"
    enabled: bool = True
    timeout_seconds: int = Field(default=120, ge=1, le=600)
    max_concurrent_requests: int = Field(default=1, ge=1, le=8)
    generation_params: dict[str, Any] = Field(default_factory=dict)
    #: Extra static headers (e.g. access-proxy auth). Redacted in outputs.
    extra_headers: dict[str, str] = Field(default_factory=dict)
    #: Explicit capability declaration; health checks may refine these.
    supports_streaming: bool | None = None
    reports_token_usage: bool | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_health_check: dict[str, Any] | None = None

    @field_validator("endpoint")
    @classmethod
    def _endpoint_has_scheme(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("endpoint must be an http(s) URL")
        return v

    def public_dict(self) -> dict[str, Any]:
        """Representation safe for logs, reports and API responses."""
        data = self.model_dump(mode="json")
        data["extra_headers"] = {
            k: (
                "********"
                if "key" in k.lower() or "secret" in k.lower() or "token" in k.lower()
                else v
            )
            for k, v in self.extra_headers.items()
        }
        return data


class HealthCheckResult(BaseModel):
    model_id: str
    ok: bool
    checked_at: datetime
    latency_ms: float | None = None
    model_identifier_reported: str | None = None
    api_compatible: bool = False
    error: str | None = None
    detail: str | None = None
