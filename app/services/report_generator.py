"""Report generation: PDF (ReportLab) and Markdown mirror.

Every estimated number is labelled "estimated"; unavailable data reads
"Not available". Recommendations are advisory only — no "production
approved" wording exists anywhere in this module.
"""

from __future__ import annotations

import html
import json
import logging
import re
from datetime import datetime
from pathlib import Path

from app.models.governance import EnterpriseAssessment, HumanReview
from app.models.result import CaseResult, EvaluationRun
from app.security.secrets import safe_error

logger = logging.getLogger(__name__)

#: The four allowed recommendation outcomes (keys) and their display labels.
RECOMMENDATIONS = {
    "candidate": "Candidate for Further Evaluation",
    "additional_testing": "Additional Testing Required",
    "not_recommended": "Not Recommended",
    "insufficient_data": "Insufficient Data for Assessment",
}

SECTION_HEADERS = [
    "Executive Summary",
    "Evaluation Scope",
    "Models Evaluated",
    "Dataset Description",
    "Evaluation Methodology",
    "Recommendation",
    "Recommended Next Steps",
    "Reproducibility",
    "Per-Dataset Performance",
    "Latency",
    "Token Usage and Estimated Cost",
    "Enterprise Assessment",
    "Human Review Records",
    "Security Evaluation",
    "Grounding and Abstention",
    "Risks and Limitations",
    "Supporting Evidence",
]

PASS_THRESHOLD = 0.8


def _weighted_score(run: EvaluationRun, results: list[CaseResult]) -> float | None:
    if run.summary is not None and run.summary.weighted_score is not None:
        return run.summary.weighted_score
    scored = [r for r in results if r.status != "error"]
    weight = sum(r.weight for r in scored)
    if weight <= 0:
        return None
    return sum(r.score * r.weight for r in scored) / weight


def recommend(
    run: EvaluationRun,
    results: list[CaseResult],
    assessment_completion: dict | None = None,
) -> tuple[str, str]:
    """Advisory recommendation. Conservative defaults; coverage always cited."""
    total = len(results)
    errored = sum(1 for r in results if r.status == "error")
    coverage = f"{total} case(s) evaluated, {errored} error(s)"
    weighted = _weighted_score(run, results)
    weighted_txt = f"{weighted:.2f}" if weighted is not None else "no aggregate score"
    suffix = " Recommendation is advisory only."

    if total < 10 or (total > 0 and errored / total > 0.5):
        return (
            "insufficient_data",
            f"Only {coverage}; weighted score {weighted_txt}. More coverage is "
            f"required (at least 10 cases, majority successful) before any conclusion." + suffix,
        )

    completion = assessment_completion or {}
    assessed = int(completion.get("assessed", 0))
    positive = int(completion.get("positive", 0))
    without_evidence = int(completion.get("positive_without_evidence", 0))

    if weighted is not None and weighted < 0.5:
        return (
            "additional_testing" if False else "not_recommended",
            f"Weighted score {weighted_txt} across {coverage} is below 0.5." + suffix,
        )

    if weighted is not None and weighted >= PASS_THRESHOLD:
        if not completion:
            return (
                "candidate",
                f"Weighted score {weighted_txt} across {coverage}. No enterprise "
                "assessment recorded yet; further evaluation is required before any "
                "deployment decision." + suffix,
            )
        evidence_complete = assessed > 0 and without_evidence == 0 and positive >= assessed * 0.8
        if evidence_complete:
            return (
                "candidate",
                f"Weighted score {weighted_txt} across {coverage}; enterprise assessment "
                f"positive ({positive}/{assessed} items) with recorded evidence." + suffix,
            )
        return (
            "additional_testing",
            f"Weighted score {weighted_txt} across {coverage}, but the enterprise "
            f"assessment is incomplete or lacks evidence (positive {positive}/{assessed}, "
            f"{without_evidence} without evidence)." + suffix,
        )

    return (
        "additional_testing",
        f"Weighted score {weighted_txt} across {coverage} is between 0.5 and "
        f"{PASS_THRESHOLD:.2f}; targeted improvement and re-testing required." + suffix,
    )


def _reproducibility_rows(run: EvaluationRun) -> list[tuple[str, str]]:
    datasets = ", ".join(f"{k}:{v[:12]}" for k, v in run.dataset_versions.items()) or "none"
    params = json.dumps(run.generation_params, sort_keys=True) if run.generation_params else "{}"
    return [
        ("Run ID", run.id),
        ("App version", run.app_version),
        ("Git commit", run.git_commit or "Not available"),
        ("Scoring version", run.scoring_version),
        ("Dataset versions", datasets),
        ("Generation params", html.escape(params)),
        ("Concurrency", str(run.concurrency)),
        ("Random seed", str(run.random_seed) if run.random_seed is not None else "Not available"),
        ("Generated at (UTC)", datetime.utcnow().isoformat(timespec="seconds")),
    ]


def _safe(value: str | None, limit: int = 400) -> str:
    """HTML-escaped, secret-redacted, truncated text for report tables."""
    if not value:
        return ""
    text = safe_error(value)
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return html.escape(text)


def _sections_payload(
    run: EvaluationRun,
    results: list[CaseResult],
    assessment: EnterpriseAssessment | None,
    reviews: list[HumanReview] | None,
) -> dict:
    """All report data assembled once, shared by the PDF and Markdown renderers."""
    from app.services.performance_evaluator import compute_summary

    summary = run.summary or compute_summary(run, results)
    outcome, rationale = recommend(run, results, _completion(assessment))
    sections: dict[str, list[tuple[str, str]]] = {}
    sections["Executive Summary"] = [
        ("Status", run.status),
        ("Model", f"{run.model_id} ({run.model_identifier})"),
        ("Endpoint", run.endpoint_label),
        ("Cases", str(summary.total_cases)),
        ("Passed / failed / errored", f"{summary.passed} / {summary.failed} / {summary.errored}"),
        (
            "Weighted score",
            f"{summary.weighted_score:.4f}"
            if summary.weighted_score is not None
            else "Not available",
        ),
        ("Timeouts", str(summary.timeout_count)),
    ]
    sections["Evaluation Scope"] = [
        ("Datasets", ", ".join(run.dataset_names) or "none"),
        ("Total cases", str(summary.total_cases)),
        ("Scoring methodology version", run.scoring_version),
        ("Application version", run.app_version),
    ]
    sections["Models Evaluated"] = [
        ("Model", f"{run.model_id} ({run.model_identifier})"),
        ("Endpoint", run.endpoint_label),
        ("Generation parameters", json.dumps(run.generation_params, sort_keys=True) or "{}"),
    ]
    dataset_rows = []
    for name in run.dataset_names:
        n = sum(1 for r in results if r.dataset == name)
        version = run.dataset_versions.get(name, "unknown")
        dataset_rows.append((name, f"{n} cases; version {version[:12]}"))
    sections["Dataset Description"] = dataset_rows or [("Not available", "no datasets recorded")]
    methods = sorted(
        {
            m.group(1)
            for r in results
            if r.scoring_notes
            for m in [re.search(r"method=([a-z_]+)", r.scoring_notes)]
            if m
        }
    )
    sections["Evaluation Methodology"] = [
        ("Scoring", "Deterministic methods with field-level partial credit; "
         "incomplete answers never receive full credit."),
        ("Methods used", ", ".join(methods) if methods else "Not available"),
        ("Human judgement", "Subjective criteria require human review; any "
         "AI-assisted judgements are labelled as such, never ground truth."),
    ]
    sections["Recommendation"] = [
        (RECOMMENDATIONS.get(outcome, outcome), rationale),
    ]
    per_dataset = [
        (
            name,
            f"n={int(bucket.get('n', 0))}, pass_rate={bucket.get('pass_rate'):.2f}, "
            f"mean_score={bucket.get('mean_score'):.4f}",
        )
        for name, bucket in sorted((summary.by_dataset or {}).items())
    ]
    sections["Per-Dataset Performance"] = per_dataset or [("Not available", "no data")]
    lat = [
        ("Median (ms)", _num(summary.latency_ms_median)),
        ("p95 (ms)", _num(summary.latency_ms_p95)),
        ("Min (ms)", _num(summary.latency_ms_min)),
        ("Max (ms)", _num(summary.latency_ms_max)),
    ]
    sections["Latency"] = lat
    token_line = (
        f"prompt={summary.prompt_tokens}, completion={summary.completion_tokens} "
        f"(source: {summary.token_source})"
        if summary.prompt_tokens is not None or summary.completion_tokens is not None
        else "Not available"
    )
    cost_line = "Not available (no pricing record on the run; see cost estimator)"
    sections["Token Usage and Estimated Cost"] = [
        ("Token usage (measured from responses where present)", token_line),
        ("Cost", "not estimated here; every cost figure elsewhere is labelled estimated"),
        ("Estimated cost basis", cost_line),
    ]
    if assessment is not None:
        completion = assessment.completion()
        sections["Enterprise Assessment"] = [
            ("Items assessed", f"{completion['assessed']}/{completion['total']}"),
            ("Positive", str(completion["positive"])),
            ("Positive without evidence", str(completion["positive_without_evidence"])),
        ]
        for item in assessment.items:
            sections["Enterprise Assessment"].append(
                (
                    f"{item.category} / {item.item}",
                    f"{item.status}; rationale: {item.rationale or '-'}",
                )
            )
    else:
        sections["Enterprise Assessment"] = [("Not available", "no assessment recorded")]
    review_rows = []
    for review in reviews or []:
        review_rows.append(
            (
                f"{review.reviewer} {review.review_date}",
                _safe(review.assessment_notes) or "-",
            )
        )
    sections["Human Review Records"] = review_rows or [("Not available", "no reviews recorded")]

    security_rows = _security_rows(results)
    if security_rows:
        from app.services.security_evaluator import SECURITY_WARNING

        sections["Security Evaluation"] = security_rows + [("Warning", SECURITY_WARNING)]
    grounding_rows = _grounding_rows(results)
    if grounding_rows:
        sections["Grounding and Abstention"] = grounding_rows

    evidence = [
        (
            result.case_id,
            result.dataset,
            result.status,
            f"{result.score:.3}",
            _safe(result.error) or _safe(result.raw_response, 200) or "-",
        )
        for result in results
    ]
    sections["Supporting Evidence"] = evidence or [("Not available", "no case results")]

    next_steps = {
        "insufficient_data": [
            "Re-run the benchmark once the endpoint is stable; too few cases "
            "completed to support any decision.",
        ],
        "candidate": [
            "Extend evaluation with use-case-specific datasets before any pilot.",
            "Complete the enterprise readiness assessment with documented evidence.",
            "Record a human review with outstanding risks and required mitigations.",
        ],
        "additional_testing": [
            "Address the failing categories identified above, then re-benchmark.",
            "Complete the enterprise readiness assessment before pilot planning.",
        ],
        "not_recommended": [
            "Review failing categories with the model owner; re-evaluate after fixes.",
            "Consider alternative models and re-benchmark against the same datasets.",
        ],
    }
    sections["Recommended Next Steps"] = [
        (f"{i + 1}.", step) for i, step in enumerate(next_steps.get(outcome, ["None."]))
    ] + [("Advisory", "These steps support a human decision; they are not an approval.")]
    sections["Risks and Limitations"] = [
        ("Sample size", "Results come from small synthetic datasets (tens of cases); "
         "they do not establish clinical safety, regulatory compliance, or production "
         "readiness."),
        ("Single run", "Unless repeated, scores reflect one run and natural variance "
         "is not characterised."),
        ("Estimates", "All cost figures and any estimated token usage are clearly "
         "labelled and must not be read as measurements."),
        ("Security scope", "Security results cover selected behaviours under controlled "
         "conditions only - not a penetration test or comprehensive assessment."),
        ("Assessments", "Enterprise readiness entries are human assessments and are "
         "reported separately from measured benchmark results."),
    ]
    return {"outcome": outcome, "rationale": rationale, "sections": sections, "summary": summary}


def _completion(assessment: EnterpriseAssessment | None) -> dict | None:
    return assessment.completion() if assessment is not None else None


def _num(value: float | None) -> str:
    return f"{value:.1f}" if value is not None else "Not available"


def _security_rows(results: list[CaseResult]) -> list[tuple[str, str]]:
    from collections import Counter

    outcomes = Counter(r.security_outcome for r in results if r.security_outcome)
    if not outcomes:
        return []
    rows = []
    for kind in ("attack_resisted", "attack_succeeded", "ambiguous"):
        if outcomes.get(kind):
            label = kind.replace("_", " ")
            rows.append((label.capitalize(), str(outcomes[kind])))
    return rows


def _grounding_rows(results: list[CaseResult]) -> list[tuple[str, str]]:
    from collections import Counter

    from app.services.grounding_evaluator import parse_grounding_note

    classifications = Counter()
    for result in results:
        info = parse_grounding_note(result.scoring_notes)
        if info:
            classifications[f"grounding:{info['classification']}"] += 1
            if info.get("valid") is not None:
                classifications["citations valid" if info["valid"] else "citations invalid"] += 1
    return [(key, str(value)) for key, value in sorted(classifications.items())]


SECTION_HEADERS_PDF = SECTION_HEADERS  # kept explicit for the doc builder


def generate_markdown(
    run: EvaluationRun,
    results: list[CaseResult],
    assessment: EnterpriseAssessment | None = None,
    reviews: list[HumanReview] | None = None,
) -> str:
    """Markdown mirror of the PDF report (for the API ``?format=markdown``)."""
    payload = _sections_payload(run, results, assessment, reviews)
    lines: list[str] = [
        "# Evaluation Report — AI Pilot Evaluation Lab",
        "",
        "Independent technology demonstration. All recommendations are advisory.",
        "",
    ]
    for header in SECTION_HEADERS:
        rows = payload["sections"].get(header)
        if header == "Reproducibility":
            rows = _reproducibility_rows(run)  # rendered from the run, not the payload
        if not rows:
            continue
        lines.append(f"## {header}")
        lines.append("")
        if header == "Recommendation":
            label, rationale = rows[0]
            lines.append(f"**{label}** — {rationale}")
        elif header == "Supporting Evidence":
            lines.append("| Case | Dataset | Status | Score | Detail |")
            lines.append("|---|---|---|---|---|")
            for row in rows:
                cells = " | ".join(str(cell) for cell in row)
                lines.append(f"| {cells} |")
        elif header in ("Reproducibility",):
            lines.append("| Field | Value |")
            lines.append("|---|---|")
            for key, value in _reproducibility_rows(run):
                lines.append(f"| {key} | {value} |")
        else:
            for key, value in rows:
                lines.append(f"- **{key}**: {value}")
        lines.append("")
    return "\n".join(lines)


def generate_report(
    run: EvaluationRun,
    results: list[CaseResult],
    assessment: EnterpriseAssessment | None,
    reviews: list[HumanReview] | None,
    out_path: Path,
) -> Path:
    """Render the A4 PDF report. Returns the written path."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _sections_payload(run, results, assessment, reviews)

    styles = getSampleStyleSheet()
    heading = styles["Heading2"]
    body = styles["BodyText"]

    def table(rows: list[tuple[str, ...], ...] | list[tuple], widths=None):  # noqa: UP037
        data = [[Paragraph(str(c), body) for c in row] for row in rows]
        table = Table(data, colWidths=widths, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        return table

    story: list = []
    title = f"Evaluation Report — {run.model_id} ({run.id})"
    story.append(Paragraph(html.escape(title), styles["Title"]))
    story.append(
        Paragraph(
            "Independent technology demonstration. All recommendations are advisory.",
            body,
        )
    )
    story.append(Spacer(1, 6 * mm))

    for header in SECTION_HEADERS:
        rows = payload["sections"].get(header)
        if header == "Reproducibility":
            rows = _reproducibility_rows(run)  # rendered from the run, not the payload
        if not rows:
            continue
        story.append(Paragraph(html.escape(header), heading))
        if header == "Reproducibility":
            story.append(table([(k, v) for k, v in _reproducibility_rows(run)]))
        elif header == "Supporting Evidence":
            story.append(
                table(
                    [("Case", "Dataset", "Status", "Score", "Detail")] + rows, [55, 70, 40, 30, 220]
                )
            )
        elif header == "Recommendation":
            label, rationale = rows[0]
            story.append(Paragraph(f"<b>{html.escape(str(label))}</b> — {rationale}", body))
        else:
            story.append(table([("Item", "Value")] + [(k, v) for k, v in rows], [150, 265]))
        story.append(Spacer(1, 4 * mm))

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        title=title,
        author="AI Pilot Evaluation Lab",
    )
    doc.build(story)
    logger.info("report written to %s", out_path)
    return out_path
