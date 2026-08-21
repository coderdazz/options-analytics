from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from toolkit.analytics.scenarios import IVScenario, ScenarioAssumptions, revalue_contract, scenario_grid
from toolkit.analytics.trades import trade_from_contracts
from toolkit.data.contracts import FillConvention, GreeksQuote, OptionContract, OptionSide
from toolkit.data.demo import DemoMarketDataProvider
from toolkit.data.moomoo import contracts_from_moomoo_frames
from toolkit.data.validation import quote_quality_flags


def contract(**overrides) -> OptionContract:
    values = dict(
        underlying="US.TEST", symbol="US.TEST-C-100", option_type=OptionSide.CALL,
        strike=100.0, expiry=date.today() + timedelta(days=30), bid=4.8, ask=5.2,
        last=5.0, volume=100, open_interest=500, implied_volatility=.25,
        greeks=GreeksQuote(.52, .04, -.08, .11, .03, "moomoo"), underlying_spot=100.0,
        timestamp=datetime.now(timezone.utc), provider="moomoo",
    )
    values.update(overrides)
    return OptionContract(**values)


def test_fill_conventions_are_explicit():
    c = contract()
    assert c.price_for_fill(True, FillConvention.NATURAL) == 5.2
    assert c.price_for_fill(False, FillConvention.NATURAL) == 4.8
    assert c.price_for_fill(True, FillConvention.MID) == 5.0
    assert c.price_for_fill(True, FillConvention.CONSERVATIVE) == 5.15
    assert c.price_for_fill(False, FillConvention.CONSERVATIVE) == 4.85


def test_quote_quality_flags_do_not_fill_missing_values():
    c = contract(bid=0.0, ask=1.0, open_interest=0, volume=0,
                 implied_volatility=None, greeks=GreeksQuote(source="missing"))
    flags = quote_quality_flags(c)
    assert {"zero_bid", "wide_spread", "low_oi", "low_volume", "missing_iv", "missing_greeks"} <= set(flags)
    assert c.implied_volatility is None and c.greeks.delta is None


def test_moomoo_mapping_preserves_vendor_values_and_percent_units():
    static = pd.DataFrame([{
        "code": "US.TEST240101C100000", "option_type": "CALL", "strike_price": 100.0,
        "strike_time": (date.today() + timedelta(days=30)).isoformat(), "lot_size": 100,
    }])
    snapshots = pd.DataFrame([{
        "code": "US.TEST240101C100000", "bid_price": 4.9, "ask_price": 5.1,
        "last_price": 5.0, "implied_volatility": 25.0, "delta": .51,
        "gamma": .04, "theta": -.08, "vega": .11, "rho": .03,
        "volume": 123, "open_interest": 987,
        "data_date": date.today().isoformat(), "data_time": "15:55:00",
    }])
    mapped = contracts_from_moomoo_frames("US.TEST", 100.0, static, snapshots, stale_after_seconds=10**9)
    assert len(mapped) == 1
    option = mapped[0]
    assert option.bid == 4.9 and option.ask == 5.1
    assert option.implied_volatility == .25
    assert option.greeks.delta == .51 and option.greeks.source == "moomoo"
    assert option.open_interest == 987


def test_scenario_is_anchored_to_market_midpoint_at_origin():
    c = contract(bid=7.8, ask=8.2, last=8.0)
    valued = revalue_contract(c, ScenarioAssumptions())
    assert abs(valued["price"] - 8.0) < 1e-10


def test_vendor_greeks_are_used_for_current_trade_display():
    c = contract()
    trade = trade_from_contracts("US.TEST", [(c, 2)], FillConvention.NATURAL)
    greeks = trade.vendor_greeks()
    assert greeks["delta"] == 104.0
    assert greeks["vega"] == 22.0


def test_vertical_bounds_and_scenario_grid():
    provider = DemoMarketDataProvider(100)
    chain = provider.option_chain("US.TEST")
    expiry = sorted({c.expiry for c in chain})[1]
    calls = sorted([c for c in chain if c.expiry == expiry and c.option_type == OptionSide.CALL], key=lambda c: c.strike)
    long = min(calls, key=lambda c: abs(c.strike - 95))
    short = min(calls, key=lambda c: abs(c.strike - 105))
    trade = trade_from_contracts("US.TEST", [(long, 1), (short, -1)], FillConvention.NATURAL)
    stats = trade.expiry_statistics()
    width = (short.strike - long.strike) * 100
    assert 0 <= stats["max_loss"] <= max(width, trade.net_debit)
    assert stats["max_profit"] is not None
    grid = scenario_grid(trade, [-.2, 0, .2], [0, 5], [-.05, 0, .05],
                         ScenarioAssumptions(iv_scenario=IVScenario.STICKY_DELTA))
    assert len(grid) == 18
    assert set(["pnl", "delta", "gamma", "theta", "vega"]) <= set(grid.columns)

