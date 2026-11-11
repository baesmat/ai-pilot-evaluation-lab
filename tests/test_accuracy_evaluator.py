"""Accuracy scoring: every method, partial credit, no free full scores."""

from __future__ import annotations

from app.services import accuracy_evaluator as acc
from tests.conftest import make_case, make_completion


def test_extract_json_variants():
    assert acc.extract_json('{"a": 1}') == {"a": 1}
    assert acc.extract_json('text before ```json\n{"a": 1}\n``` after') == {"a": 1}
    assert acc.extract_json('junk {"a": {"b": 2}} trailing') == {"a": {"b": 2}}
    assert acc.extract_json("[1, 2, 3]") == [1, 2, 3]
    assert acc.extract_json("not json {") is None
    assert acc.extract_json("") is None


def test_normalize_recurses():
    assert acc.normalize({"A": [" B ", 1]}) == {"a": ["b", 1]}
    assert acc.normalize("  Hi   There ") == "hi there"


def test_exact_match():
    case = make_case(expected_answer="The Answer")
    ok = acc.score_case(case, make_completion(content="the   answer"))
    assert ok.score == 1.0 and ok.field_results[0].correct
    miss = acc.score_case(case, make_completion(content="different"))
    assert miss.score == 0.0


def test_json_exact():
    case = make_case(
        evaluation_method="json_exact",
        expected_output={"a": 1, "b": "x"},
        expected_answer=None,
    )
    assert acc.score_case(case, make_content('{"a":1,"b":"x"}')).score == 1.0
    assert acc.score_case(case, make_content('{"a":2,"b":"x"}')).score == 0.0
    bad = acc.score_case(case, make_content("no json"))
    assert bad.score == 0.0 and bad.structured_ok is False


def test_json_schema_partial_credit():
    case = make_case(
        evaluation_method="json_schema",
        expected_output={"name": "lab", "count": 2},
        expected_answer=None,
    )
    outcome = acc.score_case(case, make_content('{"name": "LAB", "count": 5}'))
    assert outcome.score == 0.5  # name correct, count wrong: partial only
    fields = {f.field: f.correct for f in outcome.field_results}
    assert fields == {"name": True, "count": False}
    assert outcome.structured_ok is True


def test_numeric_match_tolerance():
    case = make_case(
        evaluation_method="numeric_match",
        expected_output={"value": 3.14},
        tolerance=0.01,
        expected_answer=None,
    )
    assert acc.score_case(case, make_content("value: 3.145")).score == 1.0
    assert acc.score_case(case, make_content("value: 4")).score == 0.0


def test_numeric_match_two_fields_partial():
    case = make_case(
        evaluation_method="numeric_match",
        expected_output={"a": 1, "b": 2},
        expected_answer=None,
    )
    outcome = acc.score_case(case, make_content("a=1 b=9"))
    assert outcome.score == 0.5


def test_set_match_jaccard_partial():
    case = make_case(
        evaluation_method="set_match",
        expected_output={"items": ["alpha", "beta"]},
        expected_answer=None,
    )
    outcome = acc.score_case(case, make_content('{"items": ["Alpha", "gamma"]}'))
    # intersection {alpha}, union {alpha,beta,gamma} -> 1/3; never full credit
    assert abs(outcome.score - 1 / 3) < 1e-6
    exact = acc.score_case(case, make_content('{"items": ["beta", "alpha"]}'))
    assert exact.score == 1.0


def test_contains_all_fraction():
    case = make_case(
        evaluation_method="contains_all",
        expected_output={"contains": ["foo", "bar", "baz"]},
        expected_answer=None,
    )
    outcome = acc.score_case(case, make_content("foo and BAR here"))
    assert abs(outcome.score - 2 / 3) < 1e-6
    assert len(outcome.field_results) == 3


def test_rubric_weighted_and_human_review():
    from app.models.benchmark import RubricCriterion

    case = make_case(
        evaluation_method="rubric",
        expected_answer=None,
        rubric=[
            RubricCriterion(name="has_hi", weight=2.0, check={"type": "contains", "value": "hi"}),
            RubricCriterion(name="len", weight=1.0, check={"type": "min_length", "value": 3}),
            RubricCriterion(name="manual", weight=2.0, check=None),
        ],
    )
    outcome = acc.score_case(case, make_content("hi there"))
    # earned 3 of 5 weight; manual check explicitly noted for human review
    assert abs(outcome.score - 3 / 5) < 1e-6
    assert outcome.notes is not None and "requires human review" in outcome.notes


def test_rubric_no_check_is_zero_not_full():
    from app.models.benchmark import RubricCriterion

    case = make_case(
        evaluation_method="rubric",
        expected_answer=None,
        rubric=[RubricCriterion(name="manual only", weight=1.0, check=None)],
    )
    outcome = acc.score_case(case, make_content("anything"))
    assert outcome.score == 0.0
    assert "requires human review" in (outcome.notes or "")


def test_abstain_or_answer_routes_to_grounding():
    case = make_case(
        evaluation_method="abstain_or_answer",
        expected_answer=None,
        expected_output={"abstain": True},
    )
    outcome = acc.score_case(case, make_content('{"abstain": true}'))
    assert outcome.score == 1.0
    assert "grounding:appropriate_abstain" in (outcome.notes or "")


def make_content(text: str):
    return make_completion(content=text)
