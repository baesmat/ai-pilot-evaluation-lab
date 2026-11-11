"""Dashboard page: high-level counters, recent runs, comparison teaser."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components.api import api_get


def render_dashboard() -> None:
    st.header("Dashboard")

    models = api_get("/api/models") or []
    runs = api_get("/api/evaluations", params={"limit": 100}) or []
    datasets = api_get("/api/datasets") or []

    completed = [r for r in runs if r.get("status") == "completed"]
    total_cases = sum(int(d.get("case_count", 0)) for d in datasets)
    avg_progress = (
        sum(int(r.get("progress_completed", 0)) for r in completed) / len(completed) if completed else 0.0
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Models registered", len(models))
    c2.metric("Completed runs", len(completed))
    c3.metric("Benchmark cases available", total_cases)
    completed_count = len(completed) if completed else 1
    c4.metric(
        "Avg cases completed / run",
        f"{avg_progress:.0f}",
        help="Average of progress_completed across completed runs.",
    )
    _ = completed_count

    st.subheader("Recent evaluation runs")
    if runs:
        rows = [
            {
                "Run": r.get("id"),
                "Model": r.get("model_identifier"),
                "Datasets": ", ".join(r.get("dataset_names", [])),
                "Status": r.get("status"),
                "Progress": f"{r.get('progress_completed', 0)}/{r.get('progress_total', 0)}",
                "Weighted score": (r.get("summary") or {}).get("weighted_score"),
            }
            for r in runs[:15]
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        selected = st.selectbox(
            "Inspect a run in Benchmark Results",
            [r["id"] for r in runs],
            format_func=lambda rid: next(
                (f"{r['id']} — {r['model_identifier']} ({r['status']})" for r in runs if r["id"] == rid),
                rid,
            ),
        )
        if st.button("Open in Benchmark Results"):
            st.session_state["selected_run_id"] = selected
            st.session_state["nav_page"] = "Benchmark Results"
    else:
        st.info("No evaluation runs yet — start one in the Evaluation Runner.")

    st.subheader("Latest comparison")
    completed_ids = [r["id"] for r in completed]
    if len(completed_ids) >= 2:
        teaser_ids = ",".join(completed_ids[:3])
        try:
            comparison = api_get("/api/comparison", params={"run_ids": teaser_ids}) or {}
        except Exception:  # noqa: BLE001 - teaser only, never block the page
            comparison = {}
        rows = comparison.get("rows") or []
        if rows:
            data = {"metric": []}
            for row in rows[:8]:
                data["metric"].append(row.get("metric"))
                for run_id, value in (row.get("values") or {}).items():
                    data.setdefault(run_id, []).append(value)
            st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)
        else:
            st.caption("Comparison data will appear once runs complete.")
        if len(completed_ids) < 3:
            st.caption(f"Showing {len(completed_ids)} completed runs; select more in Model Comparison.")
    else:
        st.caption("Complete at least two evaluation runs to compare models.")
