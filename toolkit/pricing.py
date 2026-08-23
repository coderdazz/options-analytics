from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
from scipy.optimize import brentq
from scipy.stats import norm


@dataclass(frozen=True)
class Greeks:
    price: float
    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float


def year_fraction(expiry: date, as_of: date | None = None) -> float:
    as_of = as_of or date.today()
    return max((expiry - as_of).days / 365.0, 1 / (365 * 24))


def black_scholes(
    spot: float,
    strike: float,
    time_to_expiry: float,
    rate: float,
    volatility: float,
    option_type: str = "call",
    dividend_yield: float = 0.0,
) -> Greeks:
    """European Black-Scholes value and Greeks per one underlying share.

    Vega and rho are returned per one percentage-point change; theta is per day.
    At/after expiry, intrinsic value and its limiting delta are returned.
    """
    s, k = float(spot), float(strike)
    t, sigma = max(float(time_to_expiry), 0.0), max(float(volatility), 0.0)
    is_call = option_type.lower() == "call"
    if s <= 0 or k <= 0:
        raise ValueError("Spot and strike must be positive.")
    if t <= 1e-10 or sigma <= 1e-10:
        intrinsic = max(s - k, 0.0) if is_call else max(k - s, 0.0)
        if is_call:
            delta = 1.0 if s > k else (0.5 if s == k else 0.0)
        else:
            delta = -1.0 if s < k else (-0.5 if s == k else 0.0)
        return Greeks(intrinsic, delta, 0.0, 0.0, 0.0, 0.0)

    sqrt_t = np.sqrt(t)
    d1 = (np.log(s / k) + (rate - dividend_yield + 0.5 * sigma**2) * t) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    disc_r, disc_q = np.exp(-rate * t), np.exp(-dividend_yield * t)
    pdf = norm.pdf(d1)
    gamma = disc_q * pdf / (s * sigma * sqrt_t)
    vega = s * disc_q * pdf * sqrt_t / 100.0
    if is_call:
        price = s * disc_q * norm.cdf(d1) - k * disc_r * norm.cdf(d2)
        delta = disc_q * norm.cdf(d1)
        theta = (
            -(s * disc_q * pdf * sigma) / (2 * sqrt_t)
            - rate * k * disc_r * norm.cdf(d2)
            + dividend_yield * s * disc_q * norm.cdf(d1)
        ) / 365.0
        rho = k * t * disc_r * norm.cdf(d2) / 100.0
    else:
        price = k * disc_r * norm.cdf(-d2) - s * disc_q * norm.cdf(-d1)
        delta = disc_q * (norm.cdf(d1) - 1)
        theta = (
            -(s * disc_q * pdf * sigma) / (2 * sqrt_t)
            + rate * k * disc_r * norm.cdf(-d2)
            - dividend_yield * s * disc_q * norm.cdf(-d1)
        ) / 365.0
        rho = -k * t * disc_r * norm.cdf(-d2) / 100.0
    return Greeks(float(price), float(delta), float(gamma), float(vega), float(theta), float(rho))


def implied_volatility(
    market_price: float,
    spot: float,
    strike: float,
    time_to_expiry: float,
    rate: float,
    option_type: str,
    dividend_yield: float = 0.0,
) -> float:
    intrinsic = max(spot - strike, 0) if option_type == "call" else max(strike - spot, 0)
    if market_price < intrinsic - 1e-8:
        raise ValueError("Market price is below intrinsic value.")
    objective = lambda vol: black_scholes(
        spot, strike, time_to_expiry, rate, vol, option_type, dividend_yield
    ).price - market_price
    try:
        return float(brentq(objective, 1e-5, 5.0))
    except ValueError as exc:
        raise ValueError("No implied-volatility solution between 0.001% and 500%.") from exc


def scenario_surface(
    spot: float,
    strike: float,
    time_to_expiry: float,
    rate: float,
    volatility: float,
    option_type: str,
    spot_shocks: np.ndarray,
    vol_shocks: np.ndarray,
    days_forward: int = 0,
    dividend_yield: float = 0.0,
) -> list[dict]:
    remaining = max(time_to_expiry - days_forward / 365.0, 0.0)
    rows: list[dict] = []
    for ds in spot_shocks:
        scenario_spot = max(0.01, spot * (1 + float(ds)))
        for dv in vol_shocks:
            scenario_vol = max(0.0001, volatility + float(dv))
            g = black_scholes(
                scenario_spot, strike, remaining, rate, scenario_vol, option_type, dividend_yield
            )
            rows.append({
                "spot_shock": float(ds), "vol_shock": float(dv), "spot": scenario_spot,
                "volatility": scenario_vol, **g.__dict__,
            })
    return rows

