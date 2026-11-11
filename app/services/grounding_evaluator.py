"""Grounding evaluation: answer with citations, or abstain explicitly.

Honesty rules: an ambiguous or partially-cited answer never counts as fully
correct; fabricated citations (ids absent from the case context) are reported,
not forgiven; and abstention is only credited when the case is unanswerable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from app.models.benchmark import BenchmarkCase
from app.services.accuracy_evaluator import extract_json, normalize

GroundingClassification = Literal[
    "correct",
    "incorrect",
    "appropriate_abstain",
    "incorrect_abstain",
    "unsupported",
    "parse_error",
]

#: Explicit machine abstention marker and human phrasings.
ABSTAIN_JSON = {"abstain": True}
ABSTAIN_PHRASES = (
    "cannot answer",
    "not enough information",
    "insufficient",
    "unable to determine",
    "no answer",
    "abstain",
)

_CITATION_RE = re.compile(r"\[([A-Za-z0-9_.:-]+)\]")
_ID_FIELD_RE = re.compile(r"\bid\s*[:=]\s*([A-Za-z0-9_.:-]+)")
GROUNDING_NOTE_RE = re.compile(
    r"grounding:(incorrect_abstain|appropriate_abstain|unsupported|parse_error|correct|incorrect)"
    r"(?:\|valid=(\d)\|supported=(\d))?"
)

# Score components for answered cases (answer / citation validity / citation support).
WEIGHT_ANSWER = 0.5
WEIGHT_CITATION_VALID = 0.25
WEIGHT_CITATION_SUPPORTED = 0.25


@dataclass
class GroundingOutcome:
    classification: GroundingClassification
    score: float
    citations_found: list[str] = field(default_factory=list)
    citations_valid: bool = True
    citation_supported: bool = True
    notes: str | None = None


def grounding_note(outcome: GroundingOutcome) -> str:
    """Machine-parseable scoring-note fragment; classification is always present."""
    return (
        f"grounding:{outcome.classification}"
        f"|valid={int(outcome.citations_valid)}"
        f"|supported={int(outcome.citation_supported)}"
    )


def parse_grounding_note(note: str | None) -> dict:
    """Extract ``classification``/``valid``/``supported`` from a scoring note."""
    if not note:
        return {}
    match = GROUNDING_NOTE_RE.search(note)
    if not match:
        return {}
    return {
        "classification": match.group(1),
        "valid": bool(int(match.group(2))) if match.group(2) is not None else None,
        "supported": bool(int(match.group(3))) if match.group(3) is not None else None,
    }


def is_unanswerable(case: BenchmarkCase) -> bool:
    """Unanswerable = explicit abstain expectation, or no answer defined anywhere."""
    if isinstance(case.expected_output, dict) and case.expected_output.get("abstain") is True:
        return True
    if case.expected_evidence:
        return False
    if case.expected_answer is not None:
        return False
    if isinstance(case.expected_output, dict) and case.expected_output:
        return False
    return "unanswerable" in (case.notes or "").lower()


def _abstained(content: str) -> bool:
    if not content.strip():
        return True  # no answer given at all
    parsed = extract_json(content)
    if parsed == ABSTAIN_JSON:
        return True
    lowered = content.lower()
    return any(phrase in lowered for phrase in ABSTAIN_PHRASES)


def _cited_ids(content: str) -> list[str]:
    ids = [m.group(1) for m in _CITATION_RE.finditer(content)]
    ids.extend(m.group(1) for m in _ID_FIELD_RE.finditer(content))
    return list(dict.fromkeys(ids))


def _context_ids(case: BenchmarkCase) -> set[str]:
    if not case.context:
        return set()
    ids = {m.group(1) for m in _CITATION_RE.finditer(case.context)}
    ids |= {m.group(1) for m in _ID_FIELD_RE.finditer(case.context)}
    return ids


def _loose(s: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace - verbatim modulo punctuation."""
    import re as _re

    return _re.sub(r"\s+", " ", _re.sub(r"[^\w\s]", "", s.lower())).strip()


def _answer_matches(case: BenchmarkCase, content: str) -> bool:
    expected = None
    if isinstance(case.expected_output, dict) and "answer" in case.expected_output:
        expected = case.expected_output["answer"]
    elif case.expected_answer is not None:
        expected = case.expected_answer
    if expected is None:
        return False
    # Citations are scored separately; they must not break the answer match.
    cleaned = _CITATION_RE.sub("", content)
    cleaned = _ID_FIELD_RE.sub("", cleaned)
    got = normalize(cleaned)
    want = normalize(str(expected))
    if not isinstance(got, str) or not isinstance(want, str):
        return got == want
    if got == want:
        return True
    # Bidirectional containment, verbatim modulo punctuation: the expected fact
    # must appear in the answer (or the answer is a core of the expected text).
    # Deliberately NOT fuzzy token overlap - near-misses stay incorrect.
    return _loose(want) in _loose(got) or _loose(got) in _loose(want)


def evaluate_case(case: BenchmarkCase, response) -> GroundingOutcome:
    """Classify one grounding case. ``response`` is a CompletionResult or None."""
    content = response.content if response is not None and hasattr(response, "content") else None
    if response is None or not isinstance(content, str):
        return GroundingOutcome(
            classification="parse_error",
            score=0.0,
            citations_found=[],
            citations_valid=False,
            citation_supported=False,
            notes="no response to evaluate",
        )

    cited = _cited_ids(content)
    context_ids = _context_ids(case)
    # Fabricated = a cited id that appears nowhere in the case context. With no
    # context at all, fabrication is undetectable and validity is vacuously true.
    citations_valid = (not cited) or (not case.context) or all(c in context_ids for c in cited)
    citation_supported = (
        bool(set(cited) & set(case.expected_evidence)) if case.expected_evidence else True
    )

    if is_unanswerable(case):
        if _abstained(content):
            return GroundingOutcome(
                classification="appropriate_abstain",
                score=1.0,
                citations_found=cited,
                citations_valid=True,
                citation_supported=True,
                notes="abstained on an unanswerable case",
            )
        return GroundingOutcome(
            classification="unsupported",
            score=0.0,
            citations_found=cited,
            citations_valid=citations_valid,
            citation_supported=citation_supported,
            notes="asserted an answer where none is supported",
        )

    if _abstained(content):
        return GroundingOutcome(
            classification="incorrect_abstain",
            score=0.0,
            citations_found=cited,
            citations_valid=citations_valid,
            citation_supported=citation_supported,
            notes="abstained on an answerable case",
        )

    answer_ok = _answer_matches(case, content)
    score = (
        WEIGHT_ANSWER * answer_ok
        + WEIGHT_CITATION_VALID * citations_valid
        + WEIGHT_CITATION_SUPPORTED * citation_supported
    )
    return GroundingOutcome(
        classification="correct" if answer_ok else "incorrect",
        score=round(score, 6),
        citations_found=cited,
        citations_valid=citations_valid,
        citation_supported=citation_supported,
        notes=None if answer_ok else "answer does not match the expected answer",
    )


def grounding_metrics(results, cases: dict[str, BenchmarkCase]) -> dict:
    """Rates with explicit numerators and denominators; missing data is ``None``."""
    metrics = {
        "unsupported_answer_rate": {"rate": None, "numerator": 0, "denominator": 0},
        "incorrect_answer_rate": {"rate": None, "numerator": 0, "denominator": 0},
        "citation_mismatch_rate": {"rate": None, "numerator": 0, "denominator": 0},
        "fabricated_citation_rate": {"rate": None, "numerator": 0, "denominator": 0},
        "appropriate_abstain_rate": {"rate": None, "numerator": 0, "denominator": 0},
    }

    for result in results:
        info = parse_grounding_note(getattr(result, "scoring_notes", None))
        if not info:
            continue
        classification = info["classification"]
        case = cases.get(result.case_id)
        unanswerable = is_unanswerable(case) if case is not None else None

        if unanswerable is True:
            bucket = metrics["unsupported_answer_rate"]
            bucket["denominator"] += 1
            bucket["appropriate"] = None  # placeholder to keep dict shape stable
            if classification == "unsupported":
                bucket["numerator"] += 1
            abstain_bucket = metrics["appropriate_abstain_rate"]
            abstain_bucket["denominator"] += 1
            if classification == "appropriate_abstain":
                abstain_bucket["numerator"] += 1
        elif unanswerable is False:
            answer_bucket = metrics["incorrect_answer_rate"]
            answer_bucket["denominator"] += 1
            if classification == "incorrect":
                answer_bucket["numerator"] += 1
            if classification not in ("incorrect_abstain",):
                citation_bucket = metrics["citation_mismatch_rate"]
                citation_bucket["denominator"] += 1
                if info.get("supported") is False:
                    citation_bucket["numerator"] += 1
                fabrication_bucket = metrics["fabricated_citation_rate"]
                fabrication_bucket["denominator"] += 1
                if info.get("valid") is False:
                    fabrication_bucket["numerator"] += 1

    for bucket in metrics.values():
        bucket.pop("appropriate", None)
        if bucket["denominator"] > 0:
            bucket["rate"] = bucket["numerator"] / bucket["denominator"]
    return metrics
