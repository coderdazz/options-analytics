from datetime import date, timedelta

import numpy as np
import pytest

from toolkit.analytics.scenarios import delta_gamma_price, delta_gamma_trade_curve
from toolkit.analytics.trades import trade_from_contracts
from toolkit.data.contracts import FillConvention
from toolkit.data.manual import build_manual_option


def manual_contract(**overrides):
    values = dict(
        underlying="TEST",
        symbol="TEST-MANUAL-CALL",
        option_type="call",
        strike=100.0,
        expiry=date.today() + timedelta(days=30),
        underlying_spot=100.0,
        bid=7.0,
        ask=7.0,
        last=7.0,
        implied_volatility=0.30,
        delta=0.20,
        gamma=0.00034,
        theta=-0.03,
        vega=0.10,
        rho=0.02,
        multiplier=100.0,
    )
    values.update(overrides)
    return build_manual_option(**values)


def test_manual_contract_preserves_percent_and_vendor_greeks():
    option = manual_contract()
    assert option.provider == "manual"
    assert option.implied_volatility == 0.30
    assert option.greeks.delta == 0.20
    assert option.greeks.gamma == 0.00034
    assert option.mid_price == 7.0


def test_delta_gamma_example_scales_100_contracts_by_multiplier():
    option = manual_contract()
    assert delta_gamma_price(option, 101.0) == pytest.approx(7.20017)
    trade = trade_from_contracts("TEST", [(option, 100)], FillConvention.NATURAL)
    assert trade.net_debit == 70_000.0
    point = delta_gamma_trade_curve(trade, np.array([0.01])).iloc[0]
    assert point.market_value == pytest.approx(72_001.70)
    assert point.pnl == pytest.approx(2_001.70)


def test_manual_contract_rejects_crossed_market():
    with pytest.raises(ValueError, match="Ask"):
        manual_contract(bid=7.2, ask=7.0)


def test_zero_bid_and_ask_fall_back_to_entered_mark():
    option = manual_contract(bid=0.0, ask=0.0, last=7.0)
    assert option.mid_price is None
    assert delta_gamma_price(option, 100.0) == 7.0
