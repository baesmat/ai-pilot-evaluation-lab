"""Governance: enterprise readiness assessments and human reviews."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.models.governance import AssessmentItem, EnterpriseAssessment, HumanReview
from app.storage.repositories import AssessmentRepository, ReviewRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["governance"])

_AssessmentStatus = Literal[
    "not_evaluated",
    "meets_requirement",
    "partially_meets_requirement",
    "does_not_meet_requirement",
    "not_applicable",
]


class AssessmentUpdate(BaseModel):
    """Either a full item list, or one partial item to merge by (category, item)."""

    items: list[AssessmentItem] | None = None
    category: str | None = None
    item: str | None = None
    status: _AssessmentStatus = "not_evaluated"
    rationale: str | None = None
    evidence: str | None = None
    updated_by: str | None = None


class ReviewCreate(BaseModel):
    model_id: str
    reviewer: str
    review_date: str | None = None  # ISO date; defaults to today
    assessment_notes: str | None = None
    outstanding_risks: list[str] | None = None
    required_mitigations: list[str] | None = None
    recommended_next_steps: list[str] | None = None


def _existing(model_id: str) -> EnterpriseAssessment:
    got = AssessmentRepository().get(model_id)
    return got if got is not None else EnterpriseAssessment(model_id=model_id)


@router.get("/assessments/{model_id}")
def get_assessment(model_id: str) -> dict:
    return _existing(model_id).model_dump(mode="json")


@router.put("/assessments/{model_id}")
def put_assessment(model_id: str, update: AssessmentUpdate) -> dict:
    assessment = _existing(model_id)
    if update.items is not None:
        assessment.items = list(update.items)
    else:
        if not update.category or not update.item:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="provide either 'items' or 'category' and 'item'",
            )
        merged = False
        for existing in assessment.items:
            if existing.category == update.category and existing.item == update.item:
                existing.status = update.status
                if update.rationale is not None:
                    existing.rationale = update.rationale
                if update.evidence is not None:
                    existing.evidence = update.evidence
                merged = True
                break
        if not merged:
            assessment.items.append(
                AssessmentItem(
                    category=update.category,
                    item=update.item,
                    status=update.status,
                    rationale=update.rationale,
                    evidence=update.evidence,
                )
            )
    assessment.updated_at = datetime.now(UTC)
    if update.updated_by:
        assessment.updated_by = update.updated_by
    AssessmentRepository().save(assessment)
    logger.info("assessment updated for %s (%d items)", model_id, len(assessment.items))
    return assessment.model_dump(mode="json")


@router.get("/assessments/{model_id}/summary")
def assessment_summary(model_id: str) -> dict:
    """Completion counts; positive statuses lacking rationale/evidence are flagged,
    never blocked."""
    assessment = _existing(model_id)
    return {"model_id": model_id, **assessment.completion()}


@router.post("/reviews", status_code=status.HTTP_201_CREATED)
def create_review(review: ReviewCreate) -> dict:
    parsed_date = date.fromisoformat(review.review_date) if review.review_date else date.today()
    record = HumanReview(
        model_id=review.model_id,
        reviewer=review.reviewer,
        review_date=parsed_date,
        assessment_notes=review.assessment_notes,
        outstanding_risks=review.outstanding_risks or [],
        required_mitigations=review.required_mitigations or [],
        recommended_next_steps=review.recommended_next_steps or [],
    )
    saved_id = ReviewRepository().add(record)
    return {"id": saved_id, **record.model_dump(mode="json")}


@router.get("/reviews/{model_id}")
def list_reviews(model_id: str) -> list[dict]:
    return [r.model_dump(mode="json") for r in ReviewRepository().for_model(model_id)]
