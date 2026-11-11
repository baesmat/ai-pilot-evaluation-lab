"""Application configuration.

All configuration is environment-driven. No secrets are stored in code; the
`.env.example` file documents every supported variable. Values are read once
at import time by :func:`get_settings`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name, "")
    if not raw:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    """Immutable runtime settings resolved from the environment."""

    app_name: str = "AI Pilot Evaluation Lab"
    version: str = "0.1.0"

    host: str = "127.0.0.1"
    port: int = 8310
    data_dir: Path = Path("./data")
    frontend_origin: str = "http://127.0.0.1:8501"

    #: Hosts the application may contact for inference (SSRF allowlist).
    endpoint_allowlist: list[str] = field(
        default_factory=lambda: _env_list("ENDPOINT_ALLOWLIST", ["127.0.0.1", "localhost"])
    )

    #: Optional bootstrap model, for CLI-first setups. The registry is
    #: authoritative once the application runs; this only seeds convenience.
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_timeout_seconds: int = 120
    llm_extra_headers: dict[str, str] = field(default_factory=dict)

    @property
    def database_path(self) -> Path:
        return self.data_dir / "evaluation_lab.db"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"


def get_settings() -> Settings:
    data_dir = Path(os.getenv("APP_DATA_DIR", "./data")).expanduser().resolve()
    extra_headers: dict[str, str] = {}
    raw_headers = os.getenv("LLM_EXTRA_HEADERS", "").strip()
    if raw_headers:
        try:
            parsed = json.loads(raw_headers)
            if isinstance(parsed, dict):
                extra_headers = {str(k): str(v) for k, v in parsed.items()}
        except json.JSONDecodeError:
            # Malformed header JSON is a configuration error, not fatal:
            # proceed without extra headers rather than crashing startup.
            pass

    return Settings(
        host=os.getenv("APP_HOST", "127.0.0.1"),
        port=_env_int("APP_PORT", 8310),
        data_dir=data_dir,
        frontend_origin=os.getenv("APP_FRONTEND_ORIGIN", "http://127.0.0.1:8501"),
        endpoint_allowlist=_env_list("ENDPOINT_ALLOWLIST", ["127.0.0.1", "localhost"]),
        llm_base_url=os.getenv("LLM_BASE_URL") or None,
        llm_model=os.getenv("LLM_MODEL") or None,
        llm_api_key=os.getenv("LLM_API_KEY") or None,
        llm_timeout_seconds=_env_int("LLM_TIMEOUT_SECONDS", 120),
        llm_extra_headers=extra_headers,
    )
