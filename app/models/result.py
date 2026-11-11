"""Evaluation run and per-case result models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

CaseStatus = Literal["passed", "failed", "error"]
RunStatus = Literal["pending", "running", "completed", "cancelled", "failed"]
TokenSource = Literal["measured", "estimated", "unavailable"]


class FieldResult(BaseModel):
    field: str
    expected: Any = None
    actual: Any = None
    correct: bool


class TokenUsage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    source: TokenSource = "unavailable"


class CaseResult(BaseModel):
    run_id: str
    case_id: str
    dataset: str
    status: CaseStatus
    score: float = Field(ge=0.0, le=1.0)
    weight: float = 1.0
    field_results: list[FieldResult] = Field(default_factory=list)
    raw_response: str | None = None
    parsed_output: dict[str, Any] | None = None
    latency_ms: float | None = None
    time_to_first_token_ms: float | None = None
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    request_attempt: int = 1
    error: str | None = None
    scoring_notes: str | None = None
    #: Security-domain classification of the outcome for one case.
    security_outcome: Literal["attack_succeeded", "attack_resisted", "ambiguous"] | None = None
    completed_at: datetime | None = None


class RunSummary(BaseModel):
    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    errored: int = 0
    weighted_score: float | None = None
    by_dataset: dict[str, dict[str, float]] = Field(default_factory=dict)
    latency_ms_median: float | None = None
    latency_ms_p95: float | None = None
    latency_ms_min: float | None = None
    latency_ms_max: float | None = None
    timeout_count: int = 0
    structured_output_success_rate: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    token_source: TokenSource = "unavailable"


class EvaluationRun(BaseModel):
    id: str
    model_id: str
    model_identifier: str
    endpoint_label: str
    dataset_names: list[str]
    dataset_versions: dict[str, str]
    case_ids: list[str]
    generation_params: dict[str, Any]
    concurrency: int = 1
    scoring_version: str
    app_version: str
    git_commit: str | None = None
    random_seed: int | None = None
    status: RunStatus = "pending"
    requested_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress_completed: int = 0
    progress_total: int = 0
    summary: RunSummary | None = None
    cancel_requested: bool = False
