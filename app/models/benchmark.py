"""Benchmark case and dataset models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# Deterministic scoring methods. Every case must declare one.
EvaluationMethod = Literal[
    "exact_match",          # whole-output equality (normalized)
    "json_exact",           # parsed JSON equality
    "json_schema",          # keys/types present with values matched field-level
    "numeric_match",        # numeric comparison with tolerance
    "set_match",            # set equality of items
    "contains_all",         # all expected substrings present
    "rubric",               # weighted criteria, deterministic checks where possible
    "abstain_or_answer",    # grounding: answer with citations, or explicit abstain
]

Difficulty = Literal["easy", "medium", "hard"]


class RubricCriterion(BaseModel):
    name: str
    weight: float
    #: Optional deterministic check configuration evaluated by the scorer.
    check: dict[str, Any] | None = None


class BenchmarkCase(BaseModel):
    """A single evaluation case with a documented expected result."""

    id: str = Field(min_length=1, max_length=64)
    dataset: str = Field(min_length=1, description="Dataset slug, e.g. structured_extraction")
    category: str
    difficulty: Difficulty = "medium"
    prompt: str = Field(min_length=1)
    system_prompt: str | None = None
    context: str | None = None
    expected_output: dict[str, Any] | None = None
    expected_answer: str | None = None
    #: Evidence identifiers the answer should cite (grounding dataset).
    expected_evidence: list[str] = Field(default_factory=list)
    evaluation_method: EvaluationMethod
    rubric: list[RubricCriterion] | None = None
    #: Tolerance for numeric_match.
    tolerance: float = 0.0
    weight: float = 1.0
    notes: str | None = None

    def expected_display(self) -> str:
        if self.expected_output is not None:
            return str(self.expected_output)
        return self.expected_answer or ""


class DatasetMeta(BaseModel):
    name: str
    title: str
    description: str
    case_count: int
    sha256: str
    categories: list[str]
