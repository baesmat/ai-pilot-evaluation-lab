"""Report generation and cross-run comparison endpoints."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.config import get_settings
from app.models.governance import EnterpriseAssessment
from app.security.secrets import safe_error
from app.services.comparison_engine import compare
from app.services.report_generator import generate_report
from app.storage.repositories import AssessmentRepository, ReviewRepository, RunRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["reports"])


def _run_or_404(run_id: str):
    run = RunRepository().get(run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"run {run_id!r} not found"
        )
    return run


def _completed_run_or_409(run_id: str):
    run = _run_or_404(run_id)
    if run.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"run {run_id!r} is {run.status!r}; reports require a completed run",
        )
    return run


def _assessment_and_reviews(model_id: str) -> tuple[EnterpriseAssessment | None, list]:
    assessment = AssessmentRepository().get(model_id)
    reviews = ReviewRepository().for_model(model_id)
    return assessment, reviews


@router.get("/evaluations/{run_id}/report")
def evaluation_report(
    run_id: str,
    format: str = Query(default="pdf", pattern="^(pdf|markdown)$"),
) -> Response:
    """Render the enterprise-style report as PDF bytes or markdown text."""
    run = _completed_run_or_409(run_id)
    results = RunRepository().case_results(run_id)
    assessment, reviews = _assessment_and_reviews(run.model_id)

    if format == "markdown":
        from app.services.report_generator import generate_markdown

        try:
            text = generate_markdown(run, results, assessment, reviews)
        except TypeError:
            # Older signature without reviews.
            text = generate_markdown(run, results, assessment)  # type: ignore[call-arg]
        return Response(
            content=text,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'inline; filename="report_{run_id}.md"'},
        )

    out_dir = get_settings().reports_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = Path(out_dir) / f"report_{run_id}.pdf"
    try:
        path = generate_report(run, results, assessment, reviews, out_path)
    except TypeError:
        path = generate_report(run, results, assessment, out_path)  # type: ignore[call-arg]
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="report generation produced no file",
        )
    data = path.read_bytes()
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{path.name}"'},
    )


@router.get("/comparison")
def comparison(run_ids: str = Query(..., description="Comma-separated run ids")) -> dict:
    """Compare completed runs; eligibility warnings flag incomparable setups."""
    ids = [raw.strip() for raw in run_ids.split(",") if raw.strip()]
    if not ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="run_ids is required"
        )
    repo = RunRepository()
    runs = []
    missing = []
    for run_id in dict.fromkeys(ids):  # dedupe, keep order
        run = repo.get(run_id)
        if run is None:
            missing.append(run_id)
            continue
        runs.append(run)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown run id(s): {', '.join(missing)}",
        )
    results = {run.id: repo.case_results(run.id) for run in runs}
    try:
        return compare(runs, results)
    except Exception as exc:  # noqa: BLE001 - never leak secrets via error text
        logger.warning("comparison failed: %s", safe_error(exc))
        raise
