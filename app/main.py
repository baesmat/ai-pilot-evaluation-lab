"""FastAPI application factory and ASGI entry point (``uvicorn app.main:app``)."""

from __future__ import annotations

import logging
import re
import subprocess
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import APP_NAME, __version__
from app.api import evaluations, governance, models, reports, results
from app.config import get_settings
from app.storage.database import init_engine

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def git_commit() -> str | None:
    """Best-effort HEAD sha; None outside a git checkout or without git."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=_REPO_ROOT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    commit = proc.stdout.strip()
    return commit or None


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-")[:64] or "bootstrap-model"


def _bootstrap_model_from_env() -> None:
    """Record the env-configured model if the registry is empty. No network I/O."""
    settings = get_settings()
    if not (settings.llm_base_url and settings.llm_model):
        return
    from app.storage.repositories import ModelRepository

    repo = ModelRepository()
    if repo.list(include_disabled=True):
        return
    from app.models.model_config import ModelConfig
    from app.security.validation import EndpointValidationError, validate_endpoint

    try:
        endpoint = validate_endpoint(settings.llm_base_url, settings.endpoint_allowlist)
    except EndpointValidationError as exc:
        logger.warning("bootstrap model endpoint invalid, skipping: %s", exc)
        return
    cfg = ModelConfig(
        id=_slug(settings.llm_model),
        display_name=f"{settings.llm_model} (bootstrap)",
        model_identifier=settings.llm_model,
        endpoint=endpoint,
        api_key=settings.llm_api_key,
        timeout_seconds=settings.llm_timeout_seconds,
        extra_headers=dict(settings.llm_extra_headers),
    )
    repo.upsert(cfg)
    logger.info("bootstrapped model record %s from environment", cfg.id)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    init_engine(settings.database_url)
    _bootstrap_model_from_env()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=APP_NAME,
        version=__version__,
        lifespan=lifespan,
        description="Independent technology demonstration - not affiliated with any institution.",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(models.router)
    application.include_router(results.router)
    application.include_router(evaluations.router)
    application.include_router(reports.router)
    application.include_router(governance.router)

    @application.get("/api/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok", "version": __version__, "git_commit": git_commit()}

    @application.get("/api/app-info", tags=["meta"])
    def app_info() -> dict:
        return {
            "name": APP_NAME,
            "version": __version__,
            "git_commit": git_commit(),
            "api_prefix": "/api",
            "docs_url": "/docs",
            "frontend_origin": settings.frontend_origin,
        }

    return application


app = create_app()
