"""Enterprise readiness assessments and human review records.

These are structured human assessments. They are stored and reported
separately from automated benchmark measurements and never automatically
mark a model as enterprise-ready.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

AssessmentStatus = Literal[
    "not_evaluated",
    "meets_requirement",
    "partially_meets_requirement",
    "does_not_meet_requirement",
    "not_applicable",
]

ASSESSMENT_CATEGORIES: dict[str, list[str]] = {
    "Security": [
        "Data classification",
        "Access controls",
        "Network exposure",
        "Encryption",
        "Logging",
        "Security review",
    ],
    "Privacy and Governance": [
        "Data retention",
        "Model provider agreements",
        "Data residency",
        "Institutional policies",
        "Research data restrictions",
    ],
    "Operational Support": [
        "Service ownership",
        "Monitoring",
        "Incident management",
        "Change management",
        "Backup and recovery",
        "Support documentation",
    ],
    "Integration": [
        "API compatibility",
        "Authentication",
        "Existing enterprise systems",
        "Research workflows",
        "Data pipelines",
    ],
    "Financial Sustainability": [
        "Licensing",
        "Infrastructure costs",
        "Support costs",
        "Scalability",
        "Vendor dependencies",
    ],
    "Model Lifecycle": [
        "Version management",
        "Evaluation frequency",
        "Regression testing",
        "Model retirement",
        "Change approval",
    ],
}

POSITIVE_STATUSES = {"meets_requirement", "partially_meets_requirement"}


class AssessmentItem(BaseModel):
    category: str
    item: str
    status: AssessmentStatus = "not_evaluated"
    rationale: str | None = None
    evidence: str | None = None


class EnterpriseAssessment(BaseModel):
    """A human-recorded governance assessment for one model."""

    model_id: str
    items: list[AssessmentItem] = Field(default_factory=list)
    updated_at: datetime | None = None
    updated_by: str | None = None

    def completion(self) -> dict[str, int]:
        total = len(self.items)
        assessed = sum(1 for i in self.items if i.status != "not_evaluated")
        positive = sum(1 for i in self.items if i.status in POSITIVE_STATUSES)
        unverified_positive = sum(
            1 for i in self.items if i.status in POSITIVE_STATUSES and not (i.rationale or i.evidence)
        )
        return {
            "total": total,
            "assessed": assessed,
            "positive": positive,
            "positive_without_evidence": unverified_positive,
        }


class HumanReview(BaseModel):
    """Demonstration review workflow. Not an official approval process."""

    model_id: str
    reviewer: str = Field(min_length=1)
    review_date: date
    assessment_notes: str | None = None
    outstanding_risks: list[str] = Field(default_factory=list)
    required_mitigations: list[str] = Field(default_factory=list)
    recommended_next_steps: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
