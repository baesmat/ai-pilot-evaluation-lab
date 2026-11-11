"""Cost estimation. Every number produced here is an ESTIMATE and is labelled one."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.model_config import ModelConfig
from app.models.result import RunSummary

HOURS_PER_MONTH = 730.0  # 365.25 days / 12


@dataclass
class CostEstimate:
    category: str  # direct_api | local_infrastructure | unavailable
    estimated_cost: float | None
    currency: str
    per_1k_requests: float | None
    basis: list[str] = field(default_factory=list)
    notes: str | None = None


def _unavailable(notes: str, currency: str = "USD") -> CostEstimate:
    return CostEstimate(
        category="unavailable",
        estimated_cost=None,
        currency=currency,
        per_1k_requests=None,
        basis=[],
        notes=notes,
    )


def estimate_token_cost(
    model: ModelConfig, prompt_tokens: int | None, completion_tokens: int | None
) -> float | None:
    """Estimated cost of one token bundle; None when prices or counts are missing."""
    if model.input_cost_per_million_tokens is None or model.output_cost_per_million_tokens is None:
        return None
    if prompt_tokens is None or completion_tokens is None:
        return None
    return (
        prompt_tokens * model.input_cost_per_million_tokens
        + completion_tokens * model.output_cost_per_million_tokens
    ) / 1_000_000


def _estimate_hosted(model: ModelConfig, summary: RunSummary, requests: int) -> CostEstimate:
    if summary.prompt_tokens is None and summary.completion_tokens is None:
        return _unavailable("token usage was not recorded for this run", model.currency)
    missing = [
        name
        for name, value in (
            ("input_cost_per_million_tokens", model.input_cost_per_million_tokens),
            ("output_cost_per_million_tokens", model.output_cost_per_million_tokens),
        )
        if value is None
    ]
    if missing:
        return _unavailable("missing model pricing field(s): " + ", ".join(missing), model.currency)
    prompt_tokens = summary.prompt_tokens or 0
    completion_tokens = summary.completion_tokens or 0
    cost = estimate_token_cost(model, prompt_tokens, completion_tokens)
    basis = [
        f"estimated from {prompt_tokens} prompt tokens at "
        f"{model.input_cost_per_million_tokens} per million",
        f"estimated from {completion_tokens} completion tokens at "
        f"{model.output_cost_per_million_tokens} per million",
    ]
    per_1k = None
    if cost is not None and requests > 0:
        per_1k = cost / requests * 1000
        basis.append(
            f"per-1k-request figure estimated by scaling the run cost over {requests} requests"
        )
    return CostEstimate(
        category="direct_api",
        estimated_cost=cost,
        currency=model.currency,
        per_1k_requests=per_1k,
        basis=basis,
        notes=None,
    )


def _estimate_local(model: ModelConfig, infra: dict, requests: int) -> CostEstimate:
    """Monthly infra cost from explicitly provided fields; never a fabricated zero.

    Formula (documented): monthly = hardware_cost/amortization_months
    + watts/1000 * HOURS_PER_MONTH * utilization_pct/100 * electricity_rate_per_kwh
    + other_monthly. per-1k needs an explicit ``requests_per_month`` infra key.
    """
    currency = model.currency
    if not isinstance(infra, dict) or not infra:
        return _unavailable(
            "hosting is local but no infrastructure cost data was provided", currency
        )

    basis: list[str] = []
    monthly = 0.0
    resolved = False

    hardware_cost = infra.get("hardware_cost")
    amortization_months = infra.get("amortization_months")
    if (
        isinstance(hardware_cost, (int, float))
        and isinstance(amortization_months, (int, float))
        and amortization_months > 0
    ):
        monthly += float(hardware_cost) / float(amortization_months)
        resolved = True
        basis.append(
            f"estimated hardware amortization: {hardware_cost} over {amortization_months} months"
        )

    watts = infra.get("watts")
    rate = infra.get("electricity_rate_per_kwh")
    utilization = infra.get("utilization_pct")
    if all(isinstance(v, (int, float)) for v in (watts, rate, utilization)):
        watts_f, rate_f, util_f = float(watts), float(rate), float(utilization)  # type: ignore[arg-type]
        energy = watts_f / 1000 * HOURS_PER_MONTH * (util_f / 100) * rate_f
        monthly += energy
        resolved = True
        basis.append(
            f"estimated energy: {watts_f}W at {util_f}% utilization, "
            f"{rate_f} per kWh, {HOURS_PER_MONTH:.01f} h/month"
        )

    other = infra.get("other_monthly")
    if isinstance(other, (int, float)):
        monthly += float(other)
        resolved = True
        basis.append(f"estimated other monthly costs: {other}")

    if not resolved:
        return _unavailable(
            "infrastructure data present but no cost component could be computed", currency
        )
    if monthly <= 0:
        return _unavailable("computed infrastructure cost is not positive; check inputs", currency)

    per_1k = None
    requests_per_month = infra.get("requests_per_month")
    if isinstance(requests_per_month, (int, float)) and requests_per_month > 0:
        per_1k = monthly / float(requests_per_month) * 1000
        basis.append(f"per-1k-request figure estimated from {requests_per_month} requests/month")
    elif requests <= 0:
        basis.append(
            "per-request cost not estimated: provide requests_per_month "
            "(per-request attribution of fixed infra is otherwise meaningless)"
        )
    else:
        basis.append(
            "per-1k-request figure not estimated: no requests_per_month assumption provided"
        )

    return CostEstimate(
        category="local_infrastructure",
        estimated_cost=monthly,
        currency=currency,
        per_1k_requests=per_1k,
        basis=basis,
        notes="all figures are estimates derived from the provided infrastructure inputs",
    )


def estimate_run_cost(
    model: ModelConfig, summary: RunSummary, requests: int, infra: dict | None = None
) -> CostEstimate:
    """Estimated cost of a run. Missing inputs yield ``unavailable``, never zero."""
    if model.hosting_type == "hosted":
        return _estimate_hosted(model, summary, requests)
    return _estimate_local(model, infra or {}, requests)
