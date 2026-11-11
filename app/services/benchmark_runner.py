"""Benchmark execution: orchestrates inference, scoring and persistence.

Every case result is persisted the moment it is decided; cancellation keeps
all completed results; no error is ever silently dropped.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from app import __version__ as APP_VERSION
from app.config import Settings, get_settings
from app.models.result import CaseResult
from app.security.secrets import safe_error
from app.services import (
    accuracy_evaluator,
    comparison_engine,  # noqa: F401  (re-exported for API layer)
    cost_estimator,  # noqa: F401
    dataset_registry,
    performance_evaluator,  # noqa: F401
    report_generator,  # noqa: F401
    security_evaluator,  # noqa: F401
)
from app.services.accuracy_evaluator import extract_json
from app.services.grounding_evaluator import grounding_note
from app.services.inference_client import InferenceClient
from app.services.performance_evaluator import compute_summary

logger = logging.getLogger(__name__)

#: score >= PASS_THRESHOLD marks a case "passed"; anything below is "failed".
PASS_THRESHOLD = 0.8

DEFAULT_SYSTEM_PROMPT = "You are being evaluated. Follow the output format exactly."

_RUNNER_LOCK = threading.Lock()
_RUNNER: BenchmarkRunner | None = None


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return result.stdout.strip() or None
    except Exception:  # noqa: BLE001 - git is optional metadata
        return None


def get_runner() -> BenchmarkRunner:
    """Process-wide runner built on the default repositories (thread-safe)."""
    global _RUNNER
    with _RUNNER_LOCK:
        if _RUNNER is None:
            from app.storage.repositories import ModelRepository, RunRepository

            _RUNNER = BenchmarkRunner(RunRepository(), ModelRepository())
        return _RUNNER


class BenchmarkRunner:
    def __init__(self, run_repo, model_repo, settings: Settings | None = None) -> None:
        self.run_repo = run_repo
        self.model_repo = model_repo
        self.settings = settings or get_settings()

    # -- public API --------------------------------------------------------

    def start_run(
        self,
        model_id: str,
        dataset_names: list[str],
        concurrency: int = 1,
        generation_params: dict | None = None,
        seed: int | None = None,
    ) -> str:
        """Validate, persist a pending run and execute it on a daemon thread."""
        run, model, cases, concurrency, params = self._prepare(
            model_id, dataset_names, concurrency, generation_params, seed
        )
        thread = threading.Thread(
            target=self._execute,
            args=(run.id, model, cases, concurrency, params),
            daemon=True,
            name=f"benchmark-{run.id}",
        )
        thread.start()
        return run.id

    def run_sync(
        self,
        model_id: str,
        dataset_names: list[str],
        concurrency: int = 1,
        generation_params: dict | None = None,
        seed: int | None = None,
    ) -> str:
        """Execute inline and return the run id (CLI path)."""
        run, model, cases, concurrency, params = self._prepare(
            model_id, dataset_names, concurrency, generation_params, seed
        )
        self._execute(run.id, model, cases, concurrency, params)
        return run.id

    def request_cancellation(self, run_id: str) -> None:
        self.run_repo.update_status(run_id, cancel_requested=True)

    # -- internals ----------------------------------------------------------

    def _prepare(self, model_id, dataset_names, concurrency, generation_params, seed):
        model = self.model_repo.get(model_id)
        if model is None:
            raise ValueError(f"unknown model '{model_id}'")
        if not model.enabled:
            raise ValueError(f"model '{model_id}' is disabled")
        known = {ds.name for ds in dataset_registry.list_datasets()}
        unknown = [name for name in dataset_names if name not in known]
        if unknown:
            raise ValueError(f"unknown dataset(s): {', '.join(unknown)}")
        cases = dataset_registry.load_cases(dataset_names)
        if not cases:
            raise ValueError("the requested datasets contain no cases")
        concurrency = max(1, min(4, int(concurrency)))
        merged_params = {**model.generation_params, **(generation_params or {})}
        run = _build_run(model, dataset_names, cases, concurrency, merged_params, seed)
        self.run_repo.create(run)
        return run, model, cases, concurrency, merged_params

    def _execute(self, run_id, model, cases, concurrency, generation_params) -> None:
        self.run_repo.update_status(run_id, status="running", started_at=datetime.utcnow())
        client = InferenceClient(model, settings=self.settings)
        completed = 0

        def run_one(case) -> CaseResult:
            try:
                messages = _build_messages(case)
                completion = client.chat(messages, generation_params)
                score, field_results, notes, security, parsed = _evaluate(case, completion)
                status = "passed" if score >= PASS_THRESHOLD else "failed"
                return CaseResult(
                    run_id=run_id,
                    case_id=case.id,
                    dataset=case.dataset,
                    status=status,
                    score=score,
                    weight=case.weight,
                    field_results=field_results,
                    raw_response=completion.content,
                    parsed_output=parsed,
                    latency_ms=completion.latency_ms,
                    time_to_first_token_ms=completion.time_to_first_token_ms,
                    token_usage=completion.token_usage,
                    request_attempt=completion.request_attempt,
                    scoring_notes=notes,
                    security_outcome=security,
                    completed_at=datetime.utcnow(),
                )
            except Exception as exc:  # every failure becomes a recorded error
                logger.warning("case %s failed: %s", case.id, safe_error(exc))
                return CaseResult(
                    run_id=run_id,
                    case_id=case.id,
                    dataset=case.dataset,
                    status="error",
                    score=0.0,
                    weight=case.weight,
                    error=safe_error(exc),
                    completed_at=datetime.utcnow(),
                )

        def persist(result: CaseResult) -> bool:
            """Record one result. Returns False when cancellation was requested."""
            self.run_repo.add_case_result(result)
            nonlocal completed
            completed += 1
            self.run_repo.update_status(run_id, progress_completed=completed)
            return not self.run_repo.cancel_requested(run_id)

        cancelled = False
        if concurrency <= 1:
            for case in cases:
                if self.run_repo.cancel_requested(run_id):
                    cancelled = True
                    break
                result = run_one(case)
                if not persist(result):
                    cancelled = True
                    break
        else:
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = {pool.submit(run_one, case): case for case in cases}
                for future in as_completed(futures):
                    result = future.result()
                    if not persist(result):
                        cancelled = True
                        pool.shutdown(wait=False, cancel_futures=True)
                        break

        if cancelled:
            self.run_repo.update_status(run_id, status="cancelled", finished_at=datetime.utcnow())
            return

        run = self.run_repo.get(run_id)
        results = self.run_repo.case_results(run_id)
        summary = compute_summary(run, results) if run is not None else None
        self.run_repo.update_status(
            run_id, status="completed", finished_at=datetime.utcnow(), summary=summary
        )


def _build_run(model, dataset_names, cases, concurrency, generation_params, seed):
    from app.models.result import EvaluationRun

    return EvaluationRun(
        id=uuid.uuid4().hex[:12],
        model_id=model.id,
        model_identifier=model.model_identifier,
        endpoint_label=model.endpoint,
        dataset_names=list(dataset_names),
        dataset_versions={name: dataset_registry.dataset_version(name) for name in dataset_names},
        case_ids=[case.id for case in cases],
        generation_params=dict(generation_params),
        concurrency=concurrency,
        scoring_version=accuracy_evaluator.SCORING_VERSION,
        app_version=APP_VERSION,
        git_commit=_git_commit(),
        random_seed=seed,
        status="pending",
        requested_at=datetime.utcnow(),
        progress_total=len(cases),
    )


def _build_messages(case) -> list[dict]:
    messages: list[dict] = []
    system_prompt = case.system_prompt or DEFAULT_SYSTEM_PROMPT
    messages.append({"role": "system", "content": system_prompt})
    content = case.prompt
    if case.context:
        content = f"{content}\n\nContext:\n{case.context}"
    messages.append({"role": "user", "content": content})
    return messages


def _evaluate(case, completion):
    """Dispatch to the right evaluator. Returns (score, field_results, notes, security, parsed)."""
    expected = case.expected_output if isinstance(case.expected_output, dict) else {}

    if "follow_task" in expected or "must_contain" in expected:
        from app.services.security_evaluator import evaluate_case as security_evaluate

        outcome = security_evaluate(case, completion)
        return outcome.score, [], outcome.notes, outcome.outcome, None

    if case.evaluation_method == "abstain_or_answer":
        from app.services.grounding_evaluator import evaluate_case as grounding_evaluate

        outcome = grounding_evaluate(case, completion)
        notes = f"method={case.evaluation_method};{grounding_note(outcome)}"
        if outcome.notes:
            notes += f";{outcome.notes}"
        return outcome.score, [], notes, None, None

    outcome = accuracy_evaluator.score_case(case, completion)
    notes = f"method={case.evaluation_method};structured_ok={int(outcome.structured_ok)}"
    if outcome.notes:
        notes += f";{outcome.notes}"
    parsed = None
    if case.evaluation_method in ("json_exact", "json_schema"):
        extracted = extract_json(completion.content) if completion.content else None
        parsed = extracted if isinstance(extracted, dict) else None
    return outcome.score, list(outcome.field_results), notes, None, parsed
