from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd


def demo_prices(symbol: str = "DEMO", start: float = 100.0, days: int = 252, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
    returns = rng.normal(0.0003, 0.018, days)
    close = start * np.exp(np.cumsum(returns))
    return pd.DataFrame({"timestamp": dates, "close": close, "volume": rng.integers(1_000_000, 8_000_000, days)})


class MoomooMarketData:
    """Read-only Moomoo OpenD adapter. No trade context is created."""

    def __init__(self, host: str = "127.0.0.1", port: int = 11111):
        try:
            from moomoo import KLType, OpenQuoteContext, RET_OK, SubType
        except ImportError as exc:
            raise RuntimeError("Install `moomoo-api` to enable live data.") from exc
        self.api = {"KLType": KLType, "RET_OK": RET_OK, "SubType": SubType}
        self.ctx = OpenQuoteContext(host=host, port=port)

    def close(self) -> None:
        self.ctx.close()

    def snapshot(self, codes: list[str]) -> pd.DataFrame:
        ret, data = self.ctx.get_market_snapshot(codes)
        if ret != self.api["RET_OK"]:
            raise RuntimeError(str(data))
        return data

    def history(self, code: str, start: str, end: str) -> pd.DataFrame:
        frames, key = [], None
        while True:
            ret, data, key = self.ctx.request_history_kline(
                code, start=start, end=end, ktype=self.api["KLType"].K_DAY,
                max_count=1000, page_req_key=key,
            )
            if ret != self.api["RET_OK"]:
                raise RuntimeError(str(data))
            frames.append(data)
            if key is None:
                break
        frame = pd.concat(frames, ignore_index=True)
        return frame.rename(columns={"time_key": "timestamp"})

    def option_chain(self, underlying: str, start: str, end: str) -> pd.DataFrame:
        ret, static = self.ctx.get_option_chain(code=underlying, start=start, end=end)
        if ret != self.api["RET_OK"]:
            raise RuntimeError(str(static))
        if static.empty:
            return static
        codes = static["code"].tolist()
        snapshots = []
        for i in range(0, len(codes), 200):
            snapshots.append(self.snapshot(codes[i:i+200]))
        quotes = pd.concat(snapshots, ignore_index=True)
        merged = static.merge(quotes, on="code", how="left", suffixes=("", "_quote"))
        rename = {
            "code": "symbol", "strike_price": "strike", "option_type": "option_type",
            "option_implied_volatility": "iv", "option_open_interest": "open_interest",
            "last_price": "last", "bid_price": "bid", "ask_price": "ask", "volume": "volume",
        }
        merged = merged.rename(columns=rename)
        if "iv" in merged:
            merged["iv"] = pd.to_numeric(merged["iv"], errors="coerce") / 100.0
        if "strike_time" in merged:
            merged["dte"] = (pd.to_datetime(merged["strike_time"]) - pd.Timestamp.today().normalize()).dt.days
        return merged


def normalize_uploaded_prices(file) -> pd.DataFrame:
    frame = pd.read_csv(file)
    frame.columns = [str(c).strip().lower() for c in frame.columns]
    aliases = {"date": "timestamp", "datetime": "timestamp", "adj close": "close", "adj_close": "close"}
    frame = frame.rename(columns={k: v for k, v in aliases.items() if k in frame.columns})
    if not {"timestamp", "close"}.issubset(frame.columns):
        raise ValueError("CSV must include Date/Timestamp and Close columns.")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    return frame.dropna(subset=["timestamp", "close"]).sort_values("timestamp")
