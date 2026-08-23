from __future__ import annotations

from datetime import date

import pandas as pd

from .models import Position
from .pricing import black_scholes, year_fraction


def value_position(position: Position, as_of: date | None = None) -> dict:
    if position.instrument_type in {"equity", "cash"}:
        unit = position.current_price if position.current_price is not None else position.entry_price
        delta = position.quantity * position.multiplier if position.instrument_type == "equity" else 0.0
        return {
            "symbol": position.symbol, "type": position.instrument_type, "quantity": position.quantity,
            "unit_price": unit, "market_value": unit * position.quantity * position.multiplier,
            "cost_basis": position.cost_basis, "pnl": (unit - position.entry_price) * position.quantity * position.multiplier,
            "delta": delta, "gamma": 0.0, "vega": 0.0, "theta": 0.0, "rho": 0.0,
        }
    required = [position.option_type, position.strike, position.expiry, position.implied_vol, position.underlying_price]
    if any(x is None for x in required):
        raise ValueError(f"Option {position.symbol} is missing contract or market inputs.")
    g = black_scholes(
        position.underlying_price, position.strike, year_fraction(position.expiry, as_of),
        position.interest_rate, position.implied_vol, position.option_type, position.dividend_yield,
    )
    factor = position.quantity * position.multiplier
    return {
        "symbol": position.symbol, "type": "option", "quantity": position.quantity,
        "unit_price": g.price, "market_value": g.price * factor, "cost_basis": position.cost_basis,
        "pnl": (g.price - position.entry_price) * factor, "delta": g.delta * factor,
        "gamma": g.gamma * factor, "vega": g.vega * factor, "theta": g.theta * factor,
        "rho": g.rho * factor,
    }


def value_portfolio(positions: list[Position], as_of: date | None = None) -> tuple[dict, list[dict]]:
    details = [value_position(p, as_of) for p in positions]
    totals = {key: sum(float(row[key]) for row in details) for key in
              ("market_value", "cost_basis", "pnl", "delta", "gamma", "vega", "theta", "rho")}
    return totals, details


def positions_from_frame(frame: pd.DataFrame) -> list[Position]:
    return [Position.from_record(row) for row in frame.to_dict("records")]

