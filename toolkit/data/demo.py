from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import numpy as np
import pandas as pd

from ..pricing import black_scholes
from .contracts import GreeksQuote, OptionContract, OptionSide, UnderlyingQuote
from .validation import quote_quality_flags


class DemoMarketDataProvider:
    """Deterministic offline provider with vendor-like IV/skew and Greeks."""

    name = "demo"

    def __init__(self, spot: float = 185.0, seed: int = 11):
        self.spot = float(spot)
        self.seed = seed
        self._timestamp = datetime.combine(date.today(), time(15, 55), tzinfo=timezone.utc)

    def underlying_quote(self, symbol: str) -> UnderlyingQuote:
        return UnderlyingQuote(symbol, self.spot, self._timestamp, self.name)

    def option_chain(
        self, symbol: str, start: date | None = None, end: date | None = None
    ) -> list[OptionContract]:
        today = date.today()
        start = start or today + timedelta(days=7)
        end = end or today + timedelta(days=100)
        expiries = [today + timedelta(days=d) for d in (14, 30, 45, 60, 90)]
        expiries = [e for e in expiries if start <= e <= end]
        contracts: list[OptionContract] = []
        rng = np.random.default_rng(self.seed)
        for expiry in expiries:
            dte = (expiry - today).days
            for strike in np.arange(round(self.spot * 0.70 / 5) * 5, self.spot * 1.31, 5):
                log_m = np.log(strike / self.spot)
                iv = 0.275 - 0.12 * log_m + 0.34 * log_m**2 + 0.015 * np.sqrt(dte / 365)
                for side in (OptionSide.CALL, OptionSide.PUT):
                    g = black_scholes(self.spot, strike, dte / 365, 0.04, iv, side.value, 0.005)
                    micro_noise = float(rng.normal(0, max(0.004, g.price * 0.002)))
                    market_mid = max(0.01, g.price + micro_noise)
                    half_spread = max(0.01, min(0.60, market_mid * (0.012 + 0.10 * abs(log_m))))
                    bid, ask = max(0.0, market_mid - half_spread), market_mid + half_spread
                    liquidity = np.exp(-6 * abs(log_m)) * np.exp(-dte / 300)
                    contract = OptionContract(
                        underlying=symbol, symbol=f"{symbol}-{expiry:%y%m%d}-{side.value[0].upper()}-{strike:g}",
                        option_type=side, strike=float(strike), expiry=expiry, bid=float(bid), ask=float(ask),
                        last=float(market_mid + rng.normal(0, half_spread / 3)), volume=int(10 + 900 * liquidity),
                        open_interest=int(50 + 4000 * liquidity), implied_volatility=float(iv),
                        greeks=GreeksQuote(g.delta, g.gamma, g.theta, g.vega, g.rho, "demo_vendor"),
                        underlying_spot=self.spot, timestamp=self._timestamp, provider=self.name,
                        feed="synthetic",
                    )
                    flags = quote_quality_flags(contract, stale_after_seconds=10**9)
                    contracts.append(OptionContract(**{
                        key: getattr(contract, key) for key in contract.__dataclass_fields__ if key != "quality_flags"
                    }, quality_flags=flags))
        return contracts

    def historical_prices(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        dates = pd.bdate_range(start=start, end=end)
        rng = np.random.default_rng(self.seed)
        close = self.spot * np.exp(np.cumsum(rng.normal(0.00025, 0.017, len(dates))))
        return pd.DataFrame({"timestamp": dates, "close": close,
                             "volume": rng.integers(1_000_000, 8_000_000, len(dates))})

    def close(self) -> None:
        return None
