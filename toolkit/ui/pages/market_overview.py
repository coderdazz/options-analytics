from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from ...data.contracts import OptionSide
from ..formatting import money, number, percent, metric_cards
from ..layout import assumption_note, page_header


def render(contracts: list) -> None:
    page_header("Market overview", "Live inputs first. Models second.",
                "Current quote, implied volatility and Greeks retain their provider provenance; theoretical values are comparisons, not replacements.")
    if not contracts:
        st.info("Load an option chain in Data & Settings.")
        return
    spot = contracts[0].underlying_spot
    frame = pd.DataFrame([c.as_row() for c in contracts])
    good = frame[frame.quality == "OK"]
    atm = frame.iloc[(frame.strike - spot).abs().argsort()[: max(1, len(frame.expiry.unique()))]]
    metric_cards([
        ("Underlying spot", money(spot), contracts[0].underlying),
        ("Contracts", f"{len(frame):,}", f"{len(frame.expiry.unique())} expiries"),
        ("Clean quotes", percent(len(good) / len(frame), 1), "quality rules passed"),
        ("Median ATM IV", percent(float(atm.iv.median()), 2), f"source: {contracts[0].provider}"),
    ])
    if contracts[0].feed == "indicative":
        assumption_note("ALPACA INDICATIVE FEED: these are modified/calculated quotes, not consolidated executable OPRA markets. Do not use this feed to estimate fills or make a final order decision.")
    left, right = st.columns([1.35, 1])
    with left:
        fig = px.scatter(frame, x="strike", y="iv", color="expiry", symbol="option_type",
                         hover_name="symbol", title="Market implied volatility by strike")
        fig.update_yaxes(tickformat=".1%", title="Implied volatility")
        fig.update_layout(height=430)
        st.plotly_chart(fig)
    with right:
        st.markdown("### Source discipline")
        st.markdown(
            f"**Market source:** `{contracts[0].provider}`  \n"
            f"**Quote timestamp:** `{contracts[0].timestamp.isoformat()}`  \n"
            "**Current IV/Greeks:** provider values when available  \n"
            "**Future scenario evolution:** Black–Scholes, anchored to the current market mark"
        )
        assumption_note("Vendor and Black–Scholes values can legitimately differ because of American exercise, discrete dividends, the live yield curve, surface/skew conventions, quote timing, feed coverage, and vendor methodology. The app never overwrites the current provider mark or Greeks.")
