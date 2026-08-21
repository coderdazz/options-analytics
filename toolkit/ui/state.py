from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from ..data.contracts import OptionContract
from ..data.demo import DemoMarketDataProvider


def initialize_state() -> None:
    defaults = {
        "underlying": "US.AAPL",
        "provider_name": "Demo",
        "contracts": [],
        "trade_quantities": {},
        "quote_status": "Demo market data",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if not st.session_state.contracts:
        provider = DemoMarketDataProvider(185.0)
        st.session_state.contracts = provider.option_chain(
            st.session_state.underlying, date.today(), date.today() + timedelta(days=100)
        )


def contracts() -> list[OptionContract]:
    return st.session_state.contracts

