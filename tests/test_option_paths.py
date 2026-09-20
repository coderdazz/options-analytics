from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from toolkit.analytics.paths import (
    PathIVMode,
    calibrate_option_model,
    revalue_option,
    revalue_path,
    spot_sweep,
    time_sweep,
)
from toolkit.data.contracts import GreeksQuote, OptionContract, OptionSide
from toolkit.pricing import black_scholes


def contract_at_vol(volatility: float = 0.32, **overrides) -> OptionContract:
    dte = 60
    spot = 100.0
    strike = 105.0
    price = black_scholes(spot, strike, dte / 365.0, 0.04, volatility, "call").price
    values = dict(
        underlying="TEST",
        symbol="TEST-PATH-CALL",
        option_type=OptionSide.CALL,
        strike=strike,
        expiry=date.today() + timedelta(days=dte),
        bid=price,
        ask=price,
        last=price,
        volume=100,
        open_interest=500,
        implied_volatility=0.25,
        greeks=GreeksQuote(0.45, 0.03, -0.05, 0.12, 0.02, "moomoo"),
        underlying_spot=spot,
        timestamp=datetime.now(timezone.utc),
        provider="moomoo",
    )
    values.update(overrides)
    return OptionContract(**values)


def test_calibration_recovers_market_implied_vol_and_price():
    contract = contract_at_vol(0.32)
    model = calibrate_option_model(contract, risk_free_rate=0.04)

    assert model.calibration_method == "Market-implied volatility"
    assert model.base_iv == pytest.approx(0.32, abs=1e-8)
    assert model.calibrated_model_price == pytest.approx(model.market_mark, abs=1e-9)
    assert model.calibration_error == pytest.approx(0.0, abs=1e-9)


def test_spot_sweep_is_anchored_and_returns_finite_greek_curves():
    model = calibrate_option_model(contract_at_vol(), 0.04)
    frame = spot_sweep(model, [90.0, 100.0, 110.0], [0, 1, 3, 5])

    assert len(frame) == 12
    origin = frame[(frame.day == 0) & (frame.spot == 100.0)].iloc[0]
    assert origin.price == pytest.approx(model.market_mark, abs=1e-9)
    assert np.isfinite(frame[["price", "delta", "gamma", "vega", "theta"]]).all().all()
    assert set(frame.day) == {0, 1, 3, 5}


def test_time_sweep_reaches_intrinsic_at_zero_dte():
    model = calibrate_option_model(contract_at_vol(), 0.04)
    frame = time_sweep(model, [100.0, 110.0], [0, 10, 60])

    expired_at_110 = frame[(frame.remaining_dte == 0) & (frame.spot == 110.0)].iloc[0]
    assert expired_at_110.price == pytest.approx(5.0)
    assert expired_at_110.delta == pytest.approx(1.0)
    assert expired_at_110.gamma == 0.0


def test_custom_iv_path_controls_revaluation_and_scales_mtm_pnl():
    model = calibrate_option_model(contract_at_vol(), 0.04)
    path = pd.DataFrame({
        "day": [0, 1, 3],
        "spot": [100.0, 102.0, 105.0],
        "iv": [model.base_iv, 0.35, 0.40],
    })
    result = revalue_path(model, path, quantity=2, mode=PathIVMode.CUSTOM)

    assert result.iv.tolist() == pytest.approx([model.base_iv, 0.35, 0.40])
    assert result.mtm_pnl.iloc[0] == pytest.approx(0.0, abs=1e-8)
    expected = (result.price.iloc[-1] - model.market_mark) * 2 * 100
    assert result.mtm_pnl.iloc[-1] == pytest.approx(expected)
    assert result.delta_exposure.iloc[-1] == pytest.approx(result.delta.iloc[-1] * 200)


def test_sticky_strike_matches_constant_for_one_fixed_contract():
    model = calibrate_option_model(contract_at_vol(), 0.04)
    constant = revalue_option(model, 110.0, 5, PathIVMode.CONSTANT)
    sticky = revalue_option(model, 110.0, 5, PathIVMode.STICKY_STRIKE)
    assert constant == sticky | {"iv_mode": PathIVMode.CONSTANT.value}


def test_sticky_delta_changes_iv_with_moneyness_and_parallel_shift_is_explicit():
    model = calibrate_option_model(contract_at_vol(), 0.04)
    sticky = revalue_option(
        model, 110.0, 1, PathIVMode.STICKY_DELTA, sticky_delta_slope=-0.10
    )
    shifted = revalue_option(
        model, 100.0, 1, PathIVMode.PARALLEL, parallel_shift=0.05
    )
    assert sticky["iv"] > model.base_iv
    assert shifted["iv"] == pytest.approx(model.base_iv + 0.05)


def test_invalid_european_mark_uses_offset_that_vanishes_at_expiry():
    invalid = contract_at_vol(bid=110.0, ask=110.0, last=110.0)
    model = calibrate_option_model(invalid, 0.04)
    assert model.calibration_method == "Vendor IV plus decaying market-price offset"
    assert revalue_option(model, 100.0, 0)["price"] == pytest.approx(110.0)
    assert revalue_option(model, 110.0, invalid.dte)["price"] == pytest.approx(5.0)


def test_custom_path_validation_rejects_duplicate_days():
    model = calibrate_option_model(contract_at_vol(), 0.04)
    path = pd.DataFrame({"day": [0, 0], "spot": [100.0, 101.0], "iv": [0.3, 0.3]})
    with pytest.raises(ValueError, match="unique"):
        revalue_path(model, path, mode=PathIVMode.CUSTOM)


def test_custom_path_validation_rejects_empty_path():
    model = calibrate_option_model(contract_at_vol(), 0.04)
    with pytest.raises(ValueError, match="at least one"):
        revalue_path(model, pd.DataFrame(columns=["day", "spot"]))
