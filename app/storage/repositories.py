"""Data-access objects. All mutations go through the process write lock."""

from __future__ import annotations

import json
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.governance import AssessmentItem, EnterpriseAssessment, HumanReview
from app.models.model_config import ModelConfig
from app.models.result import (
    CaseResult,
    EvaluationRun,
    FieldResult,
    RunSummary,
    TokenUsage,
)
from app.storage.database import write_lock
from app.storage.tables import (
    AssessmentRecord,
    CaseResultRecord,
    EvaluationRunRecord,
    HumanReviewRecord,
    ModelRecord,
)


def _loads(raw: str | None, default):
    if not raw:
        return default
    return json.loads(raw)


def _session(s: Session):
    """Usable as a context manager alias for readability."""
    return s


class ModelRepository:
    def list(self, include_disabled: bool = True) -> list[ModelConfig]:
        with write_lock():
            with _session(Session(bind=_engine())) as s:
                rows = s.scalars(select(ModelRecord)).all()
        out = []
        for r in rows:
            cfg = _record_to_model(r)
            if include_disabled or cfg.enabled:
                out.append(cfg)
        return out

    def get(self, model_id: str) -> ModelConfig | None:
        with write_lock():
            with _session(Session(bind=_engine())) as s:
                row = s.get(ModelRecord, model_id)
                return _record_to_model(row) if row else None

    def upsert(self, cfg: ModelConfig) -> ModelConfig:
        now = datetime.utcnow()
        cfg.updated_at = now
        if cfg.created_at is None:
            cfg.created_at = now
        with write_lock():
            with _session(Session(bind=_engine())) as s:
                row = s.get(ModelRecord, cfg.id)
                if row is None:
                    row = ModelRecord(id=cfg.id)
                    s.add(row)
                _apply_model_to_record(cfg, row)
                s.commit()
        return cfg

    def delete(self, model_id: str) -> bool:
        with write_lock():
            with _session(Session(bind=_engine())) as s:
                row = s.get(ModelRecord, model_id)
                if row is None:
                    return False
                s.delete(row)
                s.commit()
                return True

    def record_health(self, model_id: str, health: dict) -> None:
        with write_lock():
            with _session(Session(bind=_engine())) as s:
                row = s.get(ModelRecord, model_id)
                if row is not None:
                    row.last_health_check = json.dumps(
                        {**health, "checked_at": datetime.utcnow().isoformat()}
                    )
                    row.supports_streaming = health.get("supports_streaming")
                    row.reports_token_usage = health.get("reports_token_usage")
                    s.commit()


def _engine():
    from app.storage.database import engine_ref

    return engine_ref()


def _record_to_model(r: ModelRecord) -> ModelConfig:
    return ModelConfig(
        id=r.id,
        display_name=r.display_name,
        provider=r.provider,
        model_identifier=r.model_identifier,
        endpoint=r.endpoint,
        api_key=r.api_key,
        hosting_type=r.hosting_type,  # type: ignore[arg-type]
        context_window=r.context_window,
        input_cost_per_million_tokens=r.input_cost_per_million_tokens,
        output_cost_per_million_tokens=r.output_cost_per_million_tokens,
        currency=r.currency,
        enabled=r.enabled,
        timeout_seconds=r.timeout_seconds,
        max_concurrent_requests=r.max_concurrent_requests,
        generation_params=_loads(r.generation_params, {}),
        extra_headers=_loads(r.extra_headers, {}),
        supports_streaming=None if r.supports_streaming is None else bool(r.supports_streaming),
        reports_token_usage=None if r.reports_token_usage is None else bool(r.reports_token_usage),
        last_health_check=_loads(r.last_health_check, None),
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


def _apply_model_to_record(cfg: ModelConfig, r: ModelRecord) -> None:
    r.display_name = cfg.display_name
    r.provider = cfg.provider
    r.model_identifier = cfg.model_identifier
    r.endpoint = cfg.endpoint
    r.api_key = cfg.api_key
    r.hosting_type = cfg.hosting_type
    r.context_window = cfg.context_window
    r.input_cost_per_million_tokens = cfg.input_cost_per_million_tokens
    r.output_cost_per_million_tokens = cfg.output_cost_per_million_tokens
    r.currency = cfg.currency
    r.enabled = cfg.enabled
    r.timeout_seconds = cfg.timeout_seconds
    r.max_concurrent_requests = cfg.max_concurrent_requests
    r.generation_params = json.dumps(cfg.generation_params)
    r.extra_headers = json.dumps(cfg.extra_headers)
    r.supports_streaming = None if cfg.supports_streaming is None else int(cfg.supports_streaming)
    r.reports_token_usage = None if cfg.reports_token_usage is None else int(cfg.reports_token_usage)
    r.updated_at = cfg.updated_at


class RunRepository:
    def create(self, run: EvaluationRun) -> None:
        with write_lock():
            with _session(Session(bind=_engine())) as s:
                s.add(
                    EvaluationRunRecord(
                        id=run.id,
                        model_id=run.model_id,
                        model_identifier=run.model_identifier,
                        endpoint_label=run.endpoint_label,
                        dataset_names=json.dumps(run.dataset_names),
                        dataset_versions=json.dumps(run.dataset_versions),
                        case_ids=json.dumps(run.case_ids),
                        generation_params=json.dumps(run.generation_params),
                        concurrency=run.concurrency,
                        scoring_version=run.scoring_version,
                        app_version=run.app_version,
                        git_commit=run.git_commit,
                        random_seed=run.random_seed,
                        status=run.status,
                        requested_at=run.requested_at or datetime.utcnow(),
                        progress_total=run.progress_total,
                    )
                )
                s.commit()

    def update_status(self, run_id: str, **fields) -> None:
        serialised = {}
        for key, value in fields.items():
            if key in ("dataset_names", "case_ids", "generation_params", "dataset_versions"):
                value = json.dumps(value)
            if key == "summary" and value is not None:
                value = value.model_dump_json() if isinstance(value, RunSummary) else json.dumps(value)
            serialised[key] = value
        with write_lock():
            with _session(Session(bind=_engine())) as s:
                row = s.get(EvaluationRunRecord, run_id)
                if row is None:
                    return
                for key, value in serialised.items():
                    setattr(row, key, value)
                s.commit()

    def cancel_requested(self, run_id: str) -> bool:
        with write_lock():
            with _session(Session(bind=_engine())) as s:
                row = s.get(EvaluationRunRecord, run_id)
                return bool(row and row.cancel_requested)

    def add_case_result(self, result: CaseResult) -> None:
        with write_lock():
            with _session(Session(bind=_engine())) as s:
                s.merge(
                    CaseResultRecord(
                        run_id=result.run_id,
                        case_id=result.case_id,
                        dataset=result.dataset,
                        status=result.status,
                        score=result.score,
                        weight=result.weight,
                        field_results=json.dumps([f.model_dump() for f in result.field_results]),
                        raw_response=result.raw_response,
                        parsed_output=(
                            json.dumps(result.parsed_output)
                            if result.parsed_output is not None
                            else None
                        ),
                        latency_ms=result.latency_ms,
                        time_to_first_token_ms=result.time_to_first_token_ms,
                        token_usage=result.token_usage.model_dump_json(),
                        request_attempt=result.request_attempt,
                        error=result.error,
                        scoring_notes=result.scoring_notes,
                        security_outcome=result.security_outcome,
                        completed_at=result.completed_at or datetime.utcnow(),
                    )
                )
                s.commit()

    def _results_for(self, s: Session, run_id: str) -> list[CaseResult]:
        rows = s.scalars(select(CaseResultRecord).where(CaseResultRecord.run_id == run_id)).all()
        return [_case_from_record(r) for r in rows]

    def get(self, run_id: str) -> EvaluationRun | None:
        with write_lock():
            with _session(Session(bind=_engine())) as s:
                row = s.get(EvaluationRunRecord, run_id)
                if row is None:
                    return None
                results = self._results_for(s, run_id)
        return _run_from_record(row, progress_completed=len(results))

    def list(self, model_id: str | None = None, limit: int = 100) -> list[EvaluationRun]:
        with write_lock():
            with _session(Session(bind=_engine())) as s:
                stmt = (
                    select(EvaluationRunRecord)
                    .order_by(EvaluationRunRecord.requested_at.desc())
                    .limit(limit)
                )
                if model_id:
                    stmt = stmt.where(EvaluationRunRecord.model_id == model_id)
                rows = s.scalars(stmt).all()
                counts: dict[str, int] = {}
                for cr in s.scalars(select(CaseResultRecord)):
                    counts[cr.run_id] = counts.get(cr.run_id, 0) + 1
        return [_run_from_record(r, counts.get(r.id, 0)) for r in rows]

    def case_results(self, run_id: str) -> list[CaseResult]:
        with write_lock():
            with _session(Session(bind=_engine())) as s:
                return self._results_for(s, run_id)


def _case_from_record(cr: CaseResultRecord) -> CaseResult:
    return CaseResult(
        run_id=cr.run_id,
        case_id=cr.case_id,
        dataset=cr.dataset,
        status=cr.status,  # type: ignore[arg-type]
        score=cr.score,
        weight=cr.weight,
        field_results=[FieldResult(**f) for f in _loads(cr.field_results, [])],
        raw_response=cr.raw_response,
        parsed_output=_loads(cr.parsed_output, None),
        latency_ms=cr.latency_ms,
        time_to_first_token_ms=cr.time_to_first_token_ms,
        token_usage=TokenUsage(**_loads(cr.token_usage, {})) if cr.token_usage else TokenUsage(),
        request_attempt=cr.request_attempt,
        error=cr.error,
        scoring_notes=cr.scoring_notes,
        security_outcome=cr.security_outcome,  # type: ignore[arg-type]
        completed_at=cr.completed_at,
    )


def _run_from_record(row, progress_completed: int) -> EvaluationRun:
    summary = None
    if row.summary:
        summary = RunSummary(**_loads(row.summary, {}))
    return EvaluationRun(
        id=row.id,
        model_id=row.model_id,
        model_identifier=row.model_identifier,
        endpoint_label=row.endpoint_label,
        dataset_names=_loads(row.dataset_names, []),
        dataset_versions=_loads(row.dataset_versions, {}),
        case_ids=_loads(row.case_ids, []),
        generation_params=_loads(row.generation_params, {}),
        concurrency=row.concurrency,
        scoring_version=row.scoring_version,
        app_version=row.app_version,
        git_commit=row.git_commit,
        random_seed=row.random_seed,
        status=row.status,  # type: ignore[arg-type]
        requested_at=row.requested_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        progress_completed=progress_completed,
        progress_total=row.progress_total,
        summary=summary,
        cancel_requested=row.cancel_requested,
    )


def _attach_results(run: EvaluationRun, results: list[CaseResult]) -> EvaluationRun:
    """Attach case results for API responses that need them inline."""
    run.case_results = results  # type: ignore[attribute-defined-outside-use]
    return run


class AssessmentRepository:
    def get(self, model_id: str) -> EnterpriseAssessment | None:
        with write_lock():
            with _session(Session(bind=_engine())) as s:
                row = s.get(AssessmentRecord, model_id)
                if row is None:
                    return None
        return EnterpriseAssessment(
            model_id=row.model_id,
            items=[AssessmentItem(**i) for i in _loads(row.items, [])],
            updated_at=row.updated_at,
            updated_by=row.updated_by,
        )

    def save(self, assessment: EnterpriseAssessment) -> None:
        with write_lock():
            with _session(Session(bind=_engine())) as s:
                row = s.get(AssessmentRecord, assessment.model_id)
                if row is None:
                    row = AssessmentRecord(model_id=assessment.model_id)
                    s.add(row)
                row.items = json.dumps([i.model_dump() for i in assessment.items])
                row.updated_at = datetime.utcnow()
                row.updated_by = assessment.updated_by
                s.commit()


class ReviewRepository:
    def add(self, review: HumanReview) -> int:
        with write_lock():
            with _session(Session(bind=_engine())) as s:
                rec = HumanReviewRecord(
                    model_id=review.model_id,
                    reviewer=review.reviewer,
                    review_date=review.review_date.isoformat(),
                    assessment_notes=review.assessment_notes,
                    outstanding_risks=json.dumps(review.outstanding_risks),
                    required_mitigations=json.dumps(review.required_mitigations),
                    recommended_next_steps=json.dumps(review.recommended_next_steps),
                )
                s.add(rec)
                s.commit()
                s.refresh(rec)
                return int(rec.id)

    def for_model(self, model_id: str) -> list[HumanReview]:
        with write_lock():
            with _session(Session(bind=_engine())) as s:
                rows = s.scalars(
                    select(HumanReviewRecord).where(HumanReviewRecord.model_id == model_id)
                ).all()
        return [
            HumanReview(
                model_id=r.model_id,
                reviewer=r.reviewer,
                review_date=date.fromisoformat(r.review_date),
                assessment_notes=r.assessment_notes,
                outstanding_risks=_loads(r.outstanding_risks, []),
                required_mitigations=_loads(r.required_mitigations, []),
                recommended_next_steps=_loads(r.recommended_next_steps, []),
                created_at=r.created_at,
            )
            for r in rows
        ]
