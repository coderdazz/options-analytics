from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from ...analytics.scenarios import IVScenario, ScenarioAssumptions, scenario_grid
from ...analytics.trades import trade_from_contracts
from ...data.contracts import FillConvention
from ...pricing import black_scholes
from ..formatting import display_frame, money, number, percent, metric_cards
from ..layout import assumption_note, page_header


def render(contracts: list) -> None:
    page_header("Trade builder & scenarios", "Build from executable quotes. Reprice from the market.",
                "Create any same-underlying option combination. Entry uses an explicit fill convention; scenario marks are anchored to provider midpoints.")
    by_symbol = {contract.symbol: contract for contract in contracts}
    st.session_state.trade_quantities = {
        symbol: quantity for symbol, quantity in st.session_state.trade_quantities.items()
        if symbol in by_symbol and quantity != 0
    }
    if not st.session_state.trade_quantities:
        _starter_trade(contracts)
    symbols = list(st.session_state.trade_quantities)
    if not symbols:
        st.info("Add one or more contracts from Option Chain.")
        return

    with st.container(border=True):
        st.markdown("#### Legs")
        editor = pd.DataFrame([{
            "symbol": symbol,
            "quantity": int(st.session_state.trade_quantities[symbol]),
            "side": "BUY" if st.session_state.trade_quantities[symbol] > 0 else "SELL",
            "expiry": by_symbol[symbol].expiry,
            "strike": by_symbol[symbol].strike,
            "type": by_symbol[symbol].option_type.value,
            "bid": by_symbol[symbol].bid,
            "ask": by_symbol[symbol].ask,
            "mid": by_symbol[symbol].mid_price,
            "iv": by_symbol[symbol].implied_volatility,
            "vendor_delta": by_symbol[symbol].greeks.delta,
        } for symbol in symbols])
        edited = st.data_editor(
            editor, width="stretch", hide_index=True,
            disabled=[column for column in editor.columns if column != "quantity"],
            column_config={
                "quantity": st.column_config.NumberColumn("Signed contracts (+buy / −sell)", step=1, format="%d"),
                "bid": st.column_config.NumberColumn(format="$%.2f"),
                "ask": st.column_config.NumberColumn(format="$%.2f"),
                "mid": st.column_config.NumberColumn(format="$%.2f"),
                "iv": st.column_config.NumberColumn(format="percent"),
            }, key="leg_editor",
        )
        if st.button("Apply leg quantities"):
            st.session_state.trade_quantities = {
                str(row.symbol): int(row.quantity) for _, row in edited.iterrows() if int(row.quantity) != 0
            }
            st.rerun()

    a, b, c = st.columns(3)
    fill_label = a.selectbox("Entry fill convention", [
        "Conservative — improve 25% from natural", "Natural — buy ask / sell bid",
        "Midpoint — comparison only",
    ])
    fill = {
        "Conservative — improve 25% from natural": FillConvention.CONSERVATIVE,
        "Natural — buy ask / sell bid": FillConvention.NATURAL,
        "Midpoint — comparison only": FillConvention.MID,
    }[fill_label]
    name = b.text_input("Strategy label", "Custom option strategy")
    rate_pct = c.number_input("Risk-free rate (%)", -5.0, 30.0, 4.0, format="%.2f")
    rate = rate_pct / 100.0
    selections = [(by_symbol[s], q) for s, q in st.session_state.trade_quantities.items()]
    try:
        trade = trade_from_contracts(contracts[0].underlying, selections, fill, name=name)
    except ValueError as exc:
        st.error(str(exc))
        return
    stats = trade.expiry_statistics()
    vendor = trade.vendor_greeks()
    if stats.get("multi_expiry"):
        max_profit = max_loss = "Path-dependent"
    else:
        max_profit = "Unbounded" if stats["max_profit"] is None else money(stats["max_profit"])
        max_loss = "Unbounded" if stats["max_loss"] is None else money(stats["max_loss"])
    metric_cards([
        ("Estimated net debit", money(trade.net_debit), fill.value),
        ("Current midpoint value", money(trade.current_mid_value), "reference mark, not execution"),
        ("Maximum profit", max_profit, "expiry profile"),
        ("Maximum loss", max_loss, "size using full contractual loss"),
        ("Vendor delta", number(vendor["delta"], 2), f"source: {contracts[0].provider}"),
        ("Vendor vega / vol point", number(vendor["vega"], 2), f"source: {contracts[0].provider}"),
    ])
    if stats["breakevens"]:
        st.caption("Expiry breakeven(s): " + ", ".join(money(x) for x in stats["breakevens"]))
    if stats.get("multi_expiry"):
        st.warning("Calendar/diagonal maximum profit, loss and breakevens are path-dependent because legs expire on different dates. Dynamic scenarios remain available, but no false single-expiry statistic is shown.")
    display_frame(trade.legs_frame())
    if fill == FillConvention.MID:
        assumption_note("Midpoint entry is selected for comparison. It is not an executable-price assumption. Switch to Natural or Conservative before using the estimated P&L for a trading decision.")

    st.markdown("### Current vendor values vs model comparison")
    comparison = []
    for leg in trade.legs:
        contract = leg.contract
        if contract.implied_volatility is None:
            continue
        model = black_scholes(contract.underlying_spot, contract.strike, max(contract.dte / 365, 1/8760),
                              rate, contract.implied_volatility, contract.option_type.value)
        comparison.append({
            "symbol": contract.symbol, "market_mid": contract.mid_price, "model_price": model.price,
            "vendor_iv": contract.implied_volatility, "vendor_delta": contract.greeks.delta,
            "model_delta": model.delta, "vendor_gamma": contract.greeks.gamma,
            "model_gamma": model.gamma, "vendor_vega": contract.greeks.vega, "model_vega": model.vega,
        })
    display_frame(pd.DataFrame(comparison))
    st.caption("No reconciliation is forced: differences remain visible so quote timing, dividends, American exercise, rates and vendor conventions can be investigated.")

    st.markdown("### Dynamic P&L and Greek evolution")
    a, b, c, d = st.columns(4)
    iv_mode = a.selectbox("IV dynamics", [scenario.value for scenario in IVScenario])
    minimum_dte = min(leg.contract.dte for leg in trade.legs)
    available_days = [day for day in [0, 1, 2, 5, 10, 20] if day <= minimum_dte]
    view_day = b.selectbox("Heatmap day", available_days, index=min(3, len(available_days) - 1))
    view_iv_points = c.selectbox("Curve IV shift", [-20, -10, -5, 0, 5, 10, 20], index=3)
    dividend_pct = d.number_input("Dividend yield (%)", 0.0, 30.0, 0.0, format="%.2f")
    dividend = dividend_pct / 100.0
    extra_left, extra_right = st.columns(2)
    long_run_iv_pct = extra_left.number_input("Long-run IV (%) · mean-reverting mode", 1.0, 500.0, 25.0, format="%.2f")
    long_run_iv = long_run_iv_pct / 100.0
    local_skew = extra_right.number_input("Local skew slope (sticky-delta approximation)", -3.0, 3.0, -0.10, format="%.3f")
    base = ScenarioAssumptions(
        iv_scenario=IVScenario(iv_mode), risk_free_rate=rate, dividend_yield=dividend,
        long_run_iv=long_run_iv, local_skew_slope=local_skew,
    )
    spot_returns = np.linspace(-0.20, 0.20, 81)
    days = available_days
    shifts = np.array([-0.20, -0.10, -0.05, 0.0, 0.05, 0.10, 0.20])
    try:
        scenarios = scenario_grid(trade, spot_returns, days, shifts, base)
    except ValueError as exc:
        st.error(f"Scenario calculation stopped: {exc}")
        return
    curve = scenarios[(scenarios.days_forward == view_day) & np.isclose(scenarios.iv_shift, view_iv_points / 100)]
    fig = px.line(curve, x="spot_return", y="pnl", title=f"Underlying return vs P&L · day {view_day} · IV {view_iv_points:+d} points")
    fig.update_xaxes(tickformat="+.0%", title="Underlying return")
    fig.update_yaxes(tickprefix="$", separatethousands=True, title="Trade P&L")
    fig.add_hline(y=0, line_dash="dash", line_color="#8FA4B8")
    st.plotly_chart(fig)
    left, right = st.columns(2)
    with left:
        time_slice = scenarios[np.isclose(scenarios.iv_shift, 0.0)]
        pivot = time_slice.pivot(index="days_forward", columns="spot_return", values="pnl")
        fig = px.imshow(pivot, aspect="auto", origin="lower", color_continuous_scale="RdYlGn",
                        title="Price × time P&L", labels={"x":"Underlying return","y":"Days forward","color":"P&L"})
        fig.update_xaxes(tickformat="+.0%")
        st.plotly_chart(fig)
    with right:
        iv_slice = scenarios[scenarios.days_forward == view_day]
        pivot = iv_slice.pivot(index="iv_shift", columns="spot_return", values="pnl")
        fig = px.imshow(pivot, aspect="auto", origin="lower", color_continuous_scale="RdYlGn",
                        title=f"Price × IV P&L · day {view_day}", labels={"x":"Underlying return","y":"IV shift","color":"P&L"})
        fig.update_xaxes(tickformat="+.0%")
        fig.update_yaxes(tickformat="+.0%")
        st.plotly_chart(fig)
    greeks = curve.melt(id_vars="spot_return", value_vars=["delta", "gamma", "theta", "vega"],
                        var_name="Greek", value_name="Exposure")
    fig = px.line(greeks, x="spot_return", y="Exposure", facet_row="Greek", color="Greek",
                  title="Trade Greeks as spot moves")
    fig.update_xaxes(tickformat="+.0%")
    fig.update_layout(height=760, showlegend=False)
    fig.for_each_annotation(lambda annotation: annotation.update(text=annotation.text.split("=")[-1].upper()))
    st.plotly_chart(fig)
    assumption_note(f"IV mode: {iv_mode}. Scenario prices begin at the provider midpoint and add the Black–Scholes modeled change. Current vendor Greeks remain authoritative; future Greeks are model estimates. Sticky-delta is a local-skew approximation until the Phase 2 volatility surface is fitted.")


def _starter_trade(contracts: list) -> None:
    if not contracts:
        return
    calls = [c for c in contracts if c.option_type.value == "call" and c.greeks.delta is not None]
    if not calls:
        return
    expiry = sorted({c.expiry for c in calls})[1 if len({c.expiry for c in calls}) > 1 else 0]
    expiry_calls = [c for c in calls if c.expiry == expiry]
    long_leg = min(expiry_calls, key=lambda c: abs(c.greeks.delta - 0.65))
    short_leg = min([c for c in expiry_calls if c.strike > long_leg.strike] or expiry_calls,
                    key=lambda c: abs(c.greeks.delta - 0.30))
    st.session_state.trade_quantities = {long_leg.symbol: 1}
    if short_leg.symbol != long_leg.symbol:
        st.session_state.trade_quantities[short_leg.symbol] = -1
