"""Reports: recommendation rules, PDF smoke, markdown sections, missing data."""

from __future__ import annotations

from datetime import datetime

from app.models.governance import AssessmentItem, EnterpriseAssessment
from app.models.result import CaseResult, EvaluationRun, RunSummary
from app.services.report_generator import (
    RECOMMENDATIONS,
    generate_markdown,
    generate_report,
    recommend,
)

SECTION_HEADERS_EXPECTED = [
    "Executive Summary",
    "Reproducibility",
    "Supporting Evidence",
]


def make_run(**kw) -> EvaluationRun:
    defaults = dict(
        id="run1",
        model_id="m1",
        model_identifier="org/m",
        endpoint_label="http://127.0.0.1:1",
        dataset_names=["d"],
        dataset_versions={"d": "abc123"},
        case_ids=[f"c{i}" for i in range(12)],
        generation_params={"temperature": 0.2},
        scoring_version="1.0.0",
        app_version="0.1.0",
        git_commit=None,
        status="completed",
        requested_at=datetime.utcnow(),
    )
    defaults.update(kw)
    return EvaluationRun(**defaults)


def case(i, status="passed", score=1.0):
    return CaseResult(run_id="run1", case_id=f"c{i}", dataset="d", status=status, score=score)


def test_recommendation_labels_and_no_production_wording():
    text = " ".join(RECOMMENDATIONS.values()).lower()
    assert "production approved" not in text
    assert set(RECOMMENDATIONS) == {
        "candidate",
        "additional_testing",
        "not_recommended",
        "insufficient_data",
    }


def test_recommend_insufficient_data():
    run = make_run()
    outcome, rationale = recommend(run, [case(1)], None)
    assert outcome == "insufficient_data"
    assert "1 case" in rationale or "1 case(s)" in rationale


def test_recommend_not_recommended_low_score():
    run = make_run(summary=RunSummary(weighted_score=0.3))
    results = [case(i, status="failed", score=0.3) for i in range(12)]
    outcome, rationale = recommend(run, results, None)
    assert outcome == "not_recommended"
    assert "0.30" in rationale


def test_recommend_candidate_without_assessment():
    run = make_run(summary=RunSummary(weighted_score=0.9))
    results = [case(i) for i in range(12)]
    outcome, rationale = recommend(run, results, None)
    assert outcome == "candidate"
    assert "assessment" in rationale.lower()


def test_recommend_additional_testing_mid_score():
    run = make_run(summary=RunSummary(weighted_score=0.6))
    results = [case(i, score=0.6) for i in range(12)]
    outcome, _r = recommend(run, results, None)
    assert outcome == "additional_testing"


def test_recommend_candidate_with_complete_assessment():
    run = make_run(summary=RunSummary(weighted_score=0.9))
    results = [case(i) for i in range(12)]
    completion = {"assessed": 10, "positive": 9, "positive_without_evidence": 0}
    outcome, rationale = recommend(run, results, completion)
    assert outcome == "candidate"
    assert "9/10" in rationale


def test_recommend_assessment_without_evidence_blocks_candidate():
    run = make_run(summary=RunSummary(weighted_score=0.9))
    results = [case(i) for i in range(12)]
    completion = {"assessed": 10, "positive": 9, "positive_without_evidence": 3}
    outcome, _r = recommend(run, results, completion)
    assert outcome == "additional_testing"


def test_markdown_contains_sections_and_estimated_labels():
    run = make_run(
        summary=RunSummary(
            total_cases=2,
            weighted_score=0.9,
            prompt_tokens=10,
            completion_tokens=5,
            token_source="measured",
        )
    )
    md = generate_markdown(run, [case(1), case(2)], None, [])
    for header in SECTION_HEADERS_EXPECTED:
        assert header in md
    assert "estimated" in md.lower() or "Estimated" in md
    assert "run1" in md  # reproducibility
    # assessment missing -> honest markers
    assert "Not available" in md or "no assessment recorded" in md


def test_markdown_with_assessment_and_reviews():
    from datetime import date

    from app.models.governance import HumanReview

    run = make_run(summary=RunSummary(weighted_score=0.9))
    assessment = EnterpriseAssessment(
        model_id="m1",
        items=[
            AssessmentItem(
                category="Security", item="Logging", status="meets_requirement", rationale="ok"
            )
        ],
    )
    review = HumanReview(model_id="m1", reviewer="A", review_date=date(2026, 1, 1))
    md = generate_markdown(run, [case(1)], assessment, [review])
    assert "Enterprise Assessment" in md
    assert "Human Review Records" in md
    assert "A 2026-01-01" in md


def test_pdf_generation_smoke(tmp_path):
    run = make_run(summary=RunSummary(total_cases=2, weighted_score=0.9))
    out = tmp_path / "report.pdf"
    result_path = generate_report(run, [case(1), case(2)], None, [], out)
    assert result_path == out
    assert out.exists() and out.stat().st_size > 1024
    assert out.read_bytes().startswith(b"%PDF")


def test_pdf_with_empty_results_and_missing_data(tmp_path):
    run = make_run()
    out = tmp_path / "empty.pdf"
    generate_report(run, [], None, [], out)  # must not raise
    assert out.stat().st_size > 1024
    md = generate_markdown(run, [], None, [])
    assert "Not available" in md


def test_errors_redacted_in_evidence(tmp_path):
    run = make_run(summary=RunSummary(weighted_score=0.0))
    result = CaseResult(
        run_id="run1",
        case_id="c1",
        dataset="d",
        status="error",
        score=0.0,
        error="Bearer abcdefgh123456 failed; api_key=hunter2 invalid",
    )
    md = generate_markdown(run, [result], None, [])
    assert "abcdefgh123456" not in md  # bearer redacted
