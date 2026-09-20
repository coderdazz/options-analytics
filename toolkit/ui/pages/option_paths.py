from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from ...analytics.paths import (
    CalibratedOptionModel,
    PathIVMode,
    calibrate_option_model,
    revalue_option,
    revalue_path,
    spot_sweep,
    time_sweep,
)
from ...data.contracts import OptionContract
from ..formatting import display_frame, money, number, percent, metric_cards
from ..layout import assumption_note, page_header


def render(contracts: list[OptionContract]) -> None:
    page_header(
        "Option path lab",
        "Follow the option mark and Greeks before expiry.",
        "Calibrate one selected contract to its current market mark, then inspect ordered spot/time paths. "
        "This is mark-to-market analysis—not an exercise-payoff chart.",
    )
    usable = [contract for contract in contracts if _has_mark(contract)]
    if not usable:
        st.info("Load a Moomoo/Alpaca chain or enter a manual option before using the path lab.")
        return

    symbols = [contract.symbol for contract in usable]
    preferred = st.session_state.get("selected_contract_symbol")
    if preferred not in symbols:
        selected_trade_symbols = [
            symbol for symbol in st.session_state.get("trade_quantities", {}) if symbol in symbols
        ]
        preferred = selected_trade_symbols[0] if selected_trade_symbols else symbols[0]
    selected_symbol = st.selectbox(
        "Selected option",
        symbols,
        index=symbols.index(preferred),
        format_func=lambda symbol: _contract_label(next(c for c in usable if c.symbol == symbol)),
    )
    st.session_state.selected_contract_symbol = selected_symbol
    contract = next(item for item in usable if item.symbol == selected_symbol)

    control_a, control_b, control_c = st.columns(3)
    rate = control_a.number_input("Risk-free rate (%)", -5.0, 30.0, 4.0, format="%.2f") / 100.0
    dividend = control_b.number_input("Dividend yield (%)", 0.0, 30.0, 0.0, format="%.2f") / 100.0
    quantity = int(control_c.number_input("Contracts for P&L", 1, 10_000, 1, step=1))

    try:
        model = calibrate_option_model(contract, rate, dividend)
    except ValueError as exc:
        st.error(str(exc))
        return

    greeks = contract.greeks
    metric_cards([
        ("Underlying spot", money(contract.underlying_spot), contract.underlying),
        ("Option mark", money(model.market_mark, 4), contract.provider),
        ("Vendor IV", percent(contract.implied_volatility), "current market state"),
        ("Delta", number(greeks.delta, 4), greeks.source),
        ("Gamma", number(greeks.gamma, 6), greeks.source),
        ("Vega / vol point", number(greeks.vega, 4), greeks.source),
        ("Theta / day", number(greeks.theta, 4), greeks.source),
        ("DTE", f"{contract.dte:,}", str(contract.expiry)),
    ])

    with st.container(border=True):
        st.markdown("#### Price calibration")
        metric_cards([
            ("Vendor-IV model price", money(model.vendor_model_price, 4), "before price calibration"),
            ("Calibrated IV", percent(model.base_iv), model.calibration_method),
            ("Calibrated price", money(model.calibrated_model_price, 4), "today at current spot"),
            ("Calibration error", money(model.calibration_error, 6), "model minus market mark"),
        ])
        st.caption(
            "Calibration fits today's option price. Moomoo Greeks remain visible as current vendor observations; "
            "future path Greeks are Black–Scholes estimates from the calibrated state."
        )
        current_model = revalue_option(model, contract.underlying_spot, 0)
        comparison = [
            {
                "Measure": "Option price",
                "Current market/vendor": money(model.market_mark, 4),
                "Calibrated Black–Scholes": money(current_model["price"], 4),
            },
            {
                "Measure": "IV",
                "Current market/vendor": percent(contract.implied_volatility),
                "Calibrated Black–Scholes": percent(model.base_iv),
            },
        ]
        comparison.extend({
            "Measure": label,
            "Current market/vendor": number(getattr(greeks, field), 6),
            "Calibrated Black–Scholes": number(current_model[field], 6),
        } for field, label in (
            ("delta", "Delta"), ("gamma", "Gamma"),
            ("vega", "Vega"), ("theta", "Theta"),
        ))
        st.dataframe(
            pd.DataFrame(comparison),
            width="stretch",
            hide_index=True,
        )
        if model.calibration_method != "Market-implied volatility":
            st.warning(
                "The market mark could not be matched by a European implied-volatility solve. "
                "The displayed fallback offset is exact today and decays to zero by expiry."
            )
        elif contract.implied_volatility is not None and abs(model.base_iv - contract.implied_volatility) > 0.05:
            st.warning(
                "Calibrated IV differs from vendor IV by more than five volatility points. Check quote timing, "
                "dividends, American exercise effects and rate assumptions before relying on longer paths."
            )

    st.markdown("### IV behaviour")
    iv_col, detail_col = st.columns(2)
    mode = PathIVMode(iv_col.selectbox("IV assumption", [item.value for item in PathIVMode]))
    parallel_shift = 0.0
    sticky_delta_slope = -0.10
    if mode == PathIVMode.PARALLEL:
        parallel_shift = detail_col.number_input(
            "Parallel IV shift (volatility points)", -100.0, 300.0, 0.0, step=1.0, format="%.2f"
        ) / 100.0
    elif mode == PathIVMode.STICKY_DELTA:
        sticky_delta_slope = detail_col.number_input(
            "Local skew slope", -3.0, 3.0, -0.10, step=0.01, format="%.3f"
        )
    else:
        detail_col.caption(_iv_mode_explanation(mode))

    custom_schedule: dict[int, float] | None = None
    if mode == PathIVMode.CUSTOM:
        schedule = st.data_editor(
            _default_iv_schedule(model.base_iv, contract.dte),
            width="stretch",
            hide_index=True,
            num_rows="dynamic",
            key=f"iv_schedule_{selected_symbol}",
            column_config={
                "day": st.column_config.NumberColumn("Day", min_value=0, step=1, format="%d"),
                "iv_pct": st.column_config.NumberColumn("IV (%)", min_value=0.01, format="%.2f"),
            },
        )
        try:
            custom_schedule = _schedule_from_frame(schedule)
        except ValueError as exc:
            st.error(str(exc))
            return

    if mode == PathIVMode.STICKY_STRIKE:
        assumption_note(
            "For one fixed strike, constant IV and sticky strike are numerically identical until a fitted "
            "strike/expiry volatility surface is available. The separate label makes the assumption explicit."
        )
    elif mode == PathIVMode.STICKY_DELTA:
        assumption_note(
            "Sticky delta uses the existing local-skew approximation, not a full surface refit. Treat distant "
            "spot moves as sensitivity analysis rather than a volatility forecast."
        )

    spot_tab, time_tab, path_tab = st.tabs(["Spot sweep", "Time sweep", "Custom path"])
    common = {
        "mode": mode,
        "parallel_shift": parallel_shift,
        "sticky_delta_slope": sticky_delta_slope,
        "custom_iv_path": custom_schedule,
    }
    with spot_tab:
        _render_spot_sweep(model, common)
    with time_tab:
        _render_time_sweep(model, common)
    with path_tab:
        _render_custom_path(model, quantity, mode, parallel_shift, sticky_delta_slope)


def _render_spot_sweep(model: CalibratedOptionModel, assumptions: dict) -> None:
    left, right = st.columns(2)
    low_pct, high_pct = left.slider(
        "Spot range (%)", -80, 100, (-20, 20), step=5,
    )
    points = right.slider("Spot points", 21, 161, 81, step=20)
    spots = np.linspace(
        model.contract.underlying_spot * (1 + low_pct / 100.0),
        model.contract.underlying_spot * (1 + high_pct / 100.0),
        points,
    )
    try:
        frame = spot_sweep(model, spots, (0, 1, 3, 5), **assumptions)
    except ValueError as exc:
        st.error(str(exc))
        return
    frame["Horizon"] = frame.day.map(lambda value: "Today" if value == 0 else f"+{value}d")
    _four_metric_charts(
        frame, "spot", "Horizon", "Underlying spot",
        anchor_x=model.contract.underlying_spot,
        anchor_values=_vendor_anchors(model.contract),
        anchor_name=f"Current {model.contract.provider} anchor",
    )
    columns = [
        "day", "remaining_dte", "spot", "iv", "price",
        "delta", "gamma", "vega", "theta",
    ]
    display_frame(frame[columns].iloc[::max(points // 10, 1)])


def _render_time_sweep(model: CalibratedOptionModel, assumptions: dict) -> None:
    moves = st.multiselect(
        "Fixed spot levels (% from current)",
        [-30, -20, -10, -5, 0, 5, 10, 20, 30],
        default=[-10, 0, 10],
        format_func=lambda value: f"{value:+d}%",
    )
    if not moves:
        st.info("Choose at least one fixed spot level.")
        return
    spots = [model.contract.underlying_spot * (1 + move / 100.0) for move in moves]
    count = min(model.contract.dte + 1, 121)
    remaining = np.unique(np.linspace(0, model.contract.dte, count).round().astype(int))
    try:
        frame = time_sweep(model, spots, remaining, **assumptions)
    except ValueError as exc:
        st.error(str(exc))
        return
    labels = {round(spot, 10): f"{move:+d}% · {money(spot)}" for move, spot in zip(moves, spots)}
    frame["Spot level"] = frame.spot.map(lambda value: labels.get(round(value, 10), money(value)))
    _four_metric_charts(
        frame, "remaining_dte", "Spot level", "Remaining DTE",
        anchor_x=model.contract.dte,
        anchor_values=_vendor_anchors(model.contract),
        anchor_name=f"Current {model.contract.provider} anchor",
    )
    assumption_note(
        "The x-axis is remaining DTE: moving from right to left represents time passing. Values at DTE 0 "
        "are intrinsic value; the charts remain MTM projections for every earlier point."
    )


def _render_custom_path(
    model: CalibratedOptionModel,
    quantity: int,
    mode: PathIVMode,
    parallel_shift: float,
    sticky_delta_slope: float,
) -> None:
    st.caption(
        "Enter ordered future observations. In Custom IV mode the IV column is used; in other modes it is "
        "ignored and the selected IV rule is applied. IV is entered as a percentage."
    )
    editor = st.data_editor(
        _default_custom_path(model.contract.underlying_spot, model.base_iv),
        width="stretch",
        hide_index=True,
        num_rows="dynamic",
        key=f"custom_option_path_{model.contract.symbol}",
        column_config={
            "day": st.column_config.NumberColumn("Day", min_value=0, step=1, format="%d"),
            "spot": st.column_config.NumberColumn("Underlying spot", min_value=0.01, format="$%.2f"),
            "iv_pct": st.column_config.NumberColumn(
                "IV (%) · custom mode", min_value=0.01, format="%.2f"
            ),
        },
    )
    path = editor.rename(columns={"iv_pct": "iv"}).copy()
    path["iv"] = pd.to_numeric(path["iv"], errors="coerce") / 100.0
    try:
        result = revalue_path(
            model,
            path,
            quantity=quantity,
            mode=mode,
            parallel_shift=parallel_shift,
            sticky_delta_slope=sticky_delta_slope,
        )
    except ValueError as exc:
        st.error(str(exc))
        return

    metric_cards([
        ("Starting option mark", money(model.market_mark, 4), "market anchor"),
        ("Final option value", money(float(result.price.iloc[-1]), 4), f"day {int(result.day.iloc[-1])}"),
        ("Cumulative MTM P&L", money(float(result.mtm_pnl.iloc[-1])), f"{quantity:,} contracts"),
        ("Final IV", percent(float(result.iv.iloc[-1])), mode.value),
    ])
    charts = [
        ("spot", "Underlying price", "$"),
        ("price", "Option price", "$"),
        ("mtm_pnl", "Cumulative mark-to-market P&L", "$"),
        ("delta", "Delta per option unit", ""),
        ("gamma", "Gamma per option unit", ""),
        ("vega", "Vega per volatility point", ""),
        ("theta", "Theta per day", ""),
    ]
    columns = st.columns(2)
    for index, (metric, title, prefix) in enumerate(charts):
        fig = px.line(result, x="day", y=metric, markers=True, title=title)
        anchor = _vendor_anchors(model.contract).get(metric)
        if anchor is not None:
            fig.add_scatter(
                x=[0], y=[anchor], mode="markers", name=f"Current {model.contract.provider} anchor",
                marker={"size": 11, "symbol": "diamond", "color": "#F6C85F"},
            )
        fig.update_xaxes(title="Day", dtick=1 if result.day.max() <= 14 else None)
        fig.update_yaxes(title=title, tickprefix=prefix, separatethousands=True)
        columns[index % 2].plotly_chart(fig)
    display_frame(result[[
        "day", "remaining_dte", "spot", "iv", "price", "mtm_pnl",
        "delta", "gamma", "vega", "theta",
    ]])


def _four_metric_charts(
    frame: pd.DataFrame,
    x: str,
    color: str,
    x_title: str,
    anchor_x: float | int,
    anchor_values: dict[str, float | None],
    anchor_name: str,
) -> None:
    charts = [
        ("price", "Option price", "$"),
        ("delta", "Delta", ""),
        ("gamma", "Gamma", ""),
        ("vega", "Vega / volatility point", ""),
    ]
    columns = st.columns(2)
    for index, (metric, title, prefix) in enumerate(charts):
        fig = px.line(frame, x=x, y=metric, color=color, title=title)
        anchor = anchor_values.get(metric)
        if anchor is not None:
            fig.add_scatter(
                x=[anchor_x], y=[anchor], mode="markers", name=anchor_name,
                marker={"size": 11, "symbol": "diamond", "color": "#F6C85F"},
            )
        fig.update_xaxes(title=x_title, tickprefix="$" if x == "spot" else "")
        fig.update_yaxes(title=title, tickprefix=prefix, separatethousands=True)
        columns[index % 2].plotly_chart(fig)


def _default_iv_schedule(base_iv: float, dte: int) -> pd.DataFrame:
    days = sorted({0, 1, 3, 5, max(dte, 0)})
    return pd.DataFrame({"day": days, "iv_pct": [base_iv * 100.0] * len(days)})


def _schedule_from_frame(frame: pd.DataFrame) -> dict[int, float]:
    clean = frame.copy()
    clean["day"] = pd.to_numeric(clean.day, errors="coerce")
    clean["iv_pct"] = pd.to_numeric(clean.iv_pct, errors="coerce")
    if clean[["day", "iv_pct"]].isna().any().any():
        raise ValueError("Custom IV schedule values must be numeric.")
    if (clean.day < 0).any() or (clean.day % 1 != 0).any() or clean.day.duplicated().any():
        raise ValueError("Custom IV schedule days must be unique, non-negative whole numbers.")
    if (clean.iv_pct <= 0).any():
        raise ValueError("Custom IV values must be positive.")
    return {int(row.day): float(row.iv_pct) / 100.0 for row in clean.itertuples()}


def _default_custom_path(spot: float, base_iv: float) -> pd.DataFrame:
    days = np.array([0, 1, 2, 3, 5, 7])
    spots = spot * np.array([1.0, 1.01, 1.02, 1.015, 1.04, 1.05])
    return pd.DataFrame({"day": days, "spot": spots, "iv_pct": base_iv * 100.0})


def _has_mark(contract: OptionContract) -> bool:
    return bool(
        (contract.mid_price is not None and contract.mid_price > 0)
        or (contract.last is not None and contract.last >= 0)
    )


def _contract_label(contract: OptionContract) -> str:
    return (
        f"{contract.underlying} · {contract.expiry} · {contract.option_type.value.upper()} "
        f"{contract.strike:g} · mark {money(contract.mid_price or contract.last, 4)} · {contract.provider}"
    )


def _iv_mode_explanation(mode: PathIVMode) -> str:
    if mode == PathIVMode.CONSTANT:
        return "Hold calibrated IV constant at every spot and time point."
    if mode == PathIVMode.STICKY_STRIKE:
        return "Keep the selected strike's calibrated IV unchanged as spot moves."
    if mode == PathIVMode.CUSTOM:
        return "Interpolate the user-entered IV schedule by future day."
    return ""


def _vendor_anchors(contract: OptionContract) -> dict[str, float | None]:
    return {
        "spot": contract.underlying_spot,
        "price": (
            contract.mid_price
            if contract.mid_price is not None and contract.mid_price > 0
            else contract.last
        ),
        "delta": contract.greeks.delta,
        "gamma": contract.greeks.gamma,
        "vega": contract.greeks.vega,
        "theta": contract.greeks.theta,
    }
