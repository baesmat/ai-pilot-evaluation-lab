"""Deterministic accuracy scoring.

Scoring honesty rules: partial answers earn partial credit only; missing data
scores zero; ambiguous results are never counted as full successes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from app.models.benchmark import BenchmarkCase
from app.models.result import FieldResult

SCORING_VERSION = "1.0.0"

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def extract_json(text: str) -> dict | list | None:
    """Parse JSON from raw text: direct, fenced ```json, then first balanced span."""
    if not isinstance(text, str) or not text.strip():
        return None
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```json\s*(.+?)```", stripped, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1).strip())
        except json.JSONDecodeError:
            pass
    for opener, closer in (("{", "}"), ("[", "]")):
        span = _balanced_span(stripped, opener, closer)
        if span:
            try:
                return json.loads(stripped[span[0] : span[1]])
            except json.JSONDecodeError:
                continue
    return None


def _balanced_span(text: str, opener: str, closer: str) -> tuple[int, int] | None:
    start = text.find(opener)
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return (start, index + 1)
    return None


def normalize(value):
    """Lowercase/strip strings (whitespace-collapsed); recurse dicts/lists."""
    if isinstance(value, str):
        return " ".join(value.lower().split())
    if isinstance(value, dict):
        return {str(k).lower(): normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(v) for v in value]
    return value


@dataclass
class ScoreOutcome:
    score: float
    field_results: list[FieldResult] = field(default_factory=list)
    structured_ok: bool = False
    notes: str | None = None


def _hashable(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, default=str)
    return value


def _expected_text(case: BenchmarkCase) -> str:
    if case.expected_answer is not None:
        return case.expected_answer
    if case.expected_output is not None:
        return json.dumps(case.expected_output, sort_keys=True, default=str)
    return ""


def _expected_numbers(case: BenchmarkCase) -> list[float]:
    numbers: list[float] = []
    if case.expected_output:
        for value in case.expected_output.values():
            if isinstance(value, bool):
                continue
            if (
                isinstance(value, (int, float))
                or isinstance(value, str)
                and _NUMBER_RE.fullmatch(value.strip())
            ):
                numbers.append(float(value))
    if case.expected_answer:
        numbers.extend(float(m) for m in _NUMBER_RE.findall(case.expected_answer))
    return numbers


def _split_items(text: str | None) -> list[str]:
    if not text:
        return []
    parts: list[str] = []
    for line in text.splitlines():
        parts.extend(p.strip() for p in line.split(",") if p.strip())
    return parts


def _expected_collection(case: BenchmarkCase) -> list | None:
    """Expected item set: expected_output['items'], any list value, or the answer split."""
    if isinstance(case.expected_output, dict):
        if isinstance(case.expected_output.get("items"), list):
            return case.expected_output["items"]
        for value in case.expected_output.values():
            if isinstance(value, list):
                return value
        return None
    if case.expected_answer:
        try:
            parsed = json.loads(case.expected_answer)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
        return _split_items(case.expected_answer)
    return None


def _response_collection(content: str | None) -> list:
    if not content:
        return []
    parsed = extract_json(content)
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
        return parsed["items"]
    return _split_items(content)


def _expected_contains(case: BenchmarkCase) -> list[str]:
    if isinstance(case.expected_output, dict):
        contains = case.expected_output.get("contains")
        if isinstance(contains, list):
            return [str(c) for c in contains]
        if isinstance(contains, str):
            return [contains]
    return [case.expected_answer] if case.expected_answer else []


def _score_exact_match(case: BenchmarkCase, content: str | None) -> ScoreOutcome:
    expected = _expected_text(case)
    correct = content is not None and normalize(content) == normalize(expected)
    return ScoreOutcome(
        score=1.0 if correct else 0.0,
        field_results=[
            FieldResult(field="output", expected=expected, actual=content, correct=correct)
        ],
        structured_ok=True,
        notes=None,
    )


def _score_json_exact(case: BenchmarkCase, content: str | None) -> ScoreOutcome:
    parsed = extract_json(content) if content else None
    expected = case.expected_output
    structured_ok = parsed is not None
    correct = (
        parsed is not None
        and expected is not None
        and _hashable(normalize(parsed)) == _hashable(normalize(expected))
    )
    notes = None if parsed is not None else "output is not valid JSON"
    return ScoreOutcome(
        score=1.0 if correct else 0.0,
        field_results=[
            FieldResult(field="output", expected=expected, actual=parsed, correct=correct)
        ],
        structured_ok=structured_ok,
        notes=notes,
    )


def _score_json_schema(case: BenchmarkCase, content: str | None) -> ScoreOutcome:
    expected_fields = case.expected_output if isinstance(case.expected_output, dict) else {}
    parsed = extract_json(content) if content else None
    if not expected_fields:
        return ScoreOutcome(
            score=0.0,
            field_results=[],
            structured_ok=parsed is not None,
            notes="no expected fields defined",
        )
    if not isinstance(parsed, dict):
        results = [
            FieldResult(field=field_name, expected=expected, actual=None, correct=False)
            for field_name, expected in expected_fields.items()
        ]
        note = None if content is None else "output is not a JSON object"
        return ScoreOutcome(score=0.0, field_results=results, structured_ok=False, notes=note)

    field_results: list[FieldResult] = []
    correct_count = 0
    for field_name, expected in expected_fields.items():
        actual = parsed.get(field_name) if field_name in parsed else None
        correct = field_name in parsed and _hashable(normalize(actual)) == _hashable(
            normalize(expected)
        )
        correct_count += 1 if correct else 0
        field_results.append(
            FieldResult(field=field_name, expected=expected, actual=actual, correct=correct)
        )
    score = correct_count / len(expected_fields)
    return ScoreOutcome(score=score, field_results=field_results, structured_ok=True, notes=None)


def _score_numeric_match(case: BenchmarkCase, content: str | None) -> ScoreOutcome:
    expected_numbers = _expected_numbers(case)
    tolerance = abs(case.tolerance)
    response_numbers = [float(m) for m in _NUMBER_RE.findall(content or "")]
    if not expected_numbers:
        return ScoreOutcome(
            score=0.0,
            field_results=[],
            structured_ok=True,
            notes="no numeric expectation defined",
        )
    field_results: list[FieldResult] = []
    correct_count = 0
    for expected in expected_numbers:
        correct = any(
            abs(candidate - expected) <= tolerance + 1e-9 for candidate in response_numbers
        )
        correct_count += 1 if correct else 0
        field_results.append(
            FieldResult(field="number", expected=expected, actual=content, correct=correct)
        )
    return ScoreOutcome(
        score=correct_count / len(expected_numbers),
        field_results=field_results,
        structured_ok=True,
        notes=None,
    )


def _score_set_match(case: BenchmarkCase, content: str | None) -> ScoreOutcome:
    expected_items = _expected_collection(case)
    if expected_items is None:
        return ScoreOutcome(
            score=0.0, field_results=[], structured_ok=False, notes="no expected item set"
        )
    actual_items = _response_collection(content)
    expected_set = {_hashable(normalize(item)) for item in expected_items}
    actual_set = {_hashable(normalize(item)) for item in actual_items}
    if expected_set or actual_set:
        union = expected_set | actual_set
        score = len(expected_set & actual_set) / len(union) if union else 1.0
    else:
        score = 1.0
    correct = expected_set == actual_set
    return ScoreOutcome(
        score=score,
        field_results=[
            FieldResult(
                field="items",
                expected=sorted(expected_set),
                actual=sorted(actual_set),
                correct=correct,
            )
        ],
        structured_ok=True,
        notes=None if correct else "set mismatch; partial jaccard credit",
    )


def _score_contains_all(case: BenchmarkCase, content: str | None) -> ScoreOutcome:
    expected_parts = _expected_contains(case)
    if not expected_parts:
        return ScoreOutcome(
            score=0.0, field_results=[], structured_ok=True, notes="no expected substrings"
        )
    haystack = normalize(content) if content else ""
    field_results: list[FieldResult] = []
    present_count = 0
    for part in expected_parts:
        present = normalize(part) in haystack
        present_count += 1 if present else 0
        field_results.append(
            FieldResult(field="contains", expected=part, actual=content, correct=present)
        )
    return ScoreOutcome(
        score=present_count / len(expected_parts),
        field_results=field_results,
        structured_ok=True,
        notes=None,
    )


def _run_check(check: dict | None, content: str) -> bool:
    """Deterministic rubric check. Unknown or missing checks are unsatisfied."""
    if not isinstance(check, dict):
        return False
    check_type = check.get("type")
    if check_type == "contains":
        values = check.get("value")
        values = values if isinstance(values, list) else [values]
        haystack = normalize(content)
        for value in values:
            if value is None:
                continue
            needle = normalize(value)
            if not isinstance(needle, str) or needle not in haystack:
                return False
        return True
    if check_type == "regex":
        pattern = check.get("pattern")
        if not isinstance(pattern, str):
            return False
        try:
            return re.search(pattern, content) is not None
        except re.error:
            return False
    if check_type == "json_field_equals":
        parsed = extract_json(content)
        if not isinstance(parsed, dict):
            return False
        field_name = check.get("field")
        if not isinstance(field_name, str) or field_name not in parsed:
            return False
        return _hashable(normalize(parsed[field_name])) == _hashable(normalize(check.get("value")))
    if check_type == "min_length":
        threshold = check.get("value", check.get("length", 0))
        try:
            return len(content) >= int(threshold)
        except (TypeError, ValueError):
            return False
    return False


def _score_rubric(case: BenchmarkCase, content: str | None) -> ScoreOutcome:
    criteria = case.rubric or []
    if not criteria:
        return ScoreOutcome(score=0.0, field_results=[], structured_ok=True, notes="empty rubric")
    total_weight = 0.0
    earned = 0.0
    notes: list[str] = []
    field_results: list[FieldResult] = []
    for criterion in criteria:
        total_weight += criterion.weight
        satisfied = _run_check(criterion.check, content or "")
        if satisfied:
            earned += criterion.weight
        elif criterion.check is None:
            notes.append(f"{criterion.name}: requires human review")
        else:
            notes.append(f"{criterion.name}: not satisfied")
        field_results.append(
            FieldResult(
                field=criterion.name, expected=criterion.check, actual=content, correct=satisfied
            )
        )
    score = earned / total_weight if total_weight > 0 else 0.0
    return ScoreOutcome(
        score=score,
        field_results=field_results,
        structured_ok=True,
        notes="; ".join(notes) if notes else None,
    )


def score_case(case: BenchmarkCase, response) -> ScoreOutcome:
    """Score one case. ``response`` is a CompletionResult or None (request failed)."""
    content = response.content if response is not None else None
    method = case.evaluation_method

    if method == "abstain_or_answer":
        # Grounding owns this method; accuracy only routes to it. Imported here to
        # avoid the mutual top-level import (grounding uses extract_json/normalize).
        from app.services.grounding_evaluator import evaluate_case, grounding_note

        outcome = evaluate_case(case, response)
        return ScoreOutcome(
            score=outcome.score,
            field_results=[],
            structured_ok=outcome.classification != "parse_error",
            notes=grounding_note(outcome),
        )
    if method == "exact_match":
        return _score_exact_match(case, content)
    if method == "json_exact":
        return _score_json_exact(case, content)
    if method == "json_schema":
        return _score_json_schema(case, content)
    if method == "numeric_match":
        return _score_numeric_match(case, content)
    if method == "set_match":
        return _score_set_match(case, content)
    if method == "contains_all":
        return _score_contains_all(case, content)
    if method == "rubric":
        return _score_rubric(case, content)
    raise ValueError(f"unknown evaluation method: {method!r}")
