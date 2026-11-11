"""Cost estimation: hosted, local, missing data. Estimates only, never zero-faked."""

from __future__ import annotations

from app.models.model_config import ModelConfig
from app.models.result import RunSummary
from app.services.cost_estimator import estimate_run_cost, estimate_token_cost
from tests.conftest import make_completion  # noqa: F401


def hosted_model(**kw):
    defaults = dict(
        id="h",
        display_name="Hosted",
        model_identifier="m",
        endpoint="http://127.0.0.1:1",
        hosting_type="hosted",
        input_cost_per_million_tokens=1.0,
        output_cost_per_million_tokens=2.0,
    )
    defaults.update(kw)
    return ModelConfig(**defaults)


def local_model(**kw):
    defaults = dict(
        id="l", display_name="Local", model_identifier="m", endpoint="http://127.0.0.1:1"
    )
    defaults.update(kw)
    return ModelConfig(**defaults)


def test_hosted_cost_and_per_1k():
    model = hosted_model()
    summary = RunSummary(prompt_tokens=1_000_000, completion_tokens=1_000_000)
    estimate = estimate_run_cost(model, summary, requests=100)
    assert estimate.category == "direct_api"
    assert estimate.estimated_cost == 1.0 * 1 + 2.0 * 1  # 3.0
    assert estimate.per_1k_requests == 3.0 / 100 * 1000
    assert all("estimated" in line.lower() for line in estimate.basis)


def test_hosted_missing_price_names_the_field():
    model = hosted_model(output_cost_per_million_tokens=None)
    summary = RunSummary(prompt_tokens=10, completion_tokens=10)
    estimate = estimate_run_cost(model, summary, requests=10)
    assert estimate.category == "unavailable"
    assert estimate.estimated_cost is None
    assert "output_cost_per_million_tokens" in (estimate.notes or "")


def test_hosted_without_tokens_is_unavailable():
    estimate = estimate_run_cost(hosted_model(), RunSummary(), requests=5)
    assert estimate.category == "unavailable"
    assert "token" in (estimate.notes or "").lower()


def test_local_infrastructure_positive_cost():
    model = local_model()
    infra = {
        "hardware_cost": 12_000.0,
        "amortization_months": 36,
        "watts": 500,
        "electricity_rate_per_kwh": 0.30,
        "utilization_pct": 50,
        "other_monthly": 10.0,
    }
    estimate = estimate_run_cost(model, RunSummary(), requests=0, infra=infra)
    assert estimate.category == "local_infrastructure"
    assert estimate.estimated_cost is not None and estimate.estimated_cost > 0
    # never zero for local infra
    assert estimate.estimated_cost != 0.0
    assert estimate.per_1k_requests is None  # no requests_per_month assumption given
    energy = 500 / 1000 * 730 * 0.5 * 0.30
    assert abs(estimate.estimated_cost - (12_000 / 36 + energy + 10.0)) < 1e-6


def test_local_per_1k_needs_explicit_volume():
    model = local_model()
    infra = {"hardware_cost": 1200.0, "amortization_months": 12, "requests_per_month": 10_000}
    estimate = estimate_run_cost(model, RunSummary(), requests=3, infra=infra)
    assert estimate.per_1k_requests == (100.0 / 10_000) * 1000


def test_local_without_infra_data_is_unavailable_not_zero():
    estimate = estimate_run_cost(local_model(), RunSummary(), requests=3, infra=None)
    assert estimate.category == "unavailable"
    assert estimate.estimated_cost is None


def test_local_unusable_infra_keys():
    estimate = estimate_run_cost(
        local_model(), RunSummary(), requests=3, infra={"watts": "many", "foo": 1}
    )
    assert estimate.category == "unavailable"


def test_estimate_token_contract():
    assert estimate_token_cost(hosted_model(), 1_000_000, 0) == 1.0
    assert estimate_token_cost(hosted_model(), 1_000_000, None) is None
    assert estimate_token_cost(hosted_model(output_cost_per_million_tokens=None), 1, 1) is None
