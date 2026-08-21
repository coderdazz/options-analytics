from __future__ import annotations

from pathlib import Path

import streamlit as st

from toolkit.config import Settings
from toolkit.storage import Repository
from toolkit.ui.layout import apply_layout
from toolkit.ui.pages import data_settings, market_overview, option_chain, portfolio_risk, trade_builder
from toolkit.ui.state import initialize_state

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="VolEdge | Options Analytics", page_icon="◈", layout="wide")
try:
    APP_SECRETS = st.secrets.to_dict()
except Exception:
    APP_SECRETS = {}
SETTINGS = Settings.load(ROOT, APP_SECRETS)
apply_layout()
initialize_state()


@st.cache_resource
def repository() -> Repository:
    return Repository(SETTINGS.data_dir / "options_toolkit.db")


with st.sidebar:
    st.markdown("## ◈ VolEdge")
    st.caption("OPTIONS DECISION WORKBENCH")
    page = st.radio(
        "Workspace",
        ["Market Overview", "Option Chain", "Trade Builder", "Portfolio & Risk", "Data & Settings"],
        label_visibility="collapsed",
    )
    st.divider()
    st.caption("Current market source")
    st.markdown(f"**{st.session_state.provider_name}**")
    st.caption(st.session_state.quote_status)
    st.caption("Read-only market data · no order routing")

contracts = st.session_state.contracts

if page == "Market Overview":
    market_overview.render(contracts)
elif page == "Option Chain":
    option_chain.render(contracts)
elif page == "Trade Builder":
    trade_builder.render(contracts)
elif page == "Portfolio & Risk":
    portfolio_risk.render(repository())
else:
    data_settings.render(SETTINGS)
