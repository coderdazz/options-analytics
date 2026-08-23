from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from ...models import Position
from ...portfolio import positions_from_frame, value_portfolio
from ...risk import full_revaluation_monte_carlo
from ...storage import Repository
from ..formatting import display_frame, money, number, percent, metric_cards
from ..layout import assumption_note, page_header


def render(repository: Repository) -> None:
    page_header("Portfolio & risk", "Persist the book and stress the whole position.",
                "SQLite records position inputs and valuation snapshots. Monetary values are shown in full—never silently scaled or truncated.")
    portfolios = repository.portfolios()
    with st.expander("Create portfolio", expanded=portfolios.empty):
        name = st.text_input("Portfolio name", "Core Options Book")
        if st.button("Create / open portfolio", type="primary"):
            repository.create_portfolio(name)
            st.rerun()
    if portfolios.empty:
        st.info("Create a portfolio to begin.")
        return
    selected = st.selectbox("Portfolio", portfolios.name.tolist())
    portfolio_id = int(portfolios.loc[portfolios.name == selected, "id"].iloc[0])
    with st.expander("Add a position"):
        a, b, c, d = st.columns(4)
        instrument = a.selectbox("Instrument", ["option", "equity", "cash"])
        symbol = b.text_input("Symbol", "US.AAPL")
        quantity = c.number_input("Quantity", value=1.0, step=1.0)
        entry = d.number_input("Entry price", min_value=0.0, value=10.0)
        kwargs = {}
        if instrument == "option":
            a, b, c, d, e = st.columns(5)
            kwargs = {
                "option_type": a.selectbox("Option type", ["call", "put"]),
                "strike": b.number_input("Strike", 0.01, value=180.0),
                "expiry": c.date_input("Expiry", date.today() + timedelta(days=60)),
                "implied_vol": d.number_input("Current implied volatility (%)", 0.1, 500.0, 28.0) / 100.0,
                "underlying_price": e.number_input("Spot", .01, value=185.0),
                "multiplier": 100.0,
            }
        else:
            kwargs = {"current_price": st.number_input("Current mark", min_value=0.0, value=entry), "multiplier": 1.0}
        if st.button("Add position"):
            repository.add_position(portfolio_id, Position(symbol, instrument, quantity, entry, **kwargs))
            st.rerun()
    frame = repository.positions(portfolio_id)
    if frame.empty:
        st.info("No positions saved yet.")
        return
    positions = positions_from_frame(frame)
    summary, details = value_portfolio(positions)
    metric_cards([
        ("Market value", money(summary["market_value"]), "full value"),
        ("Unrealised P&L", money(summary["pnl"]), "model/current marks"),
        ("Delta", number(summary["delta"], 2), "share equivalent"),
        ("Gamma", number(summary["gamma"], 4), "per $1 spot move"),
        ("Vega", number(summary["vega"], 2), "per 1 vol point"),
        ("Theta", number(summary["theta"], 2), "per calendar day"),
    ])
    display_frame(pd.DataFrame(details))
    if st.button("Save valuation snapshot"):
        repository.save_valuation(portfolio_id, summary, details)
        st.success("Valuation snapshot saved.")
    st.markdown("### Full-revaluation risk")
    a, b, c, d = st.columns(4)
    vol = a.number_input("Annual volatility (%)", .1, 300.0, 30.0, key="risk_vol") / 100.0
    horizon = b.slider("Horizon (days)", 1, 30, 10)
    confidence = c.select_slider("Confidence", [.90, .95, .975, .99], .95,
                                 format_func=lambda x: percent(x, 1))
    simulations = d.select_slider("Paths", [2_000, 5_000, 10_000, 25_000], 10_000,
                                  format_func=lambda x: f"{x:,}")
    metrics, pnl = full_revaluation_monte_carlo(positions, vol, horizon, confidence, simulations)
    metric_cards([
        ("Value at Risk", money(metrics["var"]), f"{percent(confidence, 1)} · {horizon} days"),
        ("Expected shortfall", money(metrics["es"]), "average beyond VaR"),
        ("Worst simulated loss", money(max(0.0, -float(np.min(pnl)))), f"{simulations:,} paths"),
    ])
    fig = px.histogram(x=pnl, nbins=90, title=f"{horizon}-day full-revaluation P&L",
                       labels={"x": "P&L ($)"}, color_discrete_sequence=["#43D6B5"])
    fig.update_xaxes(tickprefix="$", separatethousands=True)
    st.plotly_chart(fig)
    assumption_note("Current portfolio records still use the internal model unless a live quote-refresh workflow is used. Phase 4 will link canonical contract snapshots directly to saved lots and add correlated multi-underlying factors.")
