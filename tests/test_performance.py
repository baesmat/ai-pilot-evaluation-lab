"""Performance summary: percentiles, token-source honesty, structured flags."""

from __future__ import annotations

from app.models.result import CaseResult, RunSummary, TokenUsage
from app.services.performance_evaluator import (
    compute_summary,
    latency_percentiles,
    structured_flag,
    token_source_of,
)


def result(**kw) -> CaseResult:
    defaults = dict(run_id="r", case_id="c", dataset="d", status="passed", score=1.0, weight=1.0)
    defaults.update(kw)
    return CaseResult(**defaults)


def test_latency_percentiles_empty():
    assert latency_percentiles([]) == {"p50": None, "p95": None, "min": None, "max": None}


def test_latency_percentiles_nearest_rank():
    p = latency_percentiles([5.0, 1.0, 4.0, 2.0, 3.0])
    assert p["min"] == 1.0 and p["max"] == 5.0
    assert p["p50"] == 3.0  # ceil(.5*5)=3rd value
    assert p["p95"] == 5.0  # ceil(.95*5)=5th value


def test_token_source_precedence():
    measured = result(
        token_usage=TokenUsage(prompt_tokens=10, completion_tokens=5, source="measured")
    )
    estimated = result(token_usage=TokenUsage(prompt_tokens=7, source="estimated"))
    none = result(token_usage=TokenUsage())

    assert token_source_of([measured, estimated])[0] == "measured"  # mixed -> measured
    assert token_source_of([estimated])[0] == "estimated"
    assert token_source_of([none, result()])[0] == "unavailable"

    source, prompt, completion = token_source_of([measured, estimated])
    assert (source, prompt, completion) == ("measured", 17, 5)
    assert token_source_of([result()])[1:] == (None, None)  # never invented


def test_structured_flag_parsing():
    assert structured_flag("method=json_schema;structured_ok=1") is True
    assert structured_flag("method=json_exact;structured_ok=0") is False
    assert structured_flag(None) is None
    assert structured_flag("no marker") is None


def test_compute_summary_counts_and_weighting():
    results = [
        result(case_id="1", score=1.0, weight=1.0, latency_ms=100.0),
        result(case_id="2", status="failed", score=0.5, weight=3.0, dataset="d2"),
        result(
            case_id="3",
            status="error",
            score=0.0,
            error="request timed out after retries",
            token_usage=TokenUsage(prompt_tokens=3, source="measured"),
        ),
        result(case_id="4", scoring_notes="structured_ok=1"),
        result(case_id="5", scoring_notes="structured_ok=0", status="failed", score=0.0),
    ]
    summary = compute_summary(object(), results)
    assert summary.total_cases == 5
    assert (summary.passed, summary.failed, summary.errored) == (2, 2, 1)
    # weighted over non-error: (1*1 + 0.5*3 + 1*1 + 0*1) / 6
    assert abs(summary.weighted_score - 3.5 / 6) < 1e-9
    assert summary.timeout_count == 1
    assert summary.structured_output_success_rate == 0.5
    assert summary.latency_ms_median == 100.0
    assert set(summary.by_dataset) == {"d", "d2"}
    assert summary.by_dataset["d2"]["n"] == 1
    assert summary.by_dataset["d2"]["mean_score"] == 0.5
    assert summary.token_source == "measured"
    assert summary.prompt_tokens == 3


def test_compute_summary_empty_run():
    summary = compute_summary(object(), [])
    assert summary.total_cases == 0
    assert summary.weighted_score is None
    assert summary.latency_ms_p95 is None
    assert summary.token_source == "unavailable"
    assert summary.structured_output_success_rate is None


def test_summary_never_labels_estimates_as_measured():
    results = [result(token_usage=TokenUsage(prompt_tokens=1, source="estimated"))]
    summary = compute_summary(object(), results)
    assert summary.token_source == "estimated"
    # RunSummary source stays within the declared literal set
    assert summary.token_source in ("measured", "estimated", "unavailable")


def test_summary_model_shape():
    summary = RunSummary()
    assert summary.total_cases == 0 and summary.token_source == "unavailable"
