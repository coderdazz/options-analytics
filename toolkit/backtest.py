from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from .pricing import black_scholes
from .volatility import historical_volatility


def backtest_option_mtm(
    prices: pd.DataFrame, strike: float, expiry: pd.Timestamp, option_type: str,
    entry_iv: float | None = None, rate: float = 0.04, multiplier: float = 100,
    quantity: float = 1, vol_window: int = 20,
) -> pd.DataFrame:
    frame = prices.copy().sort_values("timestamp")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    frame = frame[frame.timestamp.dt.date <= expiry.date()].copy()
    model, ivs = [], []
    for i, row in frame.iterrows():
        history = frame.loc[frame.timestamp <= row.timestamp, "close"]
        hv = historical_volatility(history, vol_window)
        iv = entry_iv if entry_iv is not None else (hv if np.isfinite(hv) else 0.25)
        t = max((expiry - row.timestamp).total_seconds() / (365*24*3600), 0)
        model.append(black_scholes(row.close, strike, t, rate, iv, option_type).price)
        ivs.append(iv)
    frame["model_price"] = model
    frame["implied_vol"] = ivs
    if len(frame):
        frame["option_pnl"] = (frame.model_price - frame.model_price.iloc[0]) * quantity * multiplier
        frame["underlying_return"] = frame.close / frame.close.iloc[0] - 1
    return frame

