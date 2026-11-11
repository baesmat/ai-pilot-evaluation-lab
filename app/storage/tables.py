"""SQLAlchemy table definitions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ModelRecord(Base):
    __tablename__ = "model_configs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120))
    provider: Mapped[str] = mapped_column(String(64), default="OpenAI Compatible")
    model_identifier: Mapped[str] = mapped_column(Text)
    endpoint: Mapped[str] = mapped_column(Text)
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)  # never logged
    hosting_type: Mapped[str] = mapped_column(String(16), default="local")
    context_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_cost_per_million_tokens: Mapped[float | None] = mapped_column(Float, nullable=True)
    output_cost_per_million_tokens: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=120)
    max_concurrent_requests: Mapped[int] = mapped_column(Integer, default=1)
    generation_params: Mapped[str] = mapped_column(Text, default="{}")   # JSON
    extra_headers: Mapped[str] = mapped_column(Text, default="{}")       # JSON, may hold creds
    supports_streaming: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0/1/NULL
    reports_token_usage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_health_check: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class EvaluationRunRecord(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    model_id: Mapped[str] = mapped_column(String(64))
    model_identifier: Mapped[str] = mapped_column(Text)
    endpoint_label: Mapped[str] = mapped_column(Text)
    dataset_names: Mapped[str] = mapped_column(Text)          # JSON list
    dataset_versions: Mapped[str] = mapped_column(Text)       # JSON dict name->sha256
    case_ids: Mapped[str] = mapped_column(Text)               # JSON list
    generation_params: Mapped[str] = mapped_column(Text)      # JSON
    concurrency: Mapped[int] = mapped_column(Integer, default=1)
    scoring_version: Mapped[str] = mapped_column(String(32))
    app_version: Mapped[str] = mapped_column(String(32))
    git_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    random_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    progress_completed: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)


class CaseResultRecord(Base):
    __tablename__ = "case_results"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(8))
    score: Mapped[float] = mapped_column(Float)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    field_results: Mapped[str] = mapped_column(Text, default="[]")   # JSON
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_output: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_to_first_token_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    token_usage: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    request_attempt: Mapped[int] = mapped_column(Integer, default=1)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    scoring_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    security_outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AssessmentRecord(Base):
    __tablename__ = "enterprise_assessments"

    model_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    items: Mapped[str] = mapped_column(Text, default="[]")  # JSON
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(120), nullable=True)


class HumanReviewRecord(Base):
    __tablename__ = "human_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_id: Mapped[str] = mapped_column(String(64))
    reviewer: Mapped[str] = mapped_column(String(120))
    review_date: Mapped[str] = mapped_column(String(10))  # ISO date
    assessment_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    outstanding_risks: Mapped[str] = mapped_column(Text, default="[]")
    required_mitigations: Mapped[str] = mapped_column(Text, default="[]")
    recommended_next_steps: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
