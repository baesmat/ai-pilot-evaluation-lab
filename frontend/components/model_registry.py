"""Model registry page: add/edit models, health checks, enable/disable, delete."""

from __future__ import annotations

import json

import streamlit as st

from components.api import api_delete, api_get, api_post, api_put

HOSTING_OPTIONS = ["local", "hosted_api", "on_premise", "hybrid"]


def _model_form(defaults: dict | None = None, key_prefix: str = "new") -> dict | None:
    d = defaults or {}
    with st.form(f"model_form_{key_prefix}", border=True):
        cols = st.columns(2)
        model_id = cols[0].text_input(
            "Model ID (unique, [a-zA-Z0-9._-])", value=d.get("id", ""), key=f"{key_prefix}_id"
        )
        display_name = cols[1].text_input(
            "Display name", value=d.get("display_name", ""), key=f"{key_prefix}_name"
        )
        provider = cols[0].text_input("Provider", value=d.get("provider", "OpenAI Compatible"),
                                      key=f"{key_prefix}_provider")
        model_identifier = cols[1].text_input(
            "Model identifier (API model name)", value=d.get("model_identifier", ""),
            key=f"{key_prefix}_ident",
        )
        endpoint = cols[0].text_input(
            "Endpoint URL (http(s)://...)", value=d.get("endpoint", ""), key=f"{key_prefix}_url"
        )
        api_key = cols[1].text_input(
            "API key (optional)", value=d.get("api_key") or "", type="password", key=f"{key_prefix}_key"
        )
        hosting = cols[0].selectbox(
            "Hosting", HOSTING_OPTIONS,
            index=(HOSTING_OPTIONS.index(d["hosting_type"]) if d.get("hosting_type") in HOSTING_OPTIONS else 0),
            key=f"{key_prefix}_hosting",
        )
        context_window = cols[1].number_input(
            "Context window (tokens, optional)", min_value=0, value=int(d.get("context_window") or 0),
            key=f"{key_prefix}_ctx",
        )
        in_cost = cols[0].number_input(
            "Input cost / M tokens", min_value=0.0, step=0.01, value=float(d.get("input_cost_per_million_tokens") or 0),
            key=f"{key_prefix}_inc",
        )
        out_cost = cols[1].number_input(
            "Output cost / M tokens", min_value=0.0, step=0.01, value=float(d.get("output_cost_per_million_tokens") or 0),
            key=f"{key_prefix}_outc",
        )
        currency = cols[0].text_input("Currency", value=d.get("currency", "USD"), key=f"{key_prefix}_cur")
        timeout = cols[1].number_input(
            "Timeout (seconds)", min_value=1, max_value=600, value=int(d.get("timeout_seconds", 120)),
            key=f"{key_prefix}_to",
        )
        max_conc = cols[0].slider(
            "Max concurrent requests", 1, 8, value=int(d.get("max_concurrent_requests", 1)),
            key=f"{key_prefix}_conc",
        )
        gen_params_raw = cols[1].text_area(
            "Generation params (JSON, optional)",
            value=json.dumps(d.get("generation_params") or {}, indent=2),
            key=f"{key_prefix}_gen", height=100,
        )
        extra_headers_raw = st.text_area(
            "Extra headers (JSON, optional)",
            value=json.dumps(d.get("extra_headers") or {}, indent=2),
            key=f"{key_prefix}_hdr", height=80,
        )
        submitted = st.form_submit_button("Save model", type="primary")

    if not submitted:
        return None

    try:
        generation_params = json.loads(gen_params_raw) if gen_params_raw.strip() else {}
        extra_headers = json.loads(extra_headers_raw) if extra_headers_raw.strip() else {}
    except json.JSONDecodeError as exc:
        st.error(f"JSON parse error in params/headers: {exc}")
        return None

    return {
        "id": model_id.strip(),
        "display_name": display_name.strip() or model_id.strip(),
        "provider": provider.strip(),
        "model_identifier": model_identifier.strip(),
        "endpoint": endpoint.strip(),
        "api_key": api_key or None,
        "hosting_type": hosting,
        "context_window": int(context_window) if context_window else None,
        "input_cost_per_million_tokens": float(in_cost) if in_cost else None,
        "output_cost_per_million_tokens": float(out_cost) if out_cost else None,
        "currency": currency.strip() or "USD",
        "enabled": bool(d.get("enabled", True)) if defaults else True,
        "timeout_seconds": int(timeout),
        "max_concurrent_requests": int(max_conc),
        "generation_params": generation_params,
        "extra_headers": {str(k): str(v) for k, v in extra_headers.items()},
    }


def _health_badge(result: dict | None) -> None:
    if not result:
        return
    ok = result.get("ok")
    color = "🟢" if ok else "🔴"
    latency = result.get("latency_ms")
    lines = [
        f"{color} API compatible: {ok}",
        f"Model reported: {result.get('model_reported') or 'n/a'}",
        f"Latency: {latency:.0f} ms" if isinstance(latency, (int, float)) else "Latency: n/a",
        f"Token usage reported: {result.get('reports_token_usage')}",
        f"Streaming: {result.get('supports_streaming')}",
    ]
    if result.get("error"):
        lines.append(f"Error: {result['error']}")
    st.markdown("\n".join(f"- {ln}" for ln in lines))


def render_model_registry() -> None:
    st.header("Model Registry")

    models = api_get("/api/models") or []
    if not models:
        st.info("No models registered yet. Add one below.")

    for m in models:
        mid = m["id"]
        with st.expander(f"**{m.get('display_name', mid)}** — `{mid}` ({m.get('hosting_type')})"):
            meta_l, meta_r = st.columns(2)
            meta_l.markdown(f"Endpoint: `{m.get('endpoint')}`")
            meta_r.markdown(f"Model: `{m.get('model_identifier')}`")
            meta_l.markdown(f"Enabled: {'yes' if m.get('enabled') else 'no'}`")
            meta_r.markdown(f"Max concurrency: {m.get('max_concurrent_requests')}")

            act1, act2, act3, act4 = st.columns(4)
            if act1.button("Health check", key=f"hc_{mid}"):
                with st.spinner("Running health check (real API call)..."):
                    try:
                        result = api_post(f"/api/models/{mid}/health")
                        _health_badge(result)
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Health check failed: {exc}")
            new_enabled = not bool(m.get("enabled"))
            if act2.button("Enable" if not m.get("enabled") else "Disable", key=f"tgl_{mid}"):
                try:
                    api_put(f"/api/models/{mid}", json={"enabled": new_enabled})
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Update failed: {exc}")
            if act3.button("Edit", key=f"edit_{mid}"):
                st.session_state["editing_model"] = mid
            confirm = act4.checkbox("Confirm delete", key=f"del_{mid}")
            if confirm and act4.button("Delete", key=f"delgo_{mid}", type="primary"):
                try:
                    api_delete(f"/api/models/{mid}")
                    st.success(f"Deleted {mid}")
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Delete failed: {exc}")

            if st.session_state.get("editing_model") == mid:
                updated = _model_form(defaults=m, key_prefix=f"edit_{mid}")
                if updated:
                    try:
                        api_put(f"/api/models/{mid}", json=updated)
                        st.success("Saved.")
                        st.session_state.pop("editing_model", None)
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Save failed: {exc}")

    st.divider()
    st.subheader("Register a new model")
    new_model = _model_form(key_prefix="new")
    if new_model:
        try:
            api_post("/api/models", json=new_model)
            st.success(f"Registered model `{new_model['id']}`.")
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Registration failed: {exc}")
