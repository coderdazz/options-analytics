from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any, Mapping

import pandas as pd

from .contracts import GreeksQuote, OptionContract, OptionSide, UnderlyingQuote
from .provider import ProviderError
from .validation import quote_quality_flags

OCC_PATTERN = re.compile(r"^(?P<root>[A-Z0-9]{1,6})(?P<expiry>\d{6})(?P<side>[CP])(?P<strike>\d{8})$")


def decode_occ_symbol(symbol: str) -> tuple[str, date, OptionSide, float]:
    """Decode Alpaca/OCC compact option symbols such as AAPL260918C00200000."""
    match = OCC_PATTERN.fullmatch(symbol.replace(" ", "").upper())
    if match is None:
        raise ProviderError(f"Unsupported OCC option symbol: {symbol}")
    expiry = datetime.strptime(match.group("expiry"), "%y%m%d").date()
    side = OptionSide.CALL if match.group("side") == "C" else OptionSide.PUT
    strike = int(match.group("strike")) / 1000.0
    return match.group("root"), expiry, side, strike


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _timestamp(snapshot: Any) -> datetime:
    quote = _value(snapshot, "latest_quote")
    trade = _value(snapshot, "latest_trade")
    value = _value(quote, "timestamp") or _value(trade, "timestamp")
    if value is None:
        return datetime.now(timezone.utc)
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize("UTC")
    return parsed.to_pydatetime().astimezone(timezone.utc)


def contracts_from_alpaca_chain(
    underlying: str,
    underlying_spot: float,
    snapshots: Mapping[str, Any],
    feed: str,
    stale_after_seconds: int = 300,
    contract_metadata: Mapping[str, Any] | None = None,
) -> list[OptionContract]:
    """Normalize Alpaca option-chain snapshots without altering vendor IV/Greeks."""
    contracts: list[OptionContract] = []
    contract_metadata = contract_metadata or {}
    for symbol, snapshot in snapshots.items():
        try:
            _, expiry, side, strike = decode_occ_symbol(str(symbol))
        except ProviderError:
            continue
        quote = _value(snapshot, "latest_quote")
        trade = _value(snapshot, "latest_trade")
        greeks_raw = _value(snapshot, "greeks")
        metadata = contract_metadata.get(str(symbol))
        greeks = GreeksQuote(
            delta=_value(greeks_raw, "delta"), gamma=_value(greeks_raw, "gamma"),
            theta=_value(greeks_raw, "theta"), vega=_value(greeks_raw, "vega"),
            rho=_value(greeks_raw, "rho"), source=f"alpaca:{feed}",
        )
        contract = OptionContract(
            underlying=underlying, symbol=str(symbol), option_type=side, strike=strike,
            expiry=expiry, bid=_value(quote, "bid_price"), ask=_value(quote, "ask_price"),
            last=_value(trade, "price"), volume=None,
            open_interest=(int(_value(metadata, "open_interest"))
                           if _value(metadata, "open_interest") is not None else None),
            implied_volatility=_value(snapshot, "implied_volatility"), greeks=greeks,
            underlying_spot=float(underlying_spot), timestamp=_timestamp(snapshot),
            multiplier=float(_value(metadata, "size", 100) or 100),
            provider=f"alpaca:{feed}", bid_size=_value(quote, "bid_size"),
            ask_size=_value(quote, "ask_size"), feed=feed,
        )
        flags = quote_quality_flags(contract, stale_after_seconds=stale_after_seconds)
        contracts.append(OptionContract(**{
            field: getattr(contract, field) for field in contract.__dataclass_fields__
            if field != "quality_flags"
        }, quality_flags=flags))
    return contracts


class AlpacaMarketDataProvider:
    """Quote-only Alpaca provider using the official alpaca-py SDK."""

    name = "alpaca"

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        option_feed: str = "indicative",
        stock_feed: str = "iex",
        stale_after_seconds: int = 300,
    ):
        if not api_key or not secret_key:
            raise ProviderError("Alpaca API key and secret are required in environment or Streamlit secrets.")
        try:
            from alpaca.data.enums import DataFeed, OptionsFeed
            from alpaca.data.historical import OptionHistoricalDataClient, StockHistoricalDataClient
            from alpaca.trading.client import TradingClient
        except ImportError as exc:
            raise ProviderError("Install `alpaca-py` to enable Alpaca market data.") from exc
        feed_map = {"indicative": OptionsFeed.INDICATIVE, "opra": OptionsFeed.OPRA}
        stock_map = {"iex": DataFeed.IEX, "sip": DataFeed.SIP}
        if option_feed not in feed_map or stock_feed not in stock_map:
            raise ProviderError("Alpaca feeds must be indicative/opra and iex/sip.")
        self.option_feed_name = option_feed
        self.option_feed = feed_map[option_feed]
        self.stock_feed = stock_map[stock_feed]
        self.stale_after_seconds = stale_after_seconds
        self.option_client = OptionHistoricalDataClient(api_key, secret_key)
        self.stock_client = StockHistoricalDataClient(api_key, secret_key)
        self.trading_client = TradingClient(api_key, secret_key, paper=True)

    def underlying_quote(self, symbol: str) -> UnderlyingQuote:
        from alpaca.data.requests import StockLatestQuoteRequest

        request = StockLatestQuoteRequest(symbol_or_symbols=symbol, feed=self.stock_feed)
        quotes = self.stock_client.get_stock_latest_quote(request)
        quote = quotes.get(symbol)
        if quote is None:
            raise ProviderError(f"Alpaca returned no underlying quote for {symbol}.")
        bid, ask = float(quote.bid_price), float(quote.ask_price)
        spot = (bid + ask) / 2 if bid > 0 and ask >= bid else max(bid, ask)
        timestamp = pd.Timestamp(quote.timestamp)
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("UTC")
        return UnderlyingQuote(symbol, spot, timestamp.to_pydatetime(), f"alpaca:{self.stock_feed.value}")

    def option_chain(
        self, symbol: str, start: date | None = None, end: date | None = None
    ) -> list[OptionContract]:
        from alpaca.data.requests import OptionChainRequest

        request = OptionChainRequest(
            underlying_symbol=symbol,
            feed=self.option_feed,
            expiration_date_gte=start,
            expiration_date_lte=end,
        )
        snapshots = self.option_client.get_option_chain(request)
        spot = self.underlying_quote(symbol).spot
        metadata = self._option_contract_metadata(symbol, start, end)
        return contracts_from_alpaca_chain(
            symbol, spot, snapshots, self.option_feed_name, self.stale_after_seconds, metadata
        )

    def _option_contract_metadata(
        self, symbol: str, start: date | None, end: date | None
    ) -> dict[str, Any]:
        from alpaca.trading.requests import GetOptionContractsRequest

        page_token = None
        result: dict[str, Any] = {}
        while True:
            request = GetOptionContractsRequest(
                underlying_symbols=[symbol], expiration_date_gte=start,
                expiration_date_lte=end, limit=10_000, page_token=page_token,
            )
            response = self.trading_client.get_option_contracts(request)
            for contract in response.option_contracts or []:
                result[contract.symbol] = contract
            page_token = response.next_page_token
            if not page_token:
                break
        return result

    def historical_prices(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        request = StockBarsRequest(
            symbol_or_symbols=symbol, timeframe=TimeFrame.Day,
            start=datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc),
            end=datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc),
            feed=self.stock_feed,
        )
        frame = self.stock_client.get_stock_bars(request).df.reset_index()
        return frame.rename(columns={"timestamp": "timestamp"})

    def close(self) -> None:
        return None
