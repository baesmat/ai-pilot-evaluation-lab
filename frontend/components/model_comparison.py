"""Model comparison page: run multi-select, eligibility warnings, metric table, bars."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from components.api import api_get

AMBER = "#B8860B"


def render_comparison() -> None:
    st.header("Model Comparison")

    runs = [r for r in (api_get("/api/evaluations", params={"limit": 100}) or [])
            if r.get("status") == "completed"]
    if len(runs) < 2:
        st.info("Complete at least two evaluation runs to compare models.")
        if runs:
            st.caption(f"Completed runs available: {', '.join(r['id'] for r in runs)}")
        return

    chosen = st.multiselect(
        "Runs to compare (2–6 recommended)",
        [r["id"] for r in runs],
        default=[r["id"] for r in runs[: min(3, len(runs))]],
        format_func=lambda rid: next(
            (f"{r['id']} — {r.get('model_identifier')}" for r in runs if r["id"] == rid), rid
        ),
    )
    if len(chosen) < 2:
        st.warning("Select at least two runs.")
        return

    ids = ",".join(chosen)
    try:
        comparison = api_get("/api/comparison", params={"run_ids": ids}) or {}
    except Exception as exc:  # noqa: BLE001 - show a friendly error, not a traceback
        st.error(f"Comparison failed: {exc}")
        return

    eligibility = comparison.get("eligibility") or []
    if eligibility:
        st.markdown(
            f'<div style="border:1px solid {AMBER};border-radius:8px;padding:10px;'
            f'color:{AMBER}"><b>Comparability warnings</b><br>'
            + "<br>".join(f"• {w}" for w in eligibility)
            + "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.success("Runs are directly comparable: no eligibility warnings.")

    rows = comparison.get("rows") or []
    if not rows:
        st.caption("No comparable metrics returned.")
        return

    # Metric-by-metric table with measured/estimated labelling.
    table_rows = []
    for row in rows:
        entry = {"metric": row.get("metric"), "kind": row.get("kind")}
        values = row.get("values") or {}
        for rid in chosen:
            label = next((r.get("model_identifier", rid) for r in runs if r["id"] == rid), rid)
            entry[label] = values.get(rid, "unavailable")
        if row.get("note"):
            entry["note"] = row["note"]
        table_rows.append(entry)
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)
    st.caption("Values are labelled measured or estimated by the backend; unavailable means no data.")

    # Numeric bars for extractable metrics.
    numeric = []
    for row in rows:
        for rid, value in (row.get("values") or {}).items():
            if isinstance(value, (int, float)):
                numeric.append(
                    {"metric": row["metric"], "run": rid, "value": float(value),
                     "kind": row.get("kind")}
                )
    if numeric:
        df = pd.DataFrame(numeric)
        for metric in df["metric"].unique():
            sub = df[df["metric"] == metric]
            fig = px.bar(
                sub, x="run", y="value", color="kind", title=metric,
                color_discrete_sequence=["#177E89", "#1B2A4A", "#B8860B"],
            )
            fig.update_layout(yaxis_range=[0, max(1.0, float(sub["value"].max()))]
                              if "rate" in metric or "score" in metric else {})
            st.plotly_chart(fig, use_container_width=True)

    rec_inputs = comparison.get("recommendation_inputs") or {}
    if rec_inputs:
        with st.expander("Recommendation inputs (per run)"):
            st.json(rec_inputs, expanded=False)
