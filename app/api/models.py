"""Model registry endpoints: CRUD plus on-demand health checks."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.config import get_settings
from app.models.model_config import HealthCheckResult, ModelConfig
from app.security.secrets import safe_error
from app.security.validation import EndpointValidationError, validate_endpoint
from app.services.inference_client import InferenceClient
from app.storage.repositories import ModelRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["models"])


class ModelHealthResponse(BaseModel):
    model_id: str
    ok: bool
    checked_at: datetime
    latency_ms: float | None = None
    model_identifier_reported: str | None = None
    api_compatible: bool = False
    error: str | None = None


def _repo() -> ModelRepository:
    return ModelRepository()


def _validated_endpoint(endpoint: str) -> str:
    settings = get_settings()
    try:
        return validate_endpoint(endpoint, settings.endpoint_allowlist)
    except EndpointValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=safe_error(exc)
        ) from exc


@router.get("/models")
def list_models() -> list[dict]:
    """All registered models, credentials redacted."""
    return [m.public_dict() for m in _repo().list(include_disabled=True)]


@router.post("/models", status_code=status.HTTP_201_CREATED)
def create_model(config: ModelConfig) -> dict:
    if _repo().get(config.id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"model id {config.id!r} already exists",
        )
    config.endpoint = _validated_endpoint(config.endpoint)
    saved = _repo().upsert(config)
    logger.info("registered model %s -> %s", saved.id, safe_error(saved.endpoint))
    return saved.public_dict()


@router.put("/models/{model_id}")
def update_model(model_id: str, config: ModelConfig) -> dict:
    if _repo().get(model_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"model {model_id!r} not found"
        )
    config.id = model_id
    config.endpoint = _validated_endpoint(config.endpoint)
    return _repo().upsert(config).public_dict()


@router.delete("/models/{model_id}")
def delete_model(model_id: str) -> dict:
    if not _repo().delete(model_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"model {model_id!r} not found"
        )
    return {"deleted": model_id}


@router.post("/models/{model_id}/health", response_model=ModelHealthResponse)
def run_health_check(model_id: str) -> ModelHealthResponse:
    """Probe the endpoint with a real minimal chat request; persist the result.

    Always returns 200 with an ``ok`` flag; transport failures are reported in
    ``error`` (redacted via :func:`app.security.secrets.safe_error`).
    """
    cfg = _repo().get(model_id)
    if cfg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"model {model_id!r} not found"
        )
    try:
        result = InferenceClient(cfg, settings=get_settings()).health_check()
    except Exception as exc:  # noqa: BLE001 - surface a redacted error, never secrets
        logger.warning("health check failed for %s: %s", model_id, safe_error(exc))
        result = HealthCheckResult(
            model_id=model_id,
            ok=False,
            checked_at=datetime.now(UTC),
            api_compatible=False,
            error=safe_error(exc),
        )
    _repo().record_health(model_id, result.model_dump(mode="json"))
    return ModelHealthResponse(
        model_id=model_id,
        ok=result.ok,
        checked_at=result.checked_at,
        latency_ms=result.latency_ms,
        model_identifier_reported=result.model_identifier_reported,
        api_compatible=result.api_compatible,
        error=result.error,
    )
