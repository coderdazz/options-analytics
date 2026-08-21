from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .contracts import GreeksQuote, OptionContract, OptionSide, UnderlyingQuote
from .provider import ProviderError
from .validation import quote_quality_flags


def _number(row: pd.Series, *names: str, scale: float = 1.0) -> float | None:
    for name in names:
        if name in row and pd.notna(row[name]):
            try:
                value = float(row[name]) * scale
                return value if np.isfinite(value) else None
            except (TypeError, ValueError):
                continue
    return None


def _integer(row: pd.Series, *names: str) -> int | None:
    value = _number(row, *names)
    return None if value is None else int(value)


def _option_side(value: Any) -> OptionSide:
    text = str(value).lower()
    if "call" in text or text in {"c", "1"}:
        return OptionSide.CALL
    if "put" in text or text in {"p", "2"}:
        return OptionSide.PUT
    raise ProviderError(f"Unknown Moomoo option type: {value!r}")


def _quote_timestamp(row: pd.Series, symbol: str | None = None) -> datetime:
    candidates = []
    for field in ("update_time", "time_key", "timestamp"):
        if field in row:
            candidates.append(row[field])
    if "data_date" in row and "data_time" in row:
        candidates.append(f"{row['data_date']} {row['data_time']}")
    for value in candidates:
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.notna(parsed):
            timestamp = parsed.to_pydatetime()
            if timestamp.tzinfo is None:
                # Moomoo documents US update_time in US Eastern time and HK/
                # A-share update_time in Beijing time. Normalize once to UTC.
                zone = ZoneInfo("America/New_York") if str(symbol).upper().startswith("US.") else ZoneInfo("Asia/Hong_Kong")
                timestamp = timestamp.replace(tzinfo=zone)
            return timestamp.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def contracts_from_moomoo_frames(
    underlying: str,
    underlying_spot: float,
    static: pd.DataFrame,
    snapshots: pd.DataFrame,
    stale_after_seconds: int = 300,
) -> list[OptionContract]:
    """Map Moomoo frames into provider-independent contracts.

    The SDK has used both generic (`implied_volatility`) and option-prefixed
    (`option_implied_volatility`) snapshot columns. Both are accepted and units
    are normalized from percentage points to decimals only when needed.
    """
    if static.empty:
        return []
    code_col = "code" if "code" in static else "symbol"
    quote_code_col = "code" if "code" in snapshots else "symbol"
    merged = static.merge(snapshots, left_on=code_col, right_on=quote_code_col,
                          how="left", suffixes=("", "_quote"))
    contracts: list[OptionContract] = []
    for _, row in merged.iterrows():
        symbol = str(row.get(code_col))
        expiry_value = row.get("strike_time", row.get("expiry", row.get("expiry_date")))
        expiry = pd.to_datetime(expiry_value, errors="coerce")
        if pd.isna(expiry):
            continue
        iv = _number(row, "implied_volatility", "option_implied_volatility", "iv")
        if iv is not None and iv > 5:
            iv /= 100.0
        greeks = GreeksQuote(
            delta=_number(row, "delta", "option_delta"),
            gamma=_number(row, "gamma", "option_gamma"),
            theta=_number(row, "theta", "option_theta"),
            vega=_number(row, "vega", "option_vega"),
            rho=_number(row, "rho", "option_rho"),
            source="moomoo",
        )
        contract = OptionContract(
            underlying=underlying, symbol=symbol,
            option_type=_option_side(row.get("option_type", row.get("type"))),
            strike=float(_number(row, "strike_price", "option_strike_price", "strike") or 0),
            expiry=expiry.date(), bid=_number(row, "bid_price", "bid"),
            ask=_number(row, "ask_price", "ask"), last=_number(row, "last_price", "last"),
            volume=_integer(row, "volume", "option_volume"),
            open_interest=_integer(row, "open_interest", "option_open_interest"),
            implied_volatility=iv, greeks=greeks, underlying_spot=float(underlying_spot),
            timestamp=_quote_timestamp(row, underlying),
            multiplier=float(_number(row, "lot_size", "option_contract_size", "contract_multiplier") or 100),
            provider="moomoo",
        )
        flags = quote_quality_flags(contract, stale_after_seconds=stale_after_seconds)
        contracts.append(OptionContract(**{
            key: getattr(contract, key) for key in contract.__dataclass_fields__ if key != "quality_flags"
        }, quality_flags=flags))
    return contracts


class MoomooMarketDataProvider:
    """Read-only Moomoo OpenD provider; never creates a trading context."""

    name = "moomoo"

    def __init__(self, host: str = "127.0.0.1", port: int = 11111, stale_after_seconds: int = 300):
        try:
            from moomoo import KLType, OpenQuoteContext, RET_OK
        except ImportError as exc:
            raise ProviderError("Install `moomoo-api` to enable live Moomoo data.") from exc
        self._ret_ok = RET_OK
        self._kl_type = KLType
        self._ctx = OpenQuoteContext(host=host, port=port)
        self.stale_after_seconds = stale_after_seconds

    def _snapshot_frame(self, codes: list[str]) -> pd.DataFrame:
        frames = []
        for offset in range(0, len(codes), 200):
            ret, data = self._ctx.get_market_snapshot(codes[offset:offset + 200])
            if ret != self._ret_ok:
                raise ProviderError(str(data))
            frames.append(data)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def underlying_quote(self, symbol: str) -> UnderlyingQuote:
        frame = self._snapshot_frame([symbol])
        if frame.empty:
            raise ProviderError(f"No Moomoo quote returned for {symbol}.")
        row = frame.iloc[0]
        spot = _number(row, "last_price", "price")
        if spot is None or spot <= 0:
            raise ProviderError(f"Moomoo returned no valid spot for {symbol}.")
        return UnderlyingQuote(symbol, spot, _quote_timestamp(row, symbol), self.name)

    def option_chain(
        self, symbol: str, start: date | None = None, end: date | None = None
    ) -> list[OptionContract]:
        start = start or date.today()
        end = end or date.today()
        ret, static = self._ctx.get_option_chain(code=symbol, start=start.isoformat(), end=end.isoformat())
        if ret != self._ret_ok:
            raise ProviderError(str(static))
        if static.empty:
            return []
        code_col = "code" if "code" in static else "symbol"
        snapshots = self._snapshot_frame(static[code_col].astype(str).tolist())
        spot = self.underlying_quote(symbol).spot
        return contracts_from_moomoo_frames(
            symbol, spot, static, snapshots, self.stale_after_seconds
        )

    def historical_prices(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        page_key = None
        while True:
            ret, data, page_key = self._ctx.request_history_kline(
                symbol, start=start.isoformat(), end=end.isoformat(),
                ktype=self._kl_type.K_DAY, max_count=1000, page_req_key=page_key,
            )
            if ret != self._ret_ok:
                raise ProviderError(str(data))
            frames.append(data)
            if page_key is None:
                break
        frame = pd.concat(frames, ignore_index=True)
        return frame.rename(columns={"time_key": "timestamp"})

    def close(self) -> None:
        self._ctx.close()
