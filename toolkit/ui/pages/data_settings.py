from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from ...config.settings import Settings
from ...data.alpaca import AlpacaMarketDataProvider
from ...data.demo import DemoMarketDataProvider
from ...data.provider import ProviderError
from ..formatting import display_frame, money, percent, metric_cards
from ..layout import assumption_note, page_header


def render(settings: Settings) -> None:
    page_header("Data & settings", "Choose the feed before trusting the number.",
                "Alpaca IV and Greeks are preserved as vendor fields. Feed provenance and quote limitations remain visible throughout analytics.")
    current_source = st.session_state.provider_name
    source = st.radio("Market-data source", ["Demo", "Alpaca"], horizontal=True,
                      index=0 if current_source == "Demo" else 1)
    a, b, c = st.columns(3)
    default_symbol = st.session_state.underlying.replace("US.", "") if source == "Alpaca" else st.session_state.underlying
    underlying = a.text_input("Underlying", default_symbol)
    start = b.date_input("First expiry", date.today())
    end = c.date_input("Last expiry", date.today() + timedelta(days=100))
    option_feed = "indicative"
    stock_feed = "iex"
    if source == "Alpaca":
        a, b = st.columns(2)
        option_feed = a.selectbox("Options feed", ["indicative", "opra"],
                                  index=0 if settings.alpaca_option_feed == "indicative" else 1)
        stock_feed = b.selectbox("Equity feed", ["iex", "sip"],
                                 index=0 if settings.alpaca_stock_feed == "iex" else 1)
        configured = bool(settings.alpaca_api_key and settings.alpaca_secret_key)
        if configured:
            st.success("Alpaca credentials are configured through environment or Streamlit secrets.")
        else:
            st.warning("Add Alpaca credentials to `.streamlit/secrets.toml` locally or the Streamlit Cloud Secrets panel. Never enter them into source code.")
            st.code('[alpaca]\napi_key = "..."\nsecret_key = "..."\noption_feed = "indicative"\nstock_feed = "iex"', language="toml")
        if option_feed == "indicative":
            assumption_note("Free Alpaca Basic options data is indicative—not OPRA. It is acceptable for development and broad research, but not executable-price or transaction-cost analysis.")
    if st.button("Load option chain", type="primary"):
        provider = None
        try:
            if source == "Demo":
                provider = DemoMarketDataProvider(185.0)
                symbol = underlying.strip().upper()
            else:
                provider = AlpacaMarketDataProvider(
                    settings.alpaca_api_key or "", settings.alpaca_secret_key or "",
                    option_feed, stock_feed, settings.stale_after_seconds,
                )
                symbol = underlying.strip().upper().removeprefix("US.")
            chain = provider.option_chain(symbol, start, end)
            if not chain:
                st.warning("The provider returned no contracts for those dates.")
            else:
                st.session_state.contracts = chain
                st.session_state.underlying = symbol
                st.session_state.provider_name = source
                st.session_state.trade_quantities = {}
                st.session_state.quote_status = f"{len(chain):,} contracts from {chain[0].provider}"
                st.success(st.session_state.quote_status)
        except (ProviderError, ValueError, RuntimeError) as exc:
            st.error(f"Market-data load stopped safely: {exc}")
        finally:
            if provider is not None:
                provider.close()
    chain = st.session_state.contracts
    if chain:
        clean = [contract for contract in chain if not contract.quality_flags]
        missing_greeks = [contract for contract in chain if not contract.greeks.complete]
        metric_cards([
            ("Source", chain[0].provider.upper(), "current session"),
            ("Contracts", f"{len(chain):,}", f"{len({contract.expiry for contract in chain})} expiries"),
            ("Spot", money(chain[0].underlying_spot), chain[0].underlying),
            ("Clean quotes", percent(len(clean) / len(chain), 1), "all validation rules"),
            ("Missing Greeks", f"{len(missing_greeks):,}", "never silently filled"),
        ])
        display_frame(pd.DataFrame([contract.as_row() for contract in chain[:8]]))
    tab1, tab2, tab3 = st.tabs(["Alpaca plans", "Quote rules", "Deployment boundary"])
    with tab1:
        st.markdown(
            "**Basic ($0):** IEX equities, indicative options, 200 REST calls/minute, "
            "30 equity WebSocket symbols and 200 option quote subscriptions. The latest "
            "15 minutes of historical data are restricted.  \n"
            "**Algo Trader Plus:** SIP equities and real-time OPRA options. Current listed price: $99/month."
        )
    with tab2:
        st.markdown(
            "Quotes are flagged for missing/crossed markets, zero bids, wide spreads, low "
            "volume/open interest, missing IV/Greeks, staleness, and indicative-feed status."
        )
        st.code(
            f"stale_after_seconds = {settings.stale_after_seconds}\n"
            f"max_spread_pct = {settings.max_spread_pct:.0%}\n"
            f"min_open_interest = {settings.min_open_interest}\n"
            f"min_volume = {settings.min_volume}", language="toml",
        )
    with tab3:
        assumption_note("Streamlit Community Cloud can host one private app free. Store Alpaca credentials only in its encrypted Secrets panel. Its local filesystem is ephemeral, so use an external Postgres database for durable cloud portfolios.")
        st.markdown("See `docs/DEPLOYMENT.md` and `docs/DATA_ARCHITECTURE.md`.")

