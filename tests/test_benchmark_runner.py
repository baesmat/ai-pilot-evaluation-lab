"""Benchmark runner: success, timeout, retry, cancel, partial preservation.

Inference is faked at the ``InferenceClient.chat`` method boundary; no network
is touched. Retry semantics are tested one level deeper at ``_post_json``.
"""

from __future__ import annotations

import json
import threading

import httpx
import pytest

from app.models.model_config import ModelConfig
from app.services import benchmark_runner as br
from app.services import dataset_registry as dr
from app.services.inference_client import InferenceClient, InferenceError
from app.storage.repositories import ModelRepository, RunRepository
from tests.conftest import make_completion


def local_model(**kw) -> ModelConfig:
    defaults = dict(
        id="m1", display_name="M1", model_identifier="org/m", endpoint="http://127.0.0.1:1"
    )
    defaults.update(kw)
    return ModelConfig(**defaults)


@pytest.fixture()
def fake_datasets(tmp_path, monkeypatch):
    dataset_dir = tmp_path / "datasets"
    dataset_dir.mkdir()
    cases = [
        {
            "id": "a1",
            "dataset": "alpha",
            "category": "general",
            "prompt": "p1",
            "evaluation_method": "exact_match",
            "expected_answer": "right",
        },
        {
            "id": "a2",
            "dataset": "alpha",
            "category": "general",
            "prompt": "p2",
            "evaluation_method": "json_schema",
            "expected_output": {"k": "v"},
        },
    ]
    (dataset_dir / "alpha.json").write_text(json.dumps(cases))
    monkeypatch.setattr(dr, "DATASETS_DIR", dataset_dir)
    return dataset_dir


def test_start_and_complete_run(tmp_db, fake_datasets, monkeypatch):
    ModelRepository().upsert(local_model())

    def fake_chat(self, messages, generation_params=None):
        _ = self, messages, generation_params
        return make_completion(content="right", latency_ms=5.0)

    monkeypatch.setattr(InferenceClient, "chat", fake_chat)
    runner = br.BenchmarkRunner(RunRepository(), ModelRepository())
    run_id = runner.run_sync("m1", ["alpha"], generation_params={"temperature": 0.1})

    repo = RunRepository()
    run = repo.get(run_id)
    assert run is not None and run.status == "completed"
    assert run.summary is not None and run.summary.total_cases == 2
    assert run.progress_completed == 2
    results = repo.case_results(run_id)
    assert {r.case_id for r in results} == {"a1", "a2"}
    a1 = next(r for r in results if r.case_id == "a1")
    assert a1.status == "passed" and a1.score == 1.0
    assert a1.latency_ms == 5.0
    assert "method=exact_match" in (a1.scoring_notes or "")
    a2 = next(r for r in results if r.case_id == "a2")
    assert "structured_ok=" in (a2.scoring_notes or "")


def test_unknown_model_dataset_and_disabled(tmp_db, fake_datasets):
    repo = ModelRepository()
    runner = br.BenchmarkRunner(RunRepository(), repo)
    with pytest.raises(ValueError):
        runner.run_sync("nope", ["alpha"])
    repo.upsert(local_model())
    with pytest.raises(ValueError):
        runner.run_sync("m1", ["missing"])
    repo.upsert(local_model(id="m2", enabled=False))
    with pytest.raises(ValueError):
        runner.run_sync("m2", ["alpha"])


def test_concurrency_clamped(tmp_db, fake_datasets):
    ModelRepository().upsert(local_model())
    runner = br.BenchmarkRunner(RunRepository(), ModelRepository())
    _, _m, _c, high, _p = runner._prepare("m1", ["alpha"], 99, None, None)
    assert high == 4
    _, _m, _c, low, _p = runner._prepare("m1", ["alpha"], 0, None, None)
    assert low == 1


def test_error_case_recorded_not_dropped(tmp_db, fake_datasets, monkeypatch):
    ModelRepository().upsert(local_model())
    calls = {"n": 0}

    def flaky_chat(self, messages, generation_params=None):
        _ = self, messages, generation_params
        calls["n"] += 1
        if calls["n"] == 1:
            raise InferenceError("endpoint returned HTTP 500: oops")
        return make_completion(content="right")

    monkeypatch.setattr(InferenceClient, "chat", flaky_chat)
    runner = br.BenchmarkRunner(RunRepository(), ModelRepository())
    run_id = runner.run_sync("m1", ["alpha"])
    results = RunRepository().case_results(run_id)
    assert len(results) == 2  # both cases recorded
    errored = [r for r in results if r.status == "error"]
    assert len(errored) == 1
    assert "HTTP 500" in (errored[0].error or "")
    run = RunRepository().get(run_id)
    assert run is not None and run.status == "completed"
    assert run.summary is not None and run.summary.errored == 1


def test_timeout_counted(tmp_db, fake_datasets, monkeypatch):
    ModelRepository().upsert(local_model())

    def slow_chat(self, messages, generation_params=None):
        _ = self, messages, generation_params
        raise InferenceError("request timed out after 3 attempts")

    monkeypatch.setattr(InferenceClient, "chat", slow_chat)
    runner = br.BenchmarkRunner(RunRepository(), ModelRepository())
    run_id = runner.run_sync("m1", ["alpha"])
    run = RunRepository().get(run_id)
    assert run is not None and run.summary is not None
    assert run.summary.timeout_count == 2
    assert run.summary.errored == 2


def test_retry_then_success_on_connect_error(tmp_db, monkeypatch):
    monkeypatch.setattr("app.services.inference_client.time.sleep", lambda _s: None)
    client = InferenceClient(local_model(), allowlist=["127.0.0.1"])
    attempts = {"n": 0}

    def flaky_post(payload):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise httpx.ConnectError("boom")
        return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}

    client._post_json = flaky_post  # type: ignore[method-assign]
    result = client.chat([{"role": "user", "content": "hi"}])
    assert result.content == "ok"
    assert result.request_attempt == 3
    assert attempts["n"] == 3


def test_retry_exhaustion_raises_inference_error(tmp_db, monkeypatch):
    monkeypatch.setattr("app.services.inference_client.time.sleep", lambda _s: None)
    client = InferenceClient(local_model(), allowlist=["127.0.0.1"])

    def always_timeout(payload):
        raise httpx.ConnectError("refused")

    client._post_json = always_timeout  # type: ignore[method-assign]
    with pytest.raises(InferenceError) as excinfo:
        client.chat([{"role": "user", "content": "hi"}])
    assert "3 attempts" in str(excinfo.value)


def test_cancellation_keeps_partial_results(tmp_db, fake_datasets, monkeypatch):
    ModelRepository().upsert(local_model())
    repo = RunRepository()
    runner = br.BenchmarkRunner(repo, ModelRepository())

    def fake_chat(self, messages, generation_params=None):
        _ = self, messages, generation_params
        return make_completion(content="right")

    monkeypatch.setattr(InferenceClient, "chat", fake_chat)

    # Prepare the run first so the test knows the id before execution starts,
    # then cancel as soon as the first result is persisted.
    run, model, cases, concurrency, params = runner._prepare("m1", ["alpha"], 1, None, None)
    run_id = run.id
    original_add = repo.add_case_result

    def add_and_cancel(result):
        original_add(result)
        if result.case_id == "a1":
            runner.request_cancellation(run_id)

    repo.add_case_result = add_and_cancel  # type: ignore[method-assign]
    worker = threading.Thread(
        target=runner._execute, args=(run_id, model, cases, concurrency, params), daemon=True
    )
    worker.start()
    worker.join(timeout=10)

    run = repo.get(run_id)
    assert run is not None and run.status == "cancelled"
    assert run.finished_at is not None
    results = repo.case_results(run_id)
    assert [r.case_id for r in results] == ["a1"]  # partial preserved; a2 never recorded


def test_runner_singleton_thread_safe():
    assert br.get_runner() is br.get_runner()
