"""API-layer tests. All service boundaries are faked; no network access."""

from __future__ import annotations

import uuid

import pytest

from tests.api_helpers import (
    FakeRunner,
    install_fake_runner,
    make_case_result,
    make_model,
    make_run,
)


@pytest.fixture()
def api_env(tmp_path, monkeypatch):
    from tests.api_helpers import env_fresh_data_dir

    yield from env_fresh_data_dir(tmp_path, monkeypatch)


@pytest.fixture()
def client(api_env):
    from tests.api_helpers import make_client

    yield from make_client()


# ---------------------------------------------------------------------------
# meta
# ---------------------------------------------------------------------------


def test_health_and_app_info(client):
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["version"]
    info = client.get("/api/app-info").json()
    assert info["name"]
    assert info["api_prefix"] == "/api"


# ---------------------------------------------------------------------------
# model registry
# ---------------------------------------------------------------------------


def _model_payload(**overrides):
    payload = {
        "id": f"m-{uuid.uuid4().hex[:8]}",
        "display_name": "Test Model",
        "model_identifier": "org/model-x",
        "endpoint": "http://127.0.0.1:9999/v1",
    }
    payload.update(overrides)
    return payload


def test_model_create_list_and_duplicate_conflict(client):
    payload = _model_payload()
    resp = client.post("/api/models", json=payload)
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["id"] == payload["id"]
    assert created["api_key"] is None

    dup = client.post("/api/models", json=payload)
    assert dup.status_code == 409

    listed = client.get("/api/models").json()
    assert any(m["id"] == payload["id"] for m in listed)


def test_model_create_validates_endpoint_allowlist(client):
    resp = client.post("/api/models", json=_model_payload(endpoint="http://example.com:1/v1"))
    assert resp.status_code == 400
    assert "allowlist" in resp.json()["detail"]


def test_model_update_and_delete(client):
    payload = _model_payload()
    assert client.post("/api/models", json=payload).status_code == 201

    renamed = dict(payload, display_name="Renamed")
    resp = client.put(f"/api/models/{payload['id']}", json=renamed)
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "Renamed"

    missing_put = client.put("/api/models/does-not-exist", json=renamed)
    assert missing_put.status_code == 404

    assert client.delete(f"/api/models/{payload['id']}").status_code == 200
    assert client.delete(f"/api/models/{payload['id']}").status_code == 404


def test_model_health_check_persists_result(client, monkeypatch):
    from tests.api_helpers import install_fake_inference

    model = make_model()
    install_fake_inference(monkeypatch, None)

    resp = client.post(f"/api/models/{model.id}/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["api_compatible"] is True

    stored = client.get("/api/models").json()
    mine = next(m for m in stored if m["id"] == model.id)
    assert mine["last_health_check"] is not None


def test_model_health_check_unknown_model(client):
    assert client.post("/api/models/nope/health").status_code == 404


def test_model_health_check_failure_is_redacted_ok_response(client, monkeypatch):
    import app.api.models as models_module

    model = make_model()

    class ExplodingClient:
        def __init__(self, *a, **k):
            pass

        def health_check(self):
            raise RuntimeError("connection refused for bearer sk-secret-value-1234")

    monkeypatch.setattr(models_module, "InferenceClient", ExplodingClient)
    resp = client.post(f"/api/models/{model.id}/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "sk-secret-value-1234" not in (body["error"] or "")


# ---------------------------------------------------------------------------
# evaluations
# ---------------------------------------------------------------------------


def test_start_evaluation_returns_202_and_run_id(client, monkeypatch):
    install_fake_runner(monkeypatch, FakeRunner())
    resp = client.post(
        "/api/evaluations",
        json={"model_id": "test-model", "datasets": ["ds_a"], "concurrency": 2},
    )
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["run_id"]
    assert run_id

    run = client.get(f"/api/evaluations/{run_id}").json()
    assert run["id"] == run_id
    assert "results" not in run

    with_results = client.get(f"/api/evaluations/{run_id}?include_results=true").json()
    assert "results" in with_results


def test_start_evaluation_invalid_dataset_maps_to_400(client, monkeypatch):
    install_fake_runner(monkeypatch, FakeRunner(fail_start=True))
    resp = client.post("/api/evaluations", json={"model_id": "m", "datasets": ["nope"]})
    assert resp.status_code == 400


def test_list_evaluations_filters_by_model(client, monkeypatch):
    install_fake_runner(monkeypatch, FakeRunner())
    client.post("/api/evaluations", json={"model_id": "a-model", "datasets": ["ds_a"]})
    client.post("/api/evaluations", json={"model_id": "b-model", "datasets": ["ds_a"]})

    listed = client.get("/api/evaluations").json()
    assert {r["model_id"] for r in listed} >= {"a-model", "b-model"}
    only_a = client.get("/api/evaluations", params={"model_id": "a-model"}).json()
    assert {r["model_id"] for r in only_a} == {"a-model"}


def test_cancel_evaluation(client, monkeypatch):
    runner = install_fake_runner(monkeypatch, FakeRunner())
    run_id = client.post("/api/evaluations", json={"model_id": "m", "datasets": ["ds_a"]}).json()[
        "run_id"
    ]

    resp = client.post(f"/api/evaluations/{run_id}/cancel")
    assert resp.status_code == 202
    assert runner.cancelled == [run_id]

    assert client.post("/api/evaluations/unknown/cancel").status_code == 404


def test_get_unknown_run_404(client):
    assert client.get("/api/evaluations/missing").status_code == 404


# ---------------------------------------------------------------------------
# case results
# ---------------------------------------------------------------------------


def test_case_results_endpoint(client):
    make_run(run_id="run-res")
    make_case_result(run_id="run-res", case_id="c1", score=1.0)
    make_case_result(run_id="run-res", case_id="c2", status="failed", score=0.0, error=None)

    resp = client.get("/api/evaluations/run-res/results")
    assert resp.status_code == 200
    results = resp.json()
    assert {r["case_id"] for r in results} == {"c1", "c2"}
    assert all({"score", "status", "case_id", "run_id"} <= set(r) for r in results)

    assert client.get("/api/evaluations/missing/results").status_code == 404


# ---------------------------------------------------------------------------
# datasets (registry faked at the API boundary)
# ---------------------------------------------------------------------------


def test_datasets_endpoints(client, monkeypatch):
    import app.api.results as results_module
    from app.models.benchmark import DatasetMeta
    from tests.api_helpers import sample_case

    meta = DatasetMeta(
        name="ds_a",
        title="Dataset A",
        description="d",
        case_count=1,
        sha256="a" * 64,
        categories=["unit"],
    )
    monkeypatch.setattr(results_module, "list_datasets", lambda: [meta])
    monkeypatch.setattr(results_module, "load_dataset", lambda name: [sample_case()])

    listed = client.get("/api/datasets").json()
    assert listed[0]["name"] == "ds_a"
    assert listed[0]["case_count"] == 1

    cases = client.get("/api/datasets/ds_a/cases").json()
    assert cases[0]["id"] == "case-1"

    def boom(name):
        raise ValueError(f"unknown dataset {name}")

    monkeypatch.setattr(results_module, "load_dataset", boom)
    assert client.get("/api/datasets/missing/cases").status_code == 404


# ---------------------------------------------------------------------------
# reports & comparison
# ---------------------------------------------------------------------------


def test_report_unknown_run_and_not_completed(client):
    assert client.get("/api/evaluations/missing/report").status_code == 404
    make_run(run_id="run-pending", status="pending")
    resp = client.get("/api/evaluations/run-pending/report")
    assert resp.status_code == 409


def test_report_markdown_and_pdf(client):
    make_run(run_id="run-rep")
    make_case_result(run_id="run-rep", case_id="c1")

    md = client.get("/api/evaluations/run-rep/report", params={"format": "markdown"})
    assert md.status_code == 200
    assert "markdown" in md.headers["content-type"]
    assert "Evaluation Report" in md.text
    assert "Executive Summary" in md.text
    assert "c1" in md.text  # case-level evidence present

    pdf = client.get("/api/evaluations/run-rep/report")  # default format=pdf
    assert pdf.status_code == 200
    assert pdf.headers["content-type"].startswith("application/pdf")
    assert pdf.content.startswith(b"%PDF")
    assert len(pdf.content) > 1024


def test_comparison_endpoint(client):
    make_run(run_id="cmp-a")
    make_run(run_id="cmp-b")
    make_case_result(run_id="cmp-a", case_id="c1")
    make_case_result(run_id="cmp-b", case_id="c1", score=0.0, status="failed")

    resp = client.get("/api/comparison", params={"run_ids": "cmp-a,cmp-b"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "eligibility" in body
    assert "rows" in body

    assert client.get("/api/comparison", params={"run_ids": "cmp-a,missing"}).status_code == 404
    assert client.get("/api/comparison").status_code == 422


# ---------------------------------------------------------------------------
# governance
# ---------------------------------------------------------------------------


def test_assessment_partial_merge_and_replace(client):
    model = make_model(model_id="gov-1")
    item = {"category": "Security", "item": "Logging", "status": "meets_requirement"}
    resp = client.put(f"/api/assessments/{model.id}", json=item)
    assert resp.status_code == 200
    assert resp.json()["items"][0]["status"] == "meets_requirement"

    # partial merge updates in place
    resp = client.put(
        f"/api/assessments/{model.id}",
        json={"category": "Security", "item": "Logging", "status": "does_not_meet_requirement"},
    )
    assert len(resp.json()["items"]) == 1
    assert resp.json()["items"][0]["status"] == "does_not_meet_requirement"

    # full replace
    replacement = {
        "items": [
            {"category": "Security", "item": "Encryption", "status": "not_evaluated"},
            {"category": "Security", "item": "Logging", "status": "meets_requirement"},
        ]
    }
    resp = client.put(f"/api/assessments/{model.id}", json=replacement)
    assert len(resp.json()["items"]) == 2

    bad = client.put(f"/api/assessments/{model.id}", json={"status": "meets_requirement"})
    assert bad.status_code == 422


def test_assessment_summary_flags_positive_without_evidence(client):
    model = make_model(model_id="gov-2")
    client.put(
        f"/api/assessments/{model.id}",
        json={
            "category": "Security",
            "item": "Logging",
            "status": "meets_requirement",  # positive, no rationale/evidence
        },
    )
    client.put(
        f"/api/assessments/{model.id}",
        json={
            "category": "Security",
            "item": "Encryption",
            "status": "meets_requirement",
            "rationale": "TLS everywhere",
            "evidence": "doc link",
        },
    )
    summary = client.get(f"/api/assessments/{model.id}/summary").json()
    assert summary["total"] == 2
    assert summary["assessed"] == 2
    assert summary["positive"] == 2
    assert summary["positive_without_evidence"] == 1


def test_reviews_roundtrip(client):
    model = make_model(model_id="gov-3")
    resp = client.post(
        "/api/reviews",
        json={"model_id": model.id, "reviewer": "Alice", "outstanding_risks": ["r1"]},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] is not None

    listed = client.get(f"/api/reviews/{model.id}").json()
    assert len(listed) == 1
    assert listed[0]["reviewer"] == "Alice"
    assert listed[0]["outstanding_risks"] == ["r1"]


# ---------------------------------------------------------------------------
# app-info / cors smoke
# ---------------------------------------------------------------------------


def test_cors_allows_configured_origin(client):
    resp = client.options(
        "/api/models",
        headers={"Origin": "http://127.0.0.1:8501", "Access-Control-Request-Method": "GET"},
    )
    assert resp.headers.get("access-control-allow-origin") == "http://127.0.0.1:8501"


def test_bootstrap_model_recorded_from_env(api_env, monkeypatch):
    from app.storage.database import reset_engine
    from app.storage.repositories import ModelRepository

    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9999/v1")
    monkeypatch.setenv("LLM_MODEL", "bootstrap/model")
    reset_engine()

    from app.main import _bootstrap_model_from_env

    _bootstrap_model_from_env()
    models = ModelRepository().list()
    assert len(models) == 1
    assert models[0].model_identifier == "bootstrap/model"

    # second call is a no-op once the registry is non-empty
    _bootstrap_model_from_env()
    assert len(ModelRepository().list()) == 1
    reset_engine()


def test_runner_start_validation_surfaces_client_error(client, monkeypatch):
    class ThrowingRunner(FakeRunner):
        def start_run(self, *a, **k):
            raise KeyError("model missing")

    install_fake_runner(monkeypatch, ThrowingRunner())
    resp = client.post("/api/evaluations", json={"model_id": "ghost", "datasets": ["ds_a"]})
    assert resp.status_code == 404


@pytest.mark.parametrize("payload", [{"datasets": ["x"]}, {"model_id": "m"}, {}])
def test_start_evaluation_validation_422(client, payload):
    # no runner needed: pydantic validation fails first
    assert client.post("/api/evaluations", json=payload).status_code == 422
