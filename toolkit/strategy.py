from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from scipy.stats import norm

from .pricing import black_scholes


def strategy_distribution(
    legs: pd.DataFrame, spot: float, horizon_years: float, expected_return: float,
    forecast_vol: float, simulations: int = 20_000, seed: int = 7,
) -> tuple[pd.DataFrame, dict]:
    """Simulate terminal strategy P&L for equity/options legs held to the horizon."""
    rng = np.random.default_rng(seed)
    terminal = spot * np.exp(
        (expected_return - 0.5 * forecast_vol**2) * horizon_years
        + forecast_vol * np.sqrt(horizon_years) * rng.normal(size=simulations)
    )
    pnl = np.zeros(simulations)
    for _, leg in legs.iterrows():
        qty, mult, entry = float(leg.quantity), float(leg.multiplier), float(leg.entry_price)
        if leg.instrument_type == "equity":
            terminal_value = terminal
        else:
            strike = float(leg.strike)
            terminal_value = np.maximum(terminal - strike, 0) if leg.option_type == "call" else np.maximum(strike - terminal, 0)
        pnl += (terminal_value - entry) * qty * mult
    stats = {
        "probability_profit": float(np.mean(pnl > 0)), "expected_pnl": float(np.mean(pnl)),
        "median_pnl": float(np.median(pnl)), "p05": float(np.quantile(pnl, 0.05)),
        "p95": float(np.quantile(pnl, 0.95)), "expected_terminal_spot": float(np.mean(terminal)),
    }
    return pd.DataFrame({"terminal_spot": terminal, "pnl": pnl}), stats


def rank_option_chain(
    chain: pd.DataFrame, spot: float, target_move: float, target_days: int,
    forecast_vol: float, rate: float = 0.04, option_type: str = "call",
) -> pd.DataFrame:
    """Rank contracts by scenario return, convexity, liquidity, and vol value.

    Scores are decision support—not trade recommendations or forecasts.
    """
    required = {"symbol", "strike", "dte", "bid", "ask", "iv", "open_interest", "volume"}
    missing = required - set(chain.columns)
    if missing:
        raise ValueError(f"Option chain is missing: {sorted(missing)}")
    rows = []
    for _, c in chain.iterrows():
        t = max(float(c.dte) / 365, 1 / 365)
        mid = max((float(c.bid) + float(c.ask)) / 2, 0.01)
        base = black_scholes(spot, c.strike, t, rate, c.iv, option_type)
        scenario = black_scholes(
            spot * (1 + target_move), c.strike, max(t - target_days / 365, 0),
            rate, max(0.01, forecast_vol), option_type,
        )
        spread_pct = (float(c.ask) - float(c.bid)) / mid
        scenario_return = (scenario.price - mid) / mid
        liquidity = np.log1p(float(c.open_interest)) + 0.5 * np.log1p(float(c.volume)) - 5 * spread_pct
        vol_value = (forecast_vol - float(c.iv)) / max(float(c.iv), 0.01)
        convexity = base.gamma * spot**2 / max(mid, 0.01)
        rows.append({**c.to_dict(), "model_price": base.price, "delta": base.delta, "gamma": base.gamma,
                     "vega": base.vega, "scenario_price": scenario.price, "scenario_return": scenario_return,
                     "spread_pct": spread_pct, "vol_value": vol_value, "convexity": convexity,
                     "raw_liquidity": liquidity})
    result = pd.DataFrame(rows)
    def z(s: pd.Series) -> pd.Series:
        std = s.std(ddof=0)
        return (s - s.mean()) / std if std and np.isfinite(std) else pd.Series(0.0, index=s.index)
    result["score"] = 0.50*z(result.scenario_return) + 0.20*z(result.raw_liquidity) + 0.15*z(result.vol_value) + 0.15*z(result.convexity)
    return result.sort_values("score", ascending=False).reset_index(drop=True)


def demo_chain(spot: float, volatility: float, option_type: str = "call") -> pd.DataFrame:
    rows = []
    for dte in (14, 30, 45, 60, 90):
        for m in np.arange(0.75, 1.26, 0.05):
            strike = round(spot * m, 2)
            g = black_scholes(spot, strike, dte / 365, 0.04, volatility, option_type)
            spread = max(0.02, 0.025 * g.price)
            rows.append({"symbol": f"DEMO-{dte}-{option_type[0].upper()}-{strike:.2f}", "strike": strike,
                         "dte": dte, "bid": max(0.01, g.price - spread/2), "ask": g.price + spread/2,
                         "iv": volatility * (1 + 0.25 * abs(np.log(strike/spot)) - 0.10 * np.log(strike/spot)),
                         "open_interest": int(2000*np.exp(-5*abs(m-1))+50),
                         "volume": int(500*np.exp(-6*abs(m-1))+10)})
    return pd.DataFrame(rows)

