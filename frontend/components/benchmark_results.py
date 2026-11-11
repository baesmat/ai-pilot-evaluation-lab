"""Benchmark results page: summary metrics, per-dataset accuracy, per-case drill-down."""

from __future__ import annotations

import json

import pandas as pd
import plotly.express as px
import streamlit as st

from components.api import api_get, BackendError


def _to_csv(rows: list[dict]) -> str:
    if not rows:
        return ""
    return pd.DataFrame(rows).to_csv(index=False)


def _case_row(case: dict) -> dict:
    usage = case.get("token_usage") or {}
    return {
        "run_id": case.get("run_id"),
        "case_id": case.get("case_id"),
        "dataset": case.get("dataset"),
        "status": case.get("status"),
        "score": case.get("score"),
        "weight": case.get("weight"),
        "latency_ms": case.get("latency_ms"),
        "ttft_ms": case.get("time_to_first_token_ms"),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "attempt": case.get("request_attempt"),
        "security_outcome": case.get("security_outcome"),
        "error": case.get("error"),
    }


def render_results(run_id: str | None = None) -> None:
    st.header("Benchmark Results")

    runs = api_get("/api/evaluations", params={"limit": 100}) or []
    if not runs:
        st.info("No evaluation runs recorded yet.")
        return

    completed = [r for r in runs if r.get("status") in {"completed", "cancelled", "failed"}]
    options = [r["id"] for r in runs]
    default = run_id if run_id in options else (completed[0]["id"] if completed else options[0])
    selected = st.selectbox(
        "Evaluation run",
        options,
        index=options.index(default) if default in options else 0,
        format_func=lambda rid: next(
            (f"{r['id']} — {r.get('model_identifier')} ({r.get('status')})" for r in runs if r["id"] == rid),
            rid,
        ),
    )

    try:
        run = api_get(f"/api/evaluations/{selected}", params={"include_results": "true"})
        results = api_get(f"/api/evaluations/{selected}/results") or []
    except BackendError as exc:
        st.warning(f"Could not load run: {exc}")
        return

    run = run or {}
    summary = run.get("summary") or {}
    st.caption(
        f"Model `{run.get('model_identifier')}` — datasets {', '.join(run.get('dataset_names', []))} — "
        f"scoring v{run.get('scoring_version', '?')} — app v{run.get('app_version', '?')} — "
        f"status **{run.get('status')}**"
    )

    if run.get("status") != "completed":
        st.warning(f"This run is not completed (status: {run.get('status')}); figures are partial.")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Cases", summary.get("total_cases", run.get("progress_total", 0)))
    c2.metric("Weighted score",
              f"{summary['weighted_score']:.3f}" if summary.get("weighted_score") is not None else "n/a")
    c3.metric("Passed / failed / errored",
              f"{summary.get('passed', 0)} / {summary.get('failed', 0)} / {summary.get('errored', 0)}")
    c4.metric("Latency p50 / p95",
              (f"{summary.get('latency_ms_median', 0):.0f} / {summary.get('latency_ms_p95', 0):.0f} ms"
               if summary.get("latency_ms_median") is not None else "n/a"))
    c5.metric("Tokens (src: {})".format(summary.get("token_source", "n/a")),
              f"{(summary.get('prompt_tokens') or 0) + (summary.get('completion_tokens') or 0):,}"
              if summary.get("prompt_tokens") is not None else "n/a")

    # Per-dataset accuracy
    by_dataset = summary.get("by_dataset") or {}
    if by_dataset:
        st.subheader("Per-dataset accuracy")
        rows = [
            {"dataset": ds, "pass_rate": v.get("pass_rate"), "mean_score": v.get("mean_score"),
             "n": v.get("n")}
            for ds, v in by_dataset.items()
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        fig = px.bar(
            pd.DataFrame(rows), x="dataset", y="mean_score", color_discrete_sequence=["#177E89"],
            range_y=[0, 1], title="Mean score by dataset",
        )
        st.plotly_chart(fig, use_container_width=True)

    # Latency distribution
    latencies = [
        {"latency_ms": r["latency_ms"], "dataset": r.get("dataset")}
        for r in results
        if isinstance(r.get("latency_ms"), (int, float))
    ]
    if latencies:
        st.subheader("Latency distribution")
        fig = px.box(pd.DataFrame(latencies), x="dataset", y="latency_ms", points="all",
                     color_discrete_sequence=["#1B2A4A"])
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("No latency data recorded for successful cases.")

    # Downloads
    dl1, dl2, _ = st.columns([1, 1, 3])
    dl1.download_button(
        "Download results JSON",
        data=json.dumps({"run": run, "results": results}, default=str, indent=2),
        file_name=f"run_{selected}_results.json",
        mime="application/json",
    )
    dl2.download_button(
        "Download results CSV",
        data=_to_csv([_case_row(r) for r in results]),
        file_name=f"run_{selected}_results.csv",
        mime="text/csv",
    )

    # Per-case expandable detail
    st.subheader("Per-case results")
    if not results:
        st.caption("No case results recorded.")
        return
    for case in results:
        title = f"`{case.get('case_id')}` — {case.get('status')} — score {case.get('score')}"
        with st.expander(title):
            col_l, col_r = st.columns(2)
            col_l.markdown(f"Dataset: **{case.get('dataset')}**  |  Weight: {case.get('weight')}")
            col_r.markdown(
                f"Latency: {case.get('latency_ms')} ms | TTFT: {case.get('time_to_first_token_ms')} ms | "
                f"Attempt {case.get('request_attempt')}"
            )
            if case.get("security_outcome"):
                st.markdown(f"Security outcome: **{case['security_outcome']}**")
            if case.get("error"):
                st.error(case["error"])
            if case.get("scoring_notes"):
                st.caption(f"Scoring notes: {case['scoring_notes']}")

            raw = case.get("raw_response")
            if raw:
                st.markdown("**Model response**")
                st.code(str(raw)[:4000], language=None)

            parsed = case.get("parsed_output")
            if parsed is not None:
                st.markdown("**Parsed output**")
                st.json(parsed if isinstance(parsed, (dict, list)) else {"value": parsed})

            field_results = case.get("field_results") or []
            if field_results:
                st.markdown("**Field results**")
                st.dataframe(
                    pd.DataFrame(field_results), use_container_width=True, hide_index=True
                )

            with st.expander("Raw result record (JSON)"):
                st.json(case, expanded=False)
