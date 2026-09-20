from __future__ import annotations

import pandas as pd
import streamlit as st

from ...data.contracts import OptionSide
from ..formatting import display_frame, money, percent, metric_cards
from ..layout import page_header


def _terminal_frame(frame: pd.DataFrame) -> pd.DataFrame:
    metrics = ["bid", "ask", "mid", "iv", "delta", "gamma", "theta", "vega", "volume", "open_interest",
               "intrinsic", "extrinsic", "spread_pct", "quality", "symbol"]
    calls = frame[frame.option_type == "call"][["strike"] + metrics].copy()
    puts = frame[frame.option_type == "put"][["strike"] + metrics].copy()
    calls = calls.rename(columns={c: f"CALL {c}" for c in metrics})
    puts = puts.rename(columns={c: f"PUT {c}" for c in metrics})
    return calls.merge(puts, on="strike", how="outer").sort_values("strike")


def render(contracts: list) -> None:
    page_header("Option chain", "Calls | Strike | Puts", "Provider IV and Greeks are displayed directly. Midpoint is a reference mark, never an assumed execution price.")
    if not contracts:
        st.info("Load an option chain in Data & Settings.")
        return
    frame = pd.DataFrame([c.as_row() for c in contracts])
    if contracts[0].feed == "indicative":
        st.error("Alpaca Basic indicative options data is not OPRA. Quotes below are research inputs, not executable markets.")
    expiries = sorted(frame.expiry.unique())
    a, b, c, d = st.columns(4)
    expiry = a.selectbox("Expiry", expiries, format_func=lambda x: f"{x} · {(x - contracts[0].timestamp.date()).days} DTE")
    min_oi = b.number_input("Minimum open interest", 0, 1_000_000, 0, step=10)
    min_volume = c.number_input("Minimum volume", 0, 1_000_000, 0, step=10)
    max_spread_pct = d.slider("Maximum bid/ask width (%)", 1, 200, 50)
    max_spread = max_spread_pct / 100.0
    e, f, g = st.columns(3)
    min_delta, max_delta = e.slider("Absolute delta", 0.0, 1.0, (0.0, 1.0), step=.05)
    strike_min, strike_max = f.slider("Strike range", float(frame.strike.min()), float(frame.strike.max()),
                                      (float(frame.strike.min()), float(frame.strike.max())))
    include_flagged = g.toggle("Include flagged quotes", value=True)
    selected = frame[(frame.expiry == expiry) & (frame.open_interest.fillna(0) >= min_oi)
                     & (frame.volume.fillna(0) >= min_volume)
                     & (frame.spread_pct.fillna(float("inf")) <= max_spread)
                     & (frame.strike.between(strike_min, strike_max))]
    abs_delta = selected.delta.abs()
    selected = selected[abs_delta.between(min_delta, max_delta)]
    if not include_flagged:
        selected = selected[selected.quality == "OK"]
    metric_cards([
        ("Underlying", money(contracts[0].underlying_spot), contracts[0].underlying),
        ("Expiry", str(expiry), f"{(expiry - contracts[0].timestamp.date()).days} DTE"),
        ("Visible contracts", f"{len(selected):,}", f"of {len(frame[frame.expiry == expiry]):,}"),
        ("Provider", contracts[0].provider.upper(), contracts[0].timestamp.strftime("%Y-%m-%d %H:%M UTC")),
    ])
    if selected.empty:
        st.warning("No contracts pass the current filters.")
        return
    terminal = _terminal_frame(selected)
    display_frame(terminal, height=520)
    st.markdown("### Add a leg to Trade Builder")
    a, b, c, d = st.columns([1, 2.4, 1, 1])
    side = a.selectbox("Contract side", ["call", "put"])
    choices = selected[selected.option_type == side].sort_values("strike")
    if choices.empty:
        st.info(f"No {side}s pass the filters.")
        return
    choices = choices.reset_index(drop=True)
    default_index = int((choices.delta.abs() - 0.50).abs().fillna(float("inf")).argmin())
    symbol = b.selectbox("Contract", choices.symbol.tolist(), index=default_index,
                         format_func=lambda s: _contract_label(choices, s))
    action = c.selectbox("Action", ["BUY", "SELL"])
    quantity = d.number_input("Contracts", 1, 10_000, 1)
    if st.button("Add selected leg", type="primary"):
        st.session_state.trade_quantities[symbol] = int(quantity) * (1 if action == "BUY" else -1)
        st.session_state.selected_contract_symbol = symbol
        st.success("Leg added. Open Trade Builder or Option Path Lab to inspect it.")


def _contract_label(frame: pd.DataFrame, symbol: str) -> str:
    row = frame[frame.symbol == symbol].iloc[0]
    return f"{row.option_type.upper()} {row.strike:g} · bid {money(row.bid)} / ask {money(row.ask)} · IV {percent(row.iv)} · Δ {row.delta:.3f}"
