from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize


def log_returns(prices: pd.Series) -> pd.Series:
    return np.log(pd.to_numeric(prices, errors="coerce")).diff().dropna()


def historical_volatility(prices: pd.Series, window: int = 30) -> float:
    r = log_returns(prices).tail(window)
    return float(r.std(ddof=1) * np.sqrt(252)) if len(r) >= 2 else float("nan")


def ewma_volatility(prices: pd.Series, decay: float = 0.94) -> float:
    r = log_returns(prices).to_numpy()
    if len(r) < 2:
        return float("nan")
    variance = np.var(r, ddof=1)
    for value in r:
        variance = decay * variance + (1 - decay) * value**2
    return float(np.sqrt(variance * 252))


def garch11_volatility(prices: pd.Series) -> tuple[float, dict]:
    """Fit a compact Gaussian GARCH(1,1) by maximum likelihood."""
    r = log_returns(prices).to_numpy() * 100.0
    if len(r) < 30:
        return float("nan"), {"warning": "At least 30 returns are required."}
    initial_var = max(np.var(r), 1e-6)

    def nll(params: np.ndarray) -> float:
        omega, alpha, beta = params
        if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 0.999:
            return 1e12
        var = np.empty_like(r)
        var[0] = initial_var
        for i in range(1, len(r)):
            var[i] = omega + alpha * r[i - 1] ** 2 + beta * var[i - 1]
        return float(0.5 * np.sum(np.log(2 * np.pi) + np.log(var) + r**2 / var))

    fit = minimize(
        nll, x0=np.array([initial_var * 0.03, 0.07, 0.90]),
        method="SLSQP", bounds=((1e-9, None), (0, 0.999), (0, 0.999)),
        constraints={"type": "ineq", "fun": lambda p: 0.999 - p[1] - p[2]},
    )
    omega, alpha, beta = fit.x
    variance = initial_var
    for i in range(1, len(r)):
        variance = omega + alpha * r[i - 1] ** 2 + beta * variance
    forecast = omega + alpha * r[-1] ** 2 + beta * variance
    annual = np.sqrt(forecast) / 100.0 * np.sqrt(252)
    return float(annual), {
        "omega": float(omega), "alpha": float(alpha), "beta": float(beta),
        "persistence": float(alpha + beta), "converged": bool(fit.success),
    }


def volatility_term_structure(prices: pd.Series, windows=(10, 20, 30, 60, 120)) -> pd.DataFrame:
    return pd.DataFrame({
        "window": list(windows),
        "historical_vol": [historical_volatility(prices, w) for w in windows],
    })

