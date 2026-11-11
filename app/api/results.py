"""Read-only inspection endpoints: per-case results and dataset contents."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

from app.security.secrets import safe_error
from app.services.dataset_registry import list_datasets, load_dataset
from app.storage.repositories import RunRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["results"])


@router.get("/evaluations/{run_id}/results")
def case_results(run_id: str) -> list[dict]:
    """Every recorded case result for a run, errors included."""
    if RunRepository().get(run_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"run {run_id!r} not found"
        )
    return [r.model_dump(mode="json") for r in RunRepository().case_results(run_id)]


@router.get("/datasets")
def datasets() -> list[dict]:
    return [meta.model_dump(mode="json") for meta in list_datasets()]


@router.get("/datasets/{name}/cases")
def dataset_cases(name: str) -> list[dict]:
    try:
        cases = load_dataset(name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=safe_error(exc)) from exc
    return [c.model_dump(mode="json") for c in cases]
