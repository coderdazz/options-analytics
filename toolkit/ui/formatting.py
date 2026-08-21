from __future__ import annotations

from html import escape
from math import isfinite

import pandas as pd
import streamlit as st


def money(value: float | None, decimals: int = 2) -> str:
    if value is None or not isfinite(float(value)):
        return "—"
    return f"${float(value):,.{decimals}f}"


def number(value: float | None, decimals: int = 2) -> str:
    if value is None or not isfinite(float(value)):
        return "—"
    return f"{float(value):,.{decimals}f}"


def percent(value: float | None, decimals: int = 2, signed: bool = False) -> str:
    if value is None or not isfinite(float(value)):
        return "—"
    sign = "+" if signed and value > 0 else ""
    return f"{sign}{float(value):.{decimals}%}"


def integer(value: int | float | None) -> str:
    if value is None or not isfinite(float(value)):
        return "—"
    return f"{int(value):,}"


def metric_cards(items: list[tuple[str, str, str | None]]) -> None:
    """Render exact values without Streamlit metric truncation/abbreviation."""
    cards = []
    for label, value, note in items:
        note_html = f'<div class="ve-metric-note">{escape(note)}</div>' if note else ""
        cards.append(
            '<div class="ve-metric">'
            f'<div class="ve-metric-label">{escape(label)}</div>'
            f'<div class="ve-metric-value" title="{escape(value)}">{escape(value)}</div>'
            f'{note_html}</div>'
        )
    st.markdown(f'<div class="ve-metric-grid">{"".join(cards)}</div>', unsafe_allow_html=True)


def display_frame(frame: pd.DataFrame, *, height: int | None = None) -> None:
    formatted = frame.copy()
    for col in formatted.columns:
        lower = str(col).lower()
        if lower in {"iv", "implied_volatility", "spread_pct", "moneyness", "return", "spot_return", "iv_shift"}:
            formatted[col] = formatted[col].map(lambda x: percent(x) if pd.notna(x) else "—")
        elif lower in {"bid", "ask", "mid", "last", "price", "entry_price", "model_price", "scenario_price", "intrinsic", "extrinsic", "market_value", "pnl"}:
            formatted[col] = formatted[col].map(lambda x: money(x) if pd.notna(x) else "—")
        elif lower in {"volume", "open_interest", "quantity", "dte"}:
            formatted[col] = formatted[col].map(lambda x: integer(x) if pd.notna(x) else "—")
        elif lower in {"delta", "gamma", "theta", "vega", "rho", "probability_like_delta"}:
            formatted[col] = formatted[col].map(lambda x: number(x, 4) if pd.notna(x) else "—")
    kwargs = {"width": "stretch", "hide_index": True}
    if height is not None:
        kwargs["height"] = height
    st.dataframe(formatted, **kwargs)
