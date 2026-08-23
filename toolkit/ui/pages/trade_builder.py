from __future__ import annotations

from datetime import date, timedelta
from math import floor

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from ...analytics.scenarios import (
    IVScenario,
    ScenarioAssumptions,
    delta_gamma_price,
    delta_gamma_trade_curve,
    scenario_grid,
)
from ...analytics.trades import trade_from_contracts
from ...data.contracts import FillConvention, OptionSide
from ...data.manual import build_manual_option
from ...pricing import black_scholes
from ..formatting import display_frame, money, number, percent, metric_cards
from ..layout import assumption_note, page_header


def render(contracts: list) -> None:
    page_header("Trade builder & scenarios", "Build from executable quotes. Reprice from the market.",
                "Create any same-underlying option combination. Entry uses an explicit fill convention; scenario marks are anchored to provider midpoints.")
    _manual_leg_entry()
    contracts = st.session_state.contracts
    by_symbol = {contract.symbol: contract for contract in contracts}
    st.session_state.trade_quantities = {
        symbol: quantity for symbol, quantity in st.session_state.trade_quantities.items()
        if symbol in by_symbol and quantity != 0
    }
    symbols = list(st.session_state.trade_quantities)
    if not symbols:
        st.info("Add a manual leg above, or add one or more contracts from Option Chain.")
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
        apply_col, clear_col = st.columns(2)
        if apply_col.button("Apply leg quantities"):
            st.session_state.trade_quantities = {
                str(row.symbol): int(row.quantity) for _, row in edited.iterrows() if int(row.quantity) != 0
            }
            st.rerun()
        if clear_col.button("Clear structure"):
            st.session_state.trade_quantities = {}
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
        trade = trade_from_contracts(selections[0][0].underlying, selections, fill, name=name)
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
        ("Vendor delta", number(vendor["delta"], 2), f"source: {trade.legs[0].contract.provider}"),
        ("Vendor vega / vol point", number(vendor["vega"], 2), f"source: {trade.legs[0].contract.provider}"),
    ])
    if stats["breakevens"]:
        st.caption("Expiry breakeven(s): " + ", ".join(money(x) for x in stats["breakevens"]))
    if stats.get("multi_expiry"):
        st.warning("Calendar/diagonal maximum profit, loss and breakevens are path-dependent because legs expire on different dates. Dynamic scenarios remain available, but no false single-expiry statistic is shown.")
    display_frame(trade.legs_frame())
    if fill == FillConvention.MID:
        assumption_note("Midpoint entry is selected for comparison. It is not an executable-price assumption. Switch to Natural or Conservative before using the estimated P&L for a trading decision.")

    st.markdown("### Entered delta–gamma MTM estimate")
    reference_spot = trade.legs[0].contract.underlying_spot
    move_left, move_right = st.columns([1, 2])
    dollar_move = move_left.number_input(
        "Underlying move ($)", min_value=float(-reference_spot + 0.01),
        max_value=float(reference_spot), value=0.0,
        step=max(round(reference_spot * 0.005, 2), 0.01), format="%.2f",
    )
    scenario_spot = reference_spot + dollar_move
    local_value = sum(
        delta_gamma_price(leg.contract, scenario_spot) * leg.quantity * leg.contract.multiplier
        for leg in trade.legs
    )
    vendor = trade.vendor_greeks()
    metric_cards([
        ("Scenario underlying", money(scenario_spot), f"move {money(dollar_move)}"),
        ("Estimated structure value", money(local_value), "entered delta + gamma"),
        ("Estimated MTM P&L", money(local_value - trade.net_debit), "relative to selected entry fill"),
        ("Dollar delta", money(vendor["delta"]), "approx. P&L for a $1 underlying move"),
        ("Dollar gamma", money(vendor["gamma"]), "change in dollar delta per $1 move"),
    ])
    local_curve = delta_gamma_trade_curve(trade, np.linspace(-0.20, 0.20, 81))
    local_fig = px.line(
        local_curve, x="spot", y="pnl",
        title="Local MTM P&L from entered delta and gamma",
    )
    local_fig.update_xaxes(tickprefix="$", separatethousands=True, title="Underlying price")
    local_fig.update_yaxes(tickprefix="$", separatethousands=True, title="Estimated MTM P&L")
    local_fig.add_hline(y=0, line_dash="dash", line_color="#8FA4B8")
    move_right.plotly_chart(local_fig)
    assumption_note(
        "Local estimate per option unit: new mark ≈ current mark + Δ×ΔS + ½×Γ×ΔS². "
        "It holds time and IV constant, then scales by signed contracts × contract multiplier. "
        "Use it as a small-move sanity check; use the dynamic scenarios below for larger spot, time and IV changes."
    )

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


def _manual_leg_entry() -> None:
    with st.expander("Enter an option manually — no API call", expanded=True):
        st.caption(
            "Copy the mark, bid/ask, IV and Greeks from your broker. IV is entered as a percentage; "
            "prices and Greeks are stored exactly as entered."
        )
        row1 = st.columns(5)
        underlying = row1[0].text_input("Underlying", "AAPL", key="manual_underlying").strip().upper()
        side_label = row1[1].selectbox("Option type", ["Call", "Put"], key="manual_side")
        spot = row1[2].number_input("Underlying spot", min_value=0.01, value=100.0, step=1.0, format="%.2f", key="manual_spot")
        strike = row1[3].number_input("Strike", min_value=0.01, value=100.0, step=1.0, format="%.2f", key="manual_strike")
        expiry = row1[4].date_input("Expiry", date.today() + timedelta(days=30), min_value=date.today(), key="manual_expiry")

        row2 = st.columns(6)
        mark = row2[0].number_input("Mark / last", min_value=0.0, value=7.0, step=0.05, format="%.4f", key="manual_mark")
        bid = row2[1].number_input("Bid", min_value=0.0, value=7.0, step=0.05, format="%.4f", key="manual_bid")
        ask = row2[2].number_input("Ask", min_value=0.0, value=7.0, step=0.05, format="%.4f", key="manual_ask")
        iv_pct = row2[3].number_input("Implied volatility (%)", min_value=0.01, value=30.0, step=1.0, format="%.2f", key="manual_iv")
        multiplier = row2[4].number_input("Contract multiplier", min_value=1.0, value=100.0, step=1.0, format="%.0f", key="manual_multiplier")
        symbol_default = f"{underlying or 'OPTION'}-MANUAL"
        symbol = row2[5].text_input("Contract label / symbol", symbol_default, key="manual_symbol")

        row3 = st.columns(5)
        delta = row3[0].number_input("Delta", value=0.20, step=0.01, format="%.6f", key="manual_delta")
        gamma = row3[1].number_input("Gamma", value=0.00034, step=0.0001, format="%.6f", key="manual_gamma")
        theta = row3[2].number_input("Theta / day", value=0.0, step=0.01, format="%.6f", key="manual_theta")
        vega = row3[3].number_input("Vega / vol point", value=0.0, step=0.01, format="%.6f", key="manual_vega")
        rho = row3[4].number_input("Rho", value=0.0, step=0.01, format="%.6f", key="manual_rho")

        sizing = st.radio("Size by", ["Contracts", "Capital budget"], horizontal=True, key="manual_sizing")
        sizing_left, sizing_right, sizing_note = st.columns([1, 1, 2])
        direction = sizing_left.selectbox("Direction", ["Buy", "Sell"], key="manual_direction")
        reference_price = ask if direction == "Buy" else bid
        if reference_price <= 0:
            reference_price = mark
        if sizing == "Contracts":
            quantity = int(sizing_right.number_input("Number of contracts", min_value=1, value=100, step=1, key="manual_quantity"))
            capital = quantity * reference_price * multiplier
        else:
            budget = sizing_right.number_input("Capital budget", min_value=0.0, value=50_000.0, step=1_000.0, format="%.2f", key="manual_budget")
            unit_cost = reference_price * multiplier
            quantity = floor(budget / unit_cost) if unit_cost > 0 else 0
            capital = quantity * unit_cost
        sizing_note.markdown(
            f"**Calculated size:** {quantity:,} contract{'s' if quantity != 1 else ''}  \n"
            f"**Premium/notional at reference price:** {money(capital)}  \n"
            f"{quantity:,} × {money(reference_price, 4)} × {multiplier:,.0f}"
        )

        if st.button("Add manual leg to structure", type="primary", disabled=quantity < 1):
            try:
                contract = build_manual_option(
                    underlying=underlying, symbol=symbol,
                    option_type=OptionSide.CALL if side_label == "Call" else OptionSide.PUT,
                    strike=strike, expiry=expiry, underlying_spot=spot,
                    bid=bid, ask=ask, last=mark, implied_volatility=iv_pct / 100.0,
                    delta=delta, gamma=gamma, theta=theta, vega=vega, rho=rho,
                    multiplier=multiplier,
                )
                same_underlying = [
                    item for item in st.session_state.contracts
                    if item.underlying == contract.underlying and item.symbol != contract.symbol
                ]
                st.session_state.contracts = same_underlying + [contract]
                signed_quantity = quantity if direction == "Buy" else -quantity
                if not same_underlying:
                    st.session_state.trade_quantities = {}
                st.session_state.trade_quantities[contract.symbol] = signed_quantity
                st.session_state.underlying = contract.underlying
                st.session_state.provider_name = "Manual"
                st.session_state.quote_status = "Manual inputs · no market-data call"
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


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
