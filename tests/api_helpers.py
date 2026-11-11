"""Shared fixtures and fakes for API tests.

Intentionally NOT conftest.py (owned by the services workstream): import these
helpers from test modules, e.g. ``from api_helpers import client`` — pytest's
rootdir-inserted path makes the bare import work.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Environment / app fixtures
# ---------------------------------------------------------------------------


def env_fresh_data_dir(tmp_path, monkeypatch):
    """Point APP_DATA_DIR at a per-test scratch dir with a fresh engine.

    Plain generator (not a fixture) so test modules wrap it in their own
    fixtures without import-shadowing pitfalls.
    """
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    from app.storage.database import reset_engine

    reset_engine()
    yield tmp_path
    reset_engine()


def make_client():
    """Yield a TestClient with lifespan (fresh app bound to the fixture env)."""
    from app.main import create_app

    app = create_app()
    with TestClient(app) as test_client:  # context manager runs lifespan
        yield test_client


# ---------------------------------------------------------------------------
# Model / run / result builders (direct repository writes, no HTTP)
# ---------------------------------------------------------------------------


def make_model(model_id: str = "test-model", **overrides: Any):
    from app.models.model_config import ModelConfig
    from app.storage.repositories import ModelRepository

    cfg = ModelConfig(
        id=model_id,
        display_name=overrides.pop("display_name", f"Model {model_id}"),
        model_identifier=overrides.pop("model_identifier", "org/model-x"),
        endpoint=overrides.pop("endpoint", "http://127.0.0.1:9999/v1"),
        **overrides,
    )
    return ModelRepository().upsert(cfg)


def make_run(
    run_id: str = "run1",
    model_id: str = "test-model",
    status: str = "completed",
    dataset_names: list[str] | None = None,
    with_summary: bool = True,
):
    from app.models.result import EvaluationRun, RunSummary
    from app.storage.repositories import RunRepository

    datasets = dataset_names or ["ds_a"]
    run = EvaluationRun(
        id=run_id,
        model_id=model_id,
        model_identifier="org/model-x",
        endpoint_label="http://127.0.0.1:9999/v1",
        dataset_names=datasets,
        dataset_versions={name: "a" * 8 for name in datasets},
        case_ids=[f"{datasets[0]}-c1"],
        generation_params={"temperature": 0},
        concurrency=1,
        scoring_version="1.0.0",
        app_version="0.1.0",
        status=status,  # type: ignore[arg-type]
        requested_at=datetime.now(UTC),
        progress_total=1,
        summary=RunSummary(total_cases=1) if with_summary else None,
    )
    RunRepository().create(run)
    return run


def make_case_result(run_id: str = "run1", case_id: str = "ds_a-c1", **overrides: Any):
    from app.models.result import CaseResult
    from app.storage.repositories import RunRepository

    result = CaseResult(run_id=run_id, case_id=case_id, dataset="ds_a", status="passed", score=1.0)
    if overrides:
        result = result.model_copy(update=overrides)
    RunRepository().add_case_result(result)
    return result


def sample_case(case_id: str = "case-1", dataset: str = "ds_a"):
    from app.models.benchmark import BenchmarkCase

    return BenchmarkCase(
        id=case_id,
        dataset=dataset,
        category="unit",
        prompt="Say OK.",
        expected_answer="OK",
        evaluation_method="exact_match",
    )


# ---------------------------------------------------------------------------
# Fakes injected at the API boundary
# ---------------------------------------------------------------------------


class FakeRunner:
    """Stand-in for BenchmarkRunner: records requests, persists a real run row."""

    def __init__(self, fail_start: bool = False):
        self.started: list[dict] = []
        self.cancelled: list[str] = []
        self.fail_start = fail_start

    def start_run(
        self,
        model_id: str,
        dataset_names: list[str],
        concurrency: int = 1,
        generation_params: dict | None = None,
        seed: int | None = None,
        **_: Any,
    ) -> str:
        if self.fail_start:
            raise ValueError(f"unknown dataset {dataset_names!r}")
        self.started.append(
            {
                "model_id": model_id,
                "datasets": list(dataset_names),
                "concurrency": concurrency,
                "generation_params": generation_params,
                "seed": seed,
            }
        )
        run_id = f"run-{len(self.started):03d}"
        make_run(run_id=run_id, model_id=model_id, status="pending", dataset_names=dataset_names)
        return run_id

    def request_cancellation(self, run_id: str) -> None:
        self.cancelled.append(run_id)


def install_fake_runner(monkeypatch, runner: FakeRunner) -> FakeRunner:
    import app.api.evaluations as evaluations_module

    monkeypatch.setattr(evaluations_module, "get_runner", lambda: runner)
    return runner


class FakeInferenceClient:
    ok_result: Any = None
    raise_error: bool = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def health_check(self):
        if self.raise_error:
            raise RuntimeError("connection refused bearer abc123456")
        return self.ok_result


def install_fake_inference(monkeypatch, result) -> None:
    import app.api.models as models_module
    from app.models.model_config import HealthCheckResult

    fake = type(
        "FakeInferenceClient",
        (FakeInferenceClient,),
        {
            "ok_result": HealthCheckResult(
                model_id="x",
                ok=True,
                checked_at=datetime.now(UTC),
                latency_ms=12.5,
                api_compatible=True,
            ),
            "raise_error": False,
        },
    )
    monkeypatch.setattr(models_module, "InferenceClient", fake)
