"""Evaluation run lifecycle: start, inspect, cancel."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.security.secrets import safe_error
from app.services.benchmark_runner import BenchmarkRunner, get_runner
from app.storage.repositories import RunRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/evaluations", tags=["evaluations"])


class StartRunRequest(BaseModel):
    model_id: str = Field(min_length=1)
    datasets: list[str] = Field(min_length=1)
    concurrency: int = Field(default=1, ge=1, le=4)
    generation_params: dict[str, Any] | None = None
    seed: int | None = None


def _runner() -> BenchmarkRunner:
    return get_runner()


def _repo() -> RunRepository:
    return RunRepository()


def _get_run_or_404(run_id: str):
    run = _repo().get(run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"run {run_id!r} not found"
        )
    return run


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def start_evaluation(request: StartRunRequest) -> dict:
    """Queue a benchmark run; execution continues in a background thread."""
    try:
        run_id = _runner().start_run(
            model_id=request.model_id,
            dataset_names=request.datasets,
            concurrency=request.concurrency,
            generation_params=request.generation_params,
            seed=request.seed,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=safe_error(exc)
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=safe_error(exc)
        ) from exc
    return {"run_id": run_id, "status": "queued"}


@router.get("")
def list_evaluations(model_id: str | None = None, limit: int = 50) -> list[dict]:
    limit = max(1, min(limit, 500))
    return [r.model_dump(mode="json") for r in _repo().list(model_id=model_id, limit=limit)]


@router.get("/{run_id}")
def get_evaluation(run_id: str, include_results: bool = False) -> dict:
    run = _get_run_or_404(run_id)
    data = run.model_dump(mode="json")
    if include_results:
        data["results"] = [r.model_dump(mode="json") for r in _repo().case_results(run_id)]
    return data


@router.post("/{run_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
def cancel_evaluation(run_id: str) -> dict:
    _get_run_or_404(run_id)
    _runner().request_cancellation(run_id)
    return {"run_id": run_id, "cancel_requested": True}
