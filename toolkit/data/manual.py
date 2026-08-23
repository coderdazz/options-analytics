from __future__ import annotations

from datetime import date
from math import isfinite

from .contracts import GreeksQuote, OptionContract, OptionSide, utc_now


def _non_negative(name: str, value: float | None) -> float | None:
    if value is None:
        return None
    value = float(value)
    if not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite, non-negative number.")
    return value


def build_manual_option(
    *,
    underlying: str,
    symbol: str,
    option_type: OptionSide | str,
    strike: float,
    expiry: date,
    underlying_spot: float,
    bid: float | None,
    ask: float | None,
    last: float | None,
    implied_volatility: float,
    delta: float,
    gamma: float,
    theta: float = 0.0,
    vega: float = 0.0,
    rho: float = 0.0,
    multiplier: float = 100.0,
) -> OptionContract:
    """Build a validated contract from values copied from a broker terminal.

    Volatility is supplied as a decimal (30% is ``0.30``). Greeks remain in
    the vendor's per-option-unit convention; exposure scaling happens later.
    """
    underlying = underlying.strip().upper()
    symbol = symbol.strip().upper()
    if not underlying:
        raise ValueError("Underlying is required.")
    if not symbol:
        raise ValueError("A contract label or symbol is required.")
    try:
        side = option_type if isinstance(option_type, OptionSide) else OptionSide(str(option_type).lower())
    except ValueError as exc:
        raise ValueError("Option type must be call or put.") from exc
    strike = float(strike)
    underlying_spot = float(underlying_spot)
    implied_volatility = float(implied_volatility)
    multiplier = float(multiplier)
    if not all(isfinite(value) and value > 0 for value in
               (strike, underlying_spot, implied_volatility, multiplier)):
        raise ValueError("Strike, spot, implied volatility and multiplier must be positive.")
    if expiry < date.today():
        raise ValueError("Expiry cannot be in the past.")
    bid = _non_negative("Bid", bid)
    ask = _non_negative("Ask", ask)
    last = _non_negative("Mark/last", last)
    if bid is not None and ask is not None and ask < bid:
        raise ValueError("Ask must be greater than or equal to bid.")
    if bid == 0 and ask == 0 and last is not None:
        bid = ask = None
    if bid is None and ask is None and last is None:
        raise ValueError("Enter a bid/ask market or a mark/last price.")
    greek_values = (float(delta), float(gamma), float(theta), float(vega), float(rho))
    if not all(isfinite(value) for value in greek_values):
        raise ValueError("All entered Greeks must be finite numbers.")
    timestamp = utc_now()
    return OptionContract(
        underlying=underlying,
        symbol=symbol,
        option_type=side,
        strike=strike,
        expiry=expiry,
        bid=bid,
        ask=ask,
        last=last,
        volume=None,
        open_interest=None,
        implied_volatility=implied_volatility,
        greeks=GreeksQuote(*greek_values, source="manual"),
        underlying_spot=underlying_spot,
        timestamp=timestamp,
        multiplier=multiplier,
        provider="manual",
        feed="manual",
        quality_flags=("manual_input",),
    )
