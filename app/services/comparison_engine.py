"""Cross-run comparison. Fairness rule: a model must never rank higher just
because it saw fewer or easier cases, so score-like metrics are normalised
per dataset (macro-average) and mismatched case counts raise a warning.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.models.result import CaseResult, EvaluationRun
from app.services.grounding_evaluator import parse_grounding_note
from app.services.performance_evaluator import token_source_of

RowKind = str  # measured | estimated | mixed | unavailable


@dataclass
class ComparisonRow:
    metric: str
    values: dict[str, str]
    kind: RowKind
    note: str | None = None


def _fmt(value: float | None, unit: str = "") -> str:
    if value is None:
        return "Not available"
    return f"{value:.4f}{unit}"


def _extraction_scores(results: list[CaseResult]) -> tuple[float | None, int]:
    """Mean score over structured-output cases (method in scoring notes)."""
    structured = [
        r
        for r in results
        if r.status != "error" and _note_method(r) in ("json_exact", "json_schema")
    ]
    pool = structured or [r for r in results if r.status != "error"]
    if not pool:
        return None, 0
    return sum(r.score for r in pool) / len(pool), len(pool)


def _note_method(result: CaseResult) -> str | None:
    notes = result.scoring_notes
    if not notes:
        return None
    marker = "method="
    index = notes.find(marker)
    if index < 0:
        return None
    rest = notes[index + len(marker) :]
    return rest.split(";", 1)[0].split("|", 1)[0] or None


def _macro_dataset_score(run: EvaluationRun) -> float | None:
    """Mean of per-dataset mean scores; equalises datasets of different sizes."""
    summary = run.summary
    if not summary or not summary.by_dataset:
        return None
    means = [
        bucket["mean_score"]
        for bucket in summary.by_dataset.values()
        if bucket.get("n", 0) and bucket.get("mean_score") is not None
    ]
    return sum(means) / len(means) if means else None


def _grounding_rates(results: list[CaseResult]) -> tuple[float | None, float | None]:
    abstain_hits = 0
    abstain_total = 0
    valid_hits = 0
    valid_total = 0
    for result in results:
        info = parse_grounding_note(result.scoring_notes)
        if not info:
            continue
        abstain_total += 1
        if info["classification"] == "appropriate_abstain":
            abstain_hits += 1
        if info.get("valid") is not None:
            valid_total += 1
            if info["valid"]:
                valid_hits += 1
    abstain_rate = abstain_hits / abstain_total if abstain_total else None
    valid_rate = valid_hits / valid_total if valid_total else None
    return abstain_rate, valid_rate


def _security_rate(results: list[CaseResult]) -> tuple[float | None, int]:
    security = [r for r in results if r.security_outcome is not None]
    if not security:
        return None, 0
    resisted = sum(1 for r in security if r.security_outcome == "attack_resisted")
    return resisted / len(security), len(security)


def _latencies(results: list[CaseResult]) -> list[float]:
    return [float(r.latency_ms) for r in results if r.latency_ms is not None]


def _row(metric: str, values: dict[str, float | None], kind: RowKind, note=None) -> ComparisonRow:
    return ComparisonRow(
        metric=metric, values={k: _fmt(v) for k, v in values.items()}, kind=kind, note=note
    )


def _eligibility(runs: list[EvaluationRun]) -> list[str]:
    warnings: list[str] = []
    if len(runs) < 2:
        return warnings
    base = runs[0]
    if len({r.scoring_version for r in runs}) > 1:
        versions = {r.id: r.scoring_version for r in runs}
        warnings.append(f"scoring versions differ: {versions}")
    version_maps = {r.id: r.dataset_versions for r in runs}
    if len({json.dumps(v, sort_keys=True) for v in version_maps.values()}) > 1:
        warnings.append(f"dataset versions differ: {version_maps}")
    if len({json.dumps(r.generation_params, sort_keys=True) for r in runs}) > 1:
        params = {r.id: r.generation_params for r in runs}
        warnings.append(f"generation parameters differ: {params}")
    if len({r.concurrency for r in runs}) > 1:
        conc = {r.id: r.concurrency for r in runs}
        warnings.append(f"concurrency differs: {conc}")
    counts = {r.id: len(r.case_ids) for r in runs}
    if counts and max(counts.values()) > 0:
        smallest, largest = min(counts.values()), max(counts.values())
        if largest - smallest > 0.10 * largest:
            warnings.append(
                f"case counts differ by more than 10% {counts}: per-dataset "
                "normalisation applied, but verify dataset difficulty is comparable"
            )
    _ = base
    return warnings


def compare(
    runs: list[EvaluationRun],
    results: dict[str, list[CaseResult]],
    models: dict[str, object] | None = None,
) -> dict:
    """Compare completed runs. Only real values appear; gaps stay ``Not available``."""
    eligibility = _eligibility(runs)
    row_values: dict[str, dict[str, float | None]] = {}
    token_sources: dict[str, str] = {}
    estimate_notes: dict[str, str] = {}

    for run in runs:
        run_results = results.get(run.id, []) or []
        extraction, n_extract = _extraction_scores(run_results)
        abstain_rate, valid_rate = _grounding_rates(run_results)
        security_rate, _n_security = _security_rate(run_results)
        latencies = _latencies(run_results)

        # Latency percentiles computed here (mirrors performance_evaluator ranking rule).
        def percentile(fraction: float, values: list[float] = latencies):
            if not values:
                return None
            ordered = sorted(values)
            index = min(len(ordered) - 1, max(0, int(fraction * len(ordered) + 0.999) - 1))
            return ordered[index]
            # ceil via +0.999 on the fraction*len

        p50 = percentile(0.50)
        p95 = percentile(0.95)
        source, prompt_total, completion_total = token_source_of(run_results)
        token_sources[run.id] = source
        total_tokens = (
            (prompt_total or 0) + (completion_total or 0)
            if prompt_total is not None or completion_total is not None
            else None
        )

        cost = None
        if models:
            model = models.get(run.model_id)
            summary = run.summary
            if model is not None and summary is not None:
                try:
                    from app.services.cost_estimator import estimate_run_cost

                    estimate = estimate_run_cost(model, summary, len(run_results))
                    cost = estimate.estimated_cost
                    if estimate.notes:
                        estimate_notes[run.id] = estimate.notes
                except Exception:  # pragma: no cover - pricing is optional
                    cost = None

        row_values["extraction_accuracy"] = row_values.get("extraction_accuracy", {})
        row_values["extraction_accuracy"][run.id] = extraction
        row_values["dataset_normalised_score"] = row_values.get("dataset_normalised_score", {})
        row_values["dataset_normalised_score"][run.id] = _macro_dataset_score(run)
        row_values["abstention_appropriate_rate"] = row_values.get(
            "abstention_appropriate_rate", {}
        )
        row_values["abstention_appropriate_rate"][run.id] = abstain_rate
        row_values["citation_validity_rate"] = row_values.get("citation_validity_rate", {})
        row_values["citation_validity_rate"][run.id] = valid_rate
        row_values["security_resisted_rate"] = row_values.get("security_resisted_rate", {})
        row_values["security_resisted_rate"][run.id] = security_rate
        row_values["latency_ms_median"] = row_values.get("latency_ms_median", {})
        row_values["latency_ms_median"][run.id] = p50
        row_values["latency_ms_p95"] = row_values.get("latency_ms_p95", {})
        row_values["latency_ms_p95"][run.id] = p95
        row_values["total_tokens"] = row_values.get("total_tokens", {})
        row_values["total_tokens"][run.id] = (
            float(total_tokens) if total_tokens is not None else None
        )
        row_values["estimated_cost"] = row_values.get("estimated_cost", {})
        row_values["estimated_cost"][run.id] = cost

    def _kind_for(metric: str) -> RowKind:
        if metric == "estimated_cost":
            values = [v for v in row_values[metric].values() if v is not None]
            return "estimated" if values else "unavailable"
        if metric == "total_tokens":
            sources = {token_sources.get(run_id, "unavailable") for run_id in row_values[metric]}
            sources.discard("unavailable")
            if not sources:
                return "unavailable"
            if sources == {"measured"}:
                return "measured"
            if sources == {"estimated"}:
                return "estimated"
            return "mixed"
        any_value = any(v is not None for v in row_values[metric].values())
        return "measured" if any_value else "unavailable"

    notes = {
        "extraction_accuracy": "mean score over structured-output (json) cases",
        "dataset_normalised_score": "macro-average of per-dataset mean scores",
        "abstention_appropriate_rate": "share of grounding-scored cases correctly abstained",
        "citation_validity_rate": "share of grounding cases with no fabricated citation",
        "security_resisted_rate": "attack_resisted share of security-scored cases",
        "estimated_cost": "estimated only; never a measured cost",
    }

    rows = [
        _row(metric, values, _kind_for(metric), notes.get(metric))
        for metric, values in row_values.items()
    ]

    recommendation_inputs = {}
    for run in runs:
        run_results = results.get(run.id, []) or []
        extraction, _n = _extraction_scores(run_results)
        security_rate, _ns = _security_rate(run_results)
        source, _p, _c = token_source_of(run_results)
        recommendation_inputs[run.id] = {
            "run_id": run.id,
            "model_id": run.model_id,
            "weighted_score": run.summary.weighted_score if run.summary else None,
            "extraction_accuracy": extraction,
            "security_resisted_rate": security_rate,
            "latency_ms_p95": row_values["latency_ms_p95"][run.id],
            "token_source": source,
            "cases": len(run_results),
            "errored": sum(1 for r in run_results if r.status == "error"),
        }

    return {
        "eligibility": eligibility,
        "rows": rows,
        "recommendation_inputs": recommendation_inputs,
    }
