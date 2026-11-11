"""Enterprise readiness: per-item assessments, human review records, completion summary."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components.api import api_get, api_post, api_put

STATUSES = [
    "not_evaluated",
    "meets_requirement",
    "partially_meets_requirement",
    "does_not_meet_requirement",
    "not_applicable",
]

STATUS_LABELS = {
    "not_evaluated": "Not evaluated",
    "meets_requirement": "Meets requirement",
    "partially_meets_requirement": "Partially meets",
    "does_not_meet_requirement": "Does not meet",
    "not_applicable": "N/A",
}


def _render_assessment_editor(model_id: str, assessment: dict) -> None:
    items = assessment.get("items") or []
    by_key = {(i.get("category"), i.get("item")): i for i in items}
    categories = sorted({i.get("category") for i in items}) if items else []

    st.markdown("Set a status per item; add rationale and evidence where required.")
    pending: list[dict] = []

    for category in categories:
        with st.expander(f"{category}", expanded=len(categories) <= 3):
            cat_items = [i for i in items if i.get("category") == category]
            for item in cat_items:
                existing = by_key.get((category, item["item"])) or {}
                key = f"asmt_{model_id}_{category}_{item['item']}".replace(" ", "_").replace("/", "_")
                c1, c2 = st.columns([1, 2])
                status = c1.selectbox(
                    item["item"],
                    STATUSES,
                    index=STATUSES.index(existing.get("status", "not_evaluated"))
                    if existing.get("status") in STATUSES else 0,
                    format_func=lambda s: STATUS_LABELS.get(s, s),
                    key=f"{key}_status",
                )
                rationale = c2.text_input(
                    "Rationale", value=existing.get("rationale") or "", key=f"{key}_rat"
                )
                evidence = st.text_input(
                    "Evidence (link, document, reference)",
                    value=existing.get("evidence") or "",
                    key=f"{key}_ev",
                )
                if status != existing.get("status", "not_evaluated") or rationale != (
                        existing.get("rationale") or "") or evidence != (existing.get("evidence") or ""):
                    pending.append({
                        "category": category,
                        "item": item["item"],
                        "status": status,
                        "rationale": rationale or None,
                        "evidence": evidence or None,
                    })

    if pending and st.button("Save assessment changes", type="primary", key=f"save_{model_id}"):
        try:
            merged = list(items)
            item_index = {(i.get("category"), i.get("item")): n for n, i in enumerate(merged)}
            for change in pending:
                idx = item_index.get((change["category"], change["item"]))
                if idx is None:
                    merged.append(change)
                else:
                    merged[idx] = {**merged[idx], **change}
            api_put(f"/api/assessments/{model_id}", json={"items": merged})
            st.success(f"Saved {len(pending)} item(s).")
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Save failed: {exc}")


def _render_completion(model_id: str) -> None:
    try:
        summary = api_get(f"/api/assessments/{model_id}/summary") or {}
    except Exception:  # noqa: BLE001
        return
    total = int(summary.get("total", 0))
    assessed = int(summary.get("assessed", 0))
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Items", total)
    c2.metric("Assessed", f"{assessed}" + (f" ({assessed / total:.0%})" if total else ""))
    c3.metric("Positive", summary.get("positive", 0))
    gaps = int(summary.get("positive_without_evidence", 0))
    c4.metric("Positive w/o evidence", gaps)
    if gaps:
        st.warning(
            f"{gaps} item(s) marked positively without recorded rationale or evidence — "
            "add evidence to support the assessment."
        )


def _render_review_form(model_id: str) -> None:
    st.subheader("Human review record")
    with st.form(f"review_{model_id}", border=True):
        reviewer = st.text_input("Reviewer name")
        review_date = st.date_input("Review date")
        notes = st.text_area("Assessment notes")
        risks = st.text_area("Outstanding risks (one per line)")
        mitigations = st.text_area("Required mitigations (one per line)")
        next_steps = st.text_area("Recommended next steps (one per line)")
        submitted = st.form_submit_button("Record review")

    if not submitted:
        _render_existing_reviews(model_id)
        return
    if not reviewer.strip():
        st.error("Reviewer name is required.")
        return
    payload = {
        "model_id": model_id,
        "reviewer": reviewer.strip(),
        "review_date": review_date.isoformat(),
        "assessment_notes": notes or None,
        "outstanding_risks": [x.strip() for x in risks.splitlines() if x.strip()],
        "required_mitigations": [x.strip() for x in mitigations.splitlines() if x.strip()],
        "recommended_next_steps": [x.strip() for x in next_steps.splitlines() if x.strip()],
    }
    try:
        api_post("/api/reviews", json=payload)
        st.success("Review recorded.")
        st.rerun()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not record review: {exc}")


def _render_existing_reviews(model_id: str) -> None:
    try:
        reviews = api_get(f"/api/reviews/{model_id}") or []
    except Exception:  # noqa: BLE001
        return
    if not reviews:
        st.caption("No human reviews recorded for this model.")
        return
    for review in reviews:
        with st.expander(f"Review by {review.get('reviewer')} — {review.get('review_date')}"):
            if review.get("assessment_notes"):
                st.markdown(review["assessment_notes"])
            for label, key in [
                ("Outstanding risks", "outstanding_risks"),
                ("Required mitigations", "required_mitigations"),
                ("Next steps", "recommended_next_steps"),
            ]:
                values = review.get(key) or []
                if values:
                    st.markdown(f"**{label}:** " + "".join(f"\n- {v}" for v in values))


def render_enterprise_readiness() -> None:
    st.header("Enterprise Readiness")

    models = api_get("/api/models") or []
    if not models:
        st.warning("No models registered — add one in Model Registry first.")
        return

    model_id = st.selectbox(
        "Model",
        [m["id"] for m in models],
        format_func=lambda mid: next(
            (f"{m.get('display_name')} ({m['id']})" for m in models if m["id"] == mid), mid
        ),
    )

    try:
        assessment = api_get(f"/api/assessments/{model_id}") or {"model_id": model_id, "items": []}
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not load assessment: {exc}")
        return

    _render_completion(model_id)

    items = assessment.get("items") or []
    if not items:
        st.info("No assessment checklist items exist yet for this model.")
        if st.button("Initialise assessment checklist", key="init_asmt"):
            try:
                api_put(f"/api/assessments/{model_id}",
                        json={"items": [{"category": c, "item": i, "status": "not_evaluated"}
                                        for c, names in _default_categories().items() for i in names]})
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Initialisation failed: {exc}")
        _render_review_form(model_id)
        return

    tab_a, tab_b = st.tabs(["Risk & readiness assessment", "Human review"])
    with tab_a:
        _render_assessment_editor(model_id, assessment)
        st.dataframe(
            pd.DataFrame(
                [{"category": i.get("category"), "item": i.get("item"),
                  "status": STATUS_LABELS.get(i.get("status"), i.get("status")),
                  "rationale": i.get("rationale"), "evidence": i.get("evidence")}
                 for i in items]
            ),
            use_container_width=True,
            hide_index=True,
        )
    with tab_b:
        _render_review_form(model_id)


def _default_categories() -> dict[str, list[str]]:
    """Fallback checklist; the backend contract drives the canonical list."""
    return {
        "Security": ["Access controls", "Logging", "Security review"],
        "Privacy and Governance": ["Data retention", "Data residency"],
        "Operational Support": ["Service ownership", "Monitoring", "Incident management"],
        "Integration": ["API compatibility", "Authentication"],
        "Financial Sustainability": ["Licensing", "Infrastructure costs"],
        "Model Lifecycle": ["Version management", "Regression testing"],
    }
