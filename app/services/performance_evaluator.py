"""Aggregate run statistics. Nothing here invents data: absent values stay None."""

from __future__ import annotations

import math
import re

from app.models.result import CaseResult, RunSummary

_STRUCTURED_RE = re.compile(r"structured_ok=([01])")


def latency_percentiles(values: list[float]) -> dict:
    """Nearest-rank p50/p95 plus min/max. Empty input -> all None."""
    if not values:
        return {"p50": None, "p95": None, "min": None, "max": None}
    ordered = sorted(values)

    def percentile(fraction: float) -> float:
        index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
        return ordered[index]

    return {
        "p50": percentile(0.50),
        "p95": percentile(0.95),
        "min": ordered[0],
        "max": ordered[-1],
    }


def structured_flag(note: str | None) -> bool | None:
    """Parse the ``structured_ok=0/1`` scoring-note marker. None when absent."""
    if not note:
        return None
    match = _STRUCTURED_RE.search(note)
    return bool(int(match.group(1))) if match else None


def token_source_of(results: list[CaseResult]) -> tuple[str, int | None, int | None]:
    """(source, prompt_total, completion_total). Totals None when unrecorded."""
    prompt_total = 0
    completion_total = 0
    seen_prompt = False
    seen_completion = False
    sources: set[str] = set()
    for result in results:
        usage = result.token_usage
        if usage.source:
            sources.add(usage.source)
        if usage.prompt_tokens is not None:
            prompt_total += usage.prompt_tokens
            seen_prompt = True
        if usage.completion_tokens is not None:
            completion_total += usage.completion_tokens
            seen_completion = True
    if not sources or not (seen_prompt or seen_completion):
        return "unavailable", None, None
    if "measured" in sources:
        source = "measured"
    elif "estimated" in sources:
        source = "estimated"
    else:
        source = "unavailable"
    return (
        source,
        (prompt_total if seen_prompt else None),
        (completion_total if seen_completion else None),
    )


def compute_summary(run, results: list[CaseResult]) -> RunSummary:
    """Summary over recorded results. The ``run`` argument is used for context only."""
    total = len(results)
    passed = sum(1 for r in results if r.status == "passed")
    failed = sum(1 for r in results if r.status == "failed")
    errored = sum(1 for r in results if r.status == "error")

    scored = [r for r in results if r.status != "error"]
    weight_sum = sum(r.weight for r in scored)
    weighted = sum(r.score * r.weight for r in scored) / weight_sum if weight_sum > 0 else None

    by_dataset: dict[str, dict[str, float]] = {}
    for result in scored:
        bucket = by_dataset.setdefault(
            result.dataset, {"pass_rate": 0.0, "mean_score": 0.0, "n": 0}
        )
        bucket["n"] = float(bucket["n"]) + 1
    for name, bucket in by_dataset.items():
        group = [r for r in scored if r.dataset == name]
        bucket["n"] = float(len(group))
        bucket["pass_rate"] = sum(1 for r in group if r.status == "passed") / len(group)
        bucket["mean_score"] = sum(r.score for r in group) / len(group)

    latencies = [r.latency_ms for r in results if r.status != "error" and r.latency_ms is not None]
    latencies = [float(value) for value in latencies]
    percentiles = latency_percentiles(latencies)

    timeout_count = sum(
        1
        for r in results
        if r.status == "error"
        and r.error is not None
        and ("timed out" in r.error.lower() or "timeout" in r.error.lower())
    )

    flags = [structured_flag(r.scoring_notes) for r in results]
    recorded = [flag for flag in flags if flag is not None]
    structured_rate = (sum(1 for f in recorded if f) / len(recorded)) if recorded else None

    source, prompt_total, completion_total = token_source_of(results)

    return RunSummary(
        total_cases=total,
        passed=passed,
        failed=failed,
        errored=errored,
        weighted_score=weighted,
        by_dataset=by_dataset,
        latency_ms_median=percentiles["p50"],
        latency_ms_p95=percentiles["p95"],
        latency_ms_min=percentiles["min"],
        latency_ms_max=percentiles["max"],
        timeout_count=timeout_count,
        structured_output_success_rate=structured_rate,
        prompt_tokens=prompt_total,
        completion_tokens=completion_total,
        token_source=source,  # type: ignore[arg-type]
    )
