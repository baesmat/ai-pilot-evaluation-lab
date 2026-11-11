"""AI Pilot Evaluation Lab — Streamlit frontend entry point.

Independent technology demonstration — not affiliated with any institution.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from components import api  # noqa: E402
from components.benchmark_results import render_results  # noqa: E402
from components.dashboard import render_dashboard  # noqa: E402
from components.enterprise_readiness import render_enterprise_readiness  # noqa: E402
from components.evaluation_runner import render_runner  # noqa: E402
from components.model_comparison import render_comparison  # noqa: E402
from components.model_registry import render_model_registry  # noqa: E402

NAVY = "#1B2A4A"
TEAL = "#177E89"
AMBER = "#B8860B"
RED = "#A4303F"

PAGE_CSS = f"""
<style>
    h1, h2, h3, h4 {{ color: {NAVY}; }}
    .block-container {{ padding-top: 1.5rem; }}
    div[data-testid="stMetric"] {{
        background: #F4F6F8;
        border: 1px solid #D9DEE4;
        border-radius: 8px;
        padding: 12px 16px;
    }}
    div[data-testid="stMetricLabel"] p {{ color: {TEAL}; font-weight: 600; }}
    div[data-testid="stExpander"] {{
        border: 1px solid #D9DEE4;
        border-radius: 8px;
        background: #FAFBFC;
    }}
    .stTabs [data-baseweb="tab"] {{ color: {NAVY}; }}
    .stButton > button {{ border-color: {TEAL}; color: {NAVY}; }}
    .stDownloadButton > button {{ border-color: {TEAL}; color: {NAVY}; }}
    .sidebar-note {{ color: {TEAL}; font-size: 0.85rem; }}
    div[data-testid="stStatusWidget"] div {{ color: {NAVY}; }}
    .warning-text {{ color: {AMBER}; }}
    .error-text {{ color: {RED}; }}
    th {{ background-color: {NAVY}; color: white; }}
    #MainMenu {{ visibility: visible; }}
    footer {{ visibility: hidden; }}
</style>
"""


def _sidebar() -> str:
    with st.sidebar:
        st.markdown("## AI Pilot Evaluation Lab")
        st.markdown(
            '<span class="sidebar-note">Independent technology demonstration — '
            "not affiliated with any institution.</span>",
            unsafe_allow_html=True,
        )
        st.divider()
        page = st.radio(
            "Section",
            [
                "Dashboard",
                "Model Registry",
                "Evaluation Runner",
                "Benchmark Results",
                "Model Comparison",
                "Enterprise Readiness",
            ],
            label_visibility="collapsed",
        )
        st.divider()
        if api.backend_ok():
            st.markdown('<span class="sidebar-note">● Backend connected</span>', unsafe_allow_html=True)
        else:
            st.markdown(
                f'<span class="error-text">● Backend unreachable ({api.BACKEND_URL})</span>',
                unsafe_allow_html=True,
            )
    return page


def main() -> None:
    st.set_page_config(
        page_title="AI Pilot Evaluation Lab",
        page_icon="📊",
        layout="wide",
    )
    st.markdown(PAGE_CSS, unsafe_allow_html=True)

    st.title("AI Pilot Evaluation Lab")
    st.caption("Independent technology demonstration — not affiliated with any institution.")

    page = _sidebar()

    pages = {
        "Dashboard": render_dashboard,
        "Model Registry": render_model_registry,
        "Evaluation Runner": render_runner,
        "Benchmark Results": render_results_page,
        "Model Comparison": render_comparison,
        "Enterprise Readiness": render_enterprise_readiness,
    }
    api.guard(pages[page])


def render_results_page() -> None:
    run_id = st.session_state.get("selected_run_id")
    render_results(run_id)


if __name__ == "__main__":
    main()
else:
    main()
