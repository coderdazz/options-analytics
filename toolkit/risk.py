from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
from scipy.stats import norm

from .models import Position
from .portfolio import value_portfolio
from .pricing import black_scholes, year_fraction


def var_es(pnl: np.ndarray, confidence: float = 0.95) -> dict:
    pnl = np.asarray(pnl, dtype=float)
    pnl = pnl[np.isfinite(pnl)]
    if len(pnl) == 0:
        return {"var": np.nan, "es": np.nan, "quantile_pnl": np.nan}
    q = float(np.quantile(pnl, 1 - confidence))
    tail = pnl[pnl <= q]
    return {"var": max(0.0, -q), "es": max(0.0, -float(tail.mean())), "quantile_pnl": q}


def parametric_var_es(value: float, annual_vol: float, horizon_days: int = 1, confidence: float = 0.95) -> dict:
    sigma = abs(value) * annual_vol * np.sqrt(horizon_days / 252)
    z = norm.ppf(confidence)
    return {"var": float(z * sigma), "es": float(sigma * norm.pdf(z) / (1 - confidence))}


def full_revaluation_monte_carlo(
    positions: list[Position], annual_vol: float, horizon_days: int = 10,
    confidence: float = 0.95, simulations: int = 10_000, drift: float = 0.0,
    vol_of_vol: float = 0.15, seed: int = 42,
) -> tuple[dict, np.ndarray]:
    """One-factor full revaluation; preserves nonlinearity and time decay.

    A production multi-underlying book should replace this with correlated factors.
    """
    if not positions:
        return {"var": 0.0, "es": 0.0}, np.array([])
    base, _ = value_portfolio(positions)
    rng = np.random.default_rng(seed)
    dt = horizon_days / 252
    shocks = np.exp((drift - 0.5 * annual_vol**2) * dt + annual_vol * np.sqrt(dt) * rng.normal(size=simulations))
    iv_shocks = rng.normal(0, vol_of_vol * np.sqrt(dt), size=simulations)
    pnl = np.zeros(simulations)
    for i, shock in enumerate(shocks):
        scenario_value = 0.0
        for p in positions:
            factor = p.quantity * p.multiplier
            if p.instrument_type == "cash":
                scenario_value += (p.current_price if p.current_price is not None else p.entry_price) * factor
            elif p.instrument_type == "equity":
                price = (p.current_price if p.current_price is not None else p.entry_price) * shock
                scenario_value += price * factor
            else:
                spot = float(p.underlying_price) * shock
                iv = max(0.0001, float(p.implied_vol) + iv_shocks[i])
                t = max(year_fraction(p.expiry) - horizon_days / 365, 0)
                scenario_value += black_scholes(
                    spot, float(p.strike), t, p.interest_rate, iv, str(p.option_type), p.dividend_yield
                ).price * factor
        pnl[i] = scenario_value - base["market_value"]
    return var_es(pnl, confidence), pnl


def historical_var_es(portfolio_returns: pd.Series, portfolio_value: float, confidence: float = 0.95) -> dict:
    return var_es(portfolio_returns.dropna().to_numpy() * portfolio_value, confidence)

