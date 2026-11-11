"""Evaluation Runner page: start runs, poll progress, cancel, show errors."""

from __future__ import annotations

import json
import time

import streamlit as st

from components.api import api_get, api_post
from components.api import BackendError


def _poll_run(run_id: str) -> dict:
    return api_get(f"/api/evaluations/{run_id}", params={"include_results": "true"})


def _render_progress(run_id: str, run: dict) -> None:
    status = run.get("status")
    done = int(run.get("progress_completed", 0))
    total = int(run.get("progress_total", 0)) or 1
    pct = done / total

    label = {
        "pending": "⏳ Pending",
        "running": "⚙️ Running",
        "completed": "✅ Completed",
        "cancelled": "🟠 Cancelled",
        "failed": "🔴 Failed",
    }.get(status, status)

    st.status(label)
    st.progress(min(pct, 1.0), text=f"{done}/{total} cases complete")
    st.caption(
        f"Run `{run.get('id')}` — model {run.get('model_identifier')} — "
        f"concurrency {run.get('concurrency')} — datasets {', '.join(run.get('dataset_names', []))}"
    )

    if status == "running":
        if st.button("Cancel run", key="cancel_run"):
            try:
                api_post(f"/api/evaluations/{run_id}/cancel")
                st.toast("Cancellation requested", icon="🟠")
                time.sleep(0.5)
            except BackendError as exc:
                st.error(f"Cancel failed: {exc}")
            st.rerun()
    if status in {"completed", "cancelled", "failed"}:
        if st.button("Open results in Benchmark Results", key="open_results"):
            st.session_state["selected_run_id"] = run_id

    summary = run.get("summary")
    if summary and status == "completed":
        st.subheader("Summary")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Weighted score", f"{summary.get('weighted_score'):.3f}"
                  if summary.get("weighted_score") is not None else "n/a")
        c2.metric("Passed / failed / errored",
                  f"{summary.get('passed', 0)} / {summary.get('failed', 0)} / {summary.get('errored', 0)}")
        c3.metric("Median latency",
                  f"{summary.get('latency_ms_median'):.0f} ms"
                  if summary.get("latency_ms_median") is not None else "n/a")
        c4.metric("Token source", summary.get("token_source", "unavailable"))

    errors = [
        r for r in (run.get("results") or [])
        if r.get("status") == "error" or r.get("error")
    ]
    if errors:
        with st.expander(f"Errors so far ({len(errors)})", expanded=False):
            for e in errors[:20]:
                st.markdown(
                    f"- `{e.get('case_id')}` ({e.get('dataset')}): {e.get('error') or 'unknown error'}"
                )


def render_runner() -> None:
    st.header("Evaluation Runner")

    models = [m for m in (api_get("/api/models") or []) if m.get("enabled")]
    datasets = api_get("/api/datasets") or []

    if not models:
        st.warning("No enabled models — register and enable one in Model Registry first.")
        return
    if not datasets:
        st.warning("No datasets available on the backend.")
        return

    col_a, col_b = st.columns(2)
    model = col_a.selectbox(
        "Model",
        models,
        format_func=lambda m: f"{m.get('display_name')} ({m['id']})",
    )
    dataset = {d["name"]: d for d in datasets}
    chosen = col_b.multiselect(
        "Datasets (with case counts)",
        list(dataset.keys()),
        default=list(dataset.keys())[:1],
        format_func=lambda n: f"{n} ({dataset[n].get('case_count', '?')} cases)",
    )

    active_run_id = st.session_state.get("active_run_id")
    if active_run_id:
        try:
            run = _poll_run(active_run_id)
        except BackendError as exc:
            st.warning(f"Cannot poll run: {exc}")
            run = None
        if run and run.get("status") in {"pending", "running"}:
            _render_progress(active_run_id, run)
            time.sleep(2)
            st.rerun()
        elif run:
            _render_progress(active_run_id, run)

    with st.expander("Advanced options"):
        concurrency = st.slider("Concurrency", 1, 4, 1)
        c1, c2 = st.columns(2)
        temperature = c1.number_input("Temperature", min_value=0.0, max_value=2.0, value=0.0, step=0.1)
        max_tokens = c2.number_input("Max tokens", min_value=1, max_value=100000, value=1024)
        seed = st.number_input("Random seed (optional, blank = none)", min_value=0, value=0,
                               key="seed_input")
        use_seed = st.checkbox("Set seed explicitly", value=False)

    if st.button("▶ Start evaluation", type="primary", disabled=not chosen):
        generation_params = {"temperature": float(temperature), "max_tokens": int(max_tokens)}
        payload = {
            "model_id": model["id"],
            "dataset_names": chosen,
            "concurrency": int(concurrency),
            "generation_params": generation_params,
        }
        if use_seed:
            payload["seed"] = int(seed)
        try:
            resp = api_post("/api/evaluations", json=payload) or {}
            run_id = resp.get("run_id") or resp.get("id")
        except BackendError as exc:
            st.error(f"Could not start run: {exc}")
            return
        if not run_id:
            st.error("Backend did not return a run id.")
            return
        st.session_state["active_run_id"] = run_id
        st.toast(f"Run {run_id} started", icon="▶")
        time.sleep(0.5)
        st.rerun()

    st.divider()
    with st.expander("Previous runs for this model"):
        history = api_get("/api/evaluations", params={"model_id": model["id"], "limit": 10}) or []
        for r in history:
            st.markdown(
                f"- `{r['id']}` — {r.get('status')} — "
                f"{r.get('progress_completed', 0)}/{r.get('progress_total', 0)} — "
                f"params `{json.dumps(r.get('generation_params') or {})}`"
            )
        if not history:
            st.caption("No prior runs.")
