from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd

from toolkit.data.alpaca import contracts_from_alpaca_chain, decode_occ_symbol
from toolkit.data.contracts import OptionSide
from toolkit.data.lake import MarketDataLake


def test_occ_symbol_decode():
    root, expiry, side, strike = decode_occ_symbol("AAPL260918C00200000")
    assert root == "AAPL"
    assert expiry == date(2026, 9, 18)
    assert side == OptionSide.CALL
    assert strike == 200.0


def test_alpaca_snapshot_mapping_preserves_vendor_fields():
    timestamp = datetime.now(timezone.utc)
    snapshot = SimpleNamespace(
        latest_quote=SimpleNamespace(bid_price=7.4, ask_price=7.6, bid_size=12, ask_size=9, timestamp=timestamp),
        latest_trade=SimpleNamespace(price=7.5, timestamp=timestamp),
        implied_volatility=.284,
        greeks=SimpleNamespace(delta=.61, gamma=.031, theta=-.12, vega=.18, rho=.04),
    )
    metadata = {"AAPL260918C00200000": SimpleNamespace(open_interest="1234", size="100")}
    contracts = contracts_from_alpaca_chain(
        "AAPL", 205.0, {"AAPL260918C00200000": snapshot}, "indicative",
        stale_after_seconds=3600, contract_metadata=metadata,
    )
    assert len(contracts) == 1
    option = contracts[0]
    assert option.bid == 7.4 and option.ask == 7.6
    assert option.bid_size == 12 and option.ask_size == 9
    assert option.implied_volatility == .284
    assert option.greeks.delta == .61
    assert option.open_interest == 1234
    assert "indicative_not_opra" in option.quality_flags


def test_parquet_market_lake_appends_microbatch(tmp_path):
    timestamp = datetime.now(timezone.utc)
    snapshot = SimpleNamespace(
        latest_quote=SimpleNamespace(bid_price=2.0, ask_price=2.2, bid_size=3, ask_size=4, timestamp=timestamp),
        latest_trade=SimpleNamespace(price=2.1, timestamp=timestamp),
        implied_volatility=.30,
        greeks=SimpleNamespace(delta=.40, gamma=.02, theta=-.05, vega=.10, rho=.02),
    )
    contracts = contracts_from_alpaca_chain(
        "AAPL", 205.0, {"AAPL260918C00220000": snapshot}, "indicative",
        stale_after_seconds=3600,
    )
    path = MarketDataLake(tmp_path).append_option_snapshot(contracts)
    assert path is not None and path.exists()
    frame = pd.read_parquet(path)
    assert len(frame) == 1
    assert frame.iloc[0].provider == "alpaca:indicative"
    assert frame.iloc[0].underlying == "AAPL"

