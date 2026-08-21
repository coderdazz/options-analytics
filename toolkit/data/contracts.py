from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import StrEnum
from math import isfinite


class OptionSide(StrEnum):
    CALL = "call"
    PUT = "put"


class FillConvention(StrEnum):
    MID = "mid"
    CONSERVATIVE = "conservative"
    NATURAL = "natural"


@dataclass(frozen=True, slots=True)
class GreeksQuote:
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    rho: float | None = None
    source: str = "missing"

    @property
    def complete(self) -> bool:
        return all(value is not None and isfinite(value) for value in
                   (self.delta, self.gamma, self.theta, self.vega))


@dataclass(frozen=True, slots=True)
class UnderlyingQuote:
    symbol: str
    spot: float
    timestamp: datetime
    provider: str


@dataclass(frozen=True, slots=True)
class OptionContract:
    underlying: str
    symbol: str
    option_type: OptionSide
    strike: float
    expiry: date
    bid: float | None
    ask: float | None
    last: float | None
    volume: int | None
    open_interest: int | None
    implied_volatility: float | None
    greeks: GreeksQuote
    underlying_spot: float
    timestamp: datetime
    multiplier: float = 100.0
    provider: str = "unknown"
    currency: str = "USD"
    bid_size: float | None = None
    ask_size: float | None = None
    feed: str | None = None
    quality_flags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def dte(self) -> int:
        return max((self.expiry - self.timestamp.date()).days, 0)

    @property
    def mid_price(self) -> float | None:
        if self.bid is None or self.ask is None or self.bid < 0 or self.ask < self.bid:
            return None
        return (self.bid + self.ask) / 2.0

    @property
    def intrinsic_value(self) -> float:
        if self.option_type == OptionSide.CALL:
            return max(self.underlying_spot - self.strike, 0.0)
        return max(self.strike - self.underlying_spot, 0.0)

    @property
    def extrinsic_value(self) -> float | None:
        mark = self.mid_price if self.mid_price is not None else self.last
        return None if mark is None else mark - self.intrinsic_value

    @property
    def bid_ask_spread(self) -> float | None:
        return None if self.bid is None or self.ask is None else self.ask - self.bid

    @property
    def bid_ask_pct(self) -> float | None:
        mid = self.mid_price
        return None if mid is None or mid <= 0 else (self.ask - self.bid) / mid

    @property
    def moneyness(self) -> float:
        return self.strike / self.underlying_spot

    def price_for_fill(
        self,
        is_buy: bool,
        convention: FillConvention,
        improvement_fraction: float = 0.25,
    ) -> float:
        """Return an explicit estimated fill; never silently assumes midpoint.

        Conservative means 25% of the way from the natural quote toward mid by
        default: ask minus 25% of half-spread for buys, bid plus it for sells.
        """
        if self.bid is None or self.ask is None or self.mid_price is None:
            if self.last is None:
                raise ValueError(f"{self.symbol} has no usable bid/ask or last price.")
            return float(self.last)
        natural = self.ask if is_buy else self.bid
        if convention == FillConvention.NATURAL:
            return float(natural)
        if convention == FillConvention.MID:
            return float(self.mid_price)
        fraction = min(max(improvement_fraction, 0.0), 1.0)
        return float(natural + fraction * (self.mid_price - natural))

    def as_row(self) -> dict[str, object]:
        return {
            "underlying": self.underlying, "symbol": self.symbol,
            "option_type": self.option_type.value, "expiry": self.expiry,
            "dte": self.dte, "strike": self.strike, "bid": self.bid,
            "ask": self.ask, "mid": self.mid_price, "last": self.last,
            "iv": self.implied_volatility, "delta": self.greeks.delta,
            "gamma": self.greeks.gamma, "theta": self.greeks.theta,
            "vega": self.greeks.vega, "rho": self.greeks.rho,
            "volume": self.volume, "open_interest": self.open_interest,
            "bid_size": self.bid_size, "ask_size": self.ask_size, "feed": self.feed,
            "intrinsic": self.intrinsic_value, "extrinsic": self.extrinsic_value,
            "spread_pct": self.bid_ask_pct, "moneyness": self.moneyness,
            "probability_like_delta": abs(self.greeks.delta) if self.greeks.delta is not None else None,
            "timestamp": self.timestamp, "provider": self.provider,
            "quality": ", ".join(self.quality_flags) if self.quality_flags else "OK",
        }


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
