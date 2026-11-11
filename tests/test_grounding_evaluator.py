"""Grounding: classifications, citation validation, honest rate denominators."""

from __future__ import annotations

from app.models.result import CaseResult
from app.services.grounding_evaluator import (
    evaluate_case,
    grounding_metrics,
    grounding_note,
    parse_grounding_note,
)
from tests.conftest import make_case, make_completion

CTX = "Report text [E1] more text [E2] and id: E3"


def answerable_case(**kw):
    return make_case(
        id="ans1",
        context=CTX,
        expected_evidence=["E1"],
        expected_answer="Paris",
        expected_output=None,
        **kw,
    )


def test_appropriate_abstain_json():
    case = make_case(id="un1", expected_output={"abstain": True}, expected_answer=None)
    outcome = evaluate_case(case, make_completion(content='{"abstain": true}'))
    assert outcome.classification == "appropriate_abstain"
    assert outcome.score == 1.0


def test_appropriate_abstain_phrase():
    case = make_case(id="un2", notes="unanswerable without the document", expected_answer=None)
    outcome = evaluate_case(
        case, make_completion(content="There is not enough information to answer.")
    )
    assert outcome.classification == "appropriate_abstain"


def test_unsupported_fabricated_answer():
    case = make_case(id="un3", expected_output={"abstain": True}, expected_answer=None)
    outcome = evaluate_case(
        case,
        make_completion(
            content="The capital is Paris [E9].",
        ),
    )
    assert outcome.classification == "unsupported"
    assert outcome.score == 0.0
    assert outcome.citations_valid is True  # no context to check against
    assert outcome.citation_supported is True  # no expected evidence -> vacuously satisfied


def test_incorrect_abstain_on_answerable():
    case = answerable_case()
    outcome = evaluate_case(case, make_completion(content="cannot answer"))
    assert outcome.classification == "incorrect_abstain"
    assert outcome.score == 0.0


def test_correct_full_score():
    case = answerable_case()
    outcome = evaluate_case(case, make_completion(content="Paris [E1]"))
    assert outcome.classification == "correct"
    assert outcome.score == 1.0
    assert outcome.citations_found == ["E1"]
    assert outcome.citations_valid and outcome.citation_supported


def test_partial_credit_for_bad_citations():
    case = answerable_case()
    # answer right, citation fabricated (E9 not in context) and not the expected one
    outcome = evaluate_case(case, make_completion(content="Paris [E9]"))
    assert outcome.classification == "correct"  # answer itself matches
    assert outcome.citations_valid is False
    assert outcome.citation_supported is False
    assert abs(outcome.score - 0.5) < 1e-9  # 0.5 answer + 0 valid + 0 supported


def test_wrong_answer_partial_citation_credit():
    case = answerable_case()
    outcome = evaluate_case(case, make_content("Lyon [E1]"))
    assert outcome.classification == "incorrect"
    # 0.5*0 (wrong answer) + 0.25 (valid citation) + 0.25 (supported) = 0.5
    assert abs(outcome.score - 0.5) < 1e-9


def test_parse_error_on_none():
    outcome = evaluate_case(answerable_case(), None)
    assert outcome.classification == "parse_error"
    assert outcome.score == 0.0


def test_note_roundtrip():
    outcome = evaluate_case(answerable_case(), make_content("Paris [E1]"))
    note = grounding_note(outcome)
    info = parse_grounding_note(f"method=abstain_or_answer;{note};extra")
    assert info["classification"] == "correct"
    assert info["valid"] is True and info["supported"] is True


def make_content(text):
    return make_completion(content=text)


def _result(case_id, note, status="passed"):
    return CaseResult(
        run_id="r1",
        case_id=case_id,
        dataset="grounding",
        status=status,
        score=1.0,
        scoring_notes=note,
    )


def test_metrics_denominators_and_rates():
    unanswerable = make_case(id="u1", expected_output={"abstain": True}, expected_answer=None)
    answerable = answerable_case()
    cases = {"u1": unanswerable, "a1": answerable}
    results = [
        _result(
            "u1", grounding_note(evaluate_case(unanswerable, make_content('{"abstain": true}')))
        ),
        _result(
            "u1",
            grounding_note(evaluate_case(unanswerable, make_content("Paris"))),
            status="failed",
        ),
        _result("a1", grounding_note(evaluate_case(answerable, make_content("Paris [E1]")))),
        _result(
            "a1",
            grounding_note(evaluate_case(answerable, make_content("Nope [E9]"))),
            status="failed",
        ),
        _result(
            "a1",
            grounding_note(evaluate_case(answerable, make_content("cannot answer"))),
            status="failed",
        ),
    ]
    metrics = grounding_metrics(results, cases)
    # every denominator present and consistent
    assert metrics["appropriate_abstain_rate"]["denominator"] == 2
    assert metrics["appropriate_abstain_rate"]["numerator"] == 1
    assert abs(metrics["appropriate_abstain_rate"]["rate"] - 0.5) < 1e-9
    assert metrics["unsupported_answer_rate"]["denominator"] == 2
    assert metrics["unsupported_answer_rate"]["numerator"] == 1
    assert metrics["incorrect_answer_rate"]["denominator"] == 3
    assert metrics["incorrect_answer_rate"]["numerator"] == 1
    # fabricated: E9 cited, not in context -> invalid; abstention results carry no
    # citation verdict and are excluded from the denominator
    fabricated = metrics["fabricated_citation_rate"]
    assert fabricated["denominator"] == 2
    assert fabricated["numerator"] == 1
    assert abs(fabricated["rate"] - 0.5) < 1e-9
    mismatch = metrics["citation_mismatch_rate"]
    assert mismatch["denominator"] == 2
    assert mismatch["numerator"] == 1


def test_metrics_empty_is_honest_none():
    metrics = grounding_metrics([], {})
    for bucket in metrics.values():
        assert bucket["denominator"] == 0
        assert bucket["numerator"] == 0
        assert bucket["rate"] is None
