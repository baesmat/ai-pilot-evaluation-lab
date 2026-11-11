"""Comparison engine: eligibility warnings, honest rows, normalisation."""

from __future__ import annotations

from datetime import datetime

from app.models.result import CaseResult, EvaluationRun, RunSummary, TokenUsage
from app.services.comparison_engine import compare
from app.services.grounding_evaluator import grounding_note


def run_with_id(run_id, n_cases=10, **kw):
    defaults = dict(
        id=run_id,
        model_id=f"m-{run_id}",
        model_identifier="org/m",
        endpoint_label="http://127.0.0.1:1",
        dataset_names=["d"],
        dataset_versions={"d": "aaa"},
        case_ids=[f"c{i}" for i in range(n_cases)],
        generation_params={"temperature": 0.2},
        concurrency=1,
        scoring_version="1.0.0",
        app_version="0.1.0",
        status="completed",
        requested_at=datetime.utcnow(),
    )
    defaults.update(kw)
    return EvaluationRun(**defaults)


def case(run_id, **kw):
    defaults = dict(
        run_id=run_id, case_id="c1", dataset="d", status="passed", score=1.0, latency_ms=10.0
    )
    defaults.update(kw)
    return CaseResult(**defaults)


def test_identical_runs_no_warnings():
    runs = [run_with_id("a"), run_with_id("b")]
    out = compare(runs, {"a": [], "b": []})
    assert out["eligibility"] == []


def test_dataset_version_mismatch_warns():
    runs = [run_with_id("a"), run_with_id("b", dataset_versions={"d": "bbb"})]
    out = compare(runs, {"a": [], "b": []})
    assert any("dataset versions differ" in w for w in out["eligibility"])


def test_case_count_gap_warns():
    runs = [run_with_id("a", n_cases=100), run_with_id("b", n_cases=50)]
    out = compare(runs, {"a": [], "b": []})
    assert any("more than 10%" in w for w in out["eligibility"])


def test_generation_params_and_concurrency_warn():
    runs = [
        run_with_id("a"),
        run_with_id("b", generation_params={"temperature": 0.9}, concurrency=2),
    ]
    out = compare(runs, {"a": [], "b": []})
    joined = " | ".join(out["eligibility"])
    assert "generation parameters differ" in joined
    assert "concurrency differ" in joined


def test_rows_present_and_measured():
    runs = [run_with_id("a"), run_with_id("b")]
    results = {
        "a": [
            case(
                "a",
                case_id="c1",
                latency_ms=10.0,
                scoring_notes="method=json_schema;structured_ok=1",
            ),
            case("a", case_id="c2", latency_ms=30.0, security_outcome="attack_resisted"),
        ],
        "b": [
            case(
                "b",
                case_id="c1",
                status="failed",
                score=0.0,
                latency_ms=20.0,
                scoring_notes="method=json_schema;structured_ok=0",
            ),
        ],
    }
    out = compare(runs, results)
    metrics = {row.metric: row for row in out["rows"]}
    for expected in (
        "extraction_accuracy",
        "security_resisted_rate",
        "latency_ms_median",
        "latency_ms_p95",
        "total_tokens",
        "estimated_cost",
    ):
        assert expected in metrics
    assert metrics["extraction_accuracy"].kind == "measured"
    assert metrics["extraction_accuracy"].values["a"] != "Not available"
    assert metrics["estimated_cost"].kind == "unavailable"  # no pricing passed
    assert metrics["latency_ms_median"].values["a"] != "Not available"
    rec = out["recommendation_inputs"]["a"]
    assert rec["security_resisted_rate"] == 1.0  # 1 of 1 security-scored case resisted
    assert rec["cases"] == 2


def test_token_row_kind_mixed():
    runs = [run_with_id("a"), run_with_id("b")]
    results = {
        "a": [case("a", token_usage=TokenUsage(prompt_tokens=5, source="measured"))],
        "b": [case("b", token_usage=TokenUsage(prompt_tokens=5, source="estimated"))],
    }
    out = compare(runs, results)
    tokens = next(r for r in out["rows"] if r.metric == "total_tokens")
    assert tokens.kind == "mixed"
    assert tokens.values["a"] != "Not available"


def test_grounding_rates_from_notes():
    note_ok = grounding_note(
        type(
            "GO",
            (),
            {
                "classification": "appropriate_abstain",
                "citations_valid": True,
                "citation_supported": True,
            },
        )
    )
    runs = [run_with_id("a")]
    results = {"a": [case("a", scoring_notes=f"method=abstain_or_answer;{note_ok}")]}
    out = compare(runs, results)
    abstain = next(r for r in out["rows"] if r.metric == "abstention_appropriate_rate")
    assert abstain.values["a"] == "1.0000"
    valid = next(r for r in out["rows"] if r.metric == "citation_validity_rate")
    assert valid.values["a"] == "1.0000"


def test_summary_weighted_used_for_recommendation_inputs():
    runs = [run_with_id("a", summary=RunSummary(weighted_score=0.7))]
    out = compare(runs, {"a": [case("a")]})
    assert out["recommendation_inputs"]["a"]["weighted_score"] == 0.7
