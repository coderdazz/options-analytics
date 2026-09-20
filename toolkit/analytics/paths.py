from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from ..data.contracts import OptionContract
from ..pricing import black_scholes, implied_volatility


class PathIVMode(StrEnum):
    CONSTANT = "Constant IV"
    PARALLEL = "Parallel IV shift"
    STICKY_STRIKE = "Sticky strike"
    STICKY_DELTA = "Sticky delta (local-skew approximation)"
    CUSTOM = "Custom user-entered IV path"


@dataclass(frozen=True, slots=True)
class CalibratedOptionModel:
    """A small, inspectable model anchored to one observed option market."""

    contract: OptionContract
    market_mark: float
    vendor_iv: float | None
    base_iv: float
    vendor_model_price: float | None
    calibrated_model_price: float
    price_offset: float
    calibration_method: str
    calibration_error: float
    risk_free_rate: float
    dividend_yield: float

    @property
    def current_time_years(self) -> float:
        return max(self.contract.dte / 365.0, 1.0 / (365.0 * 24.0))


def market_mark(contract: OptionContract) -> float:
    mid = contract.mid_price
    if mid is not None and isfinite(mid) and mid > 0:
        return float(mid)
    if contract.last is not None and isfinite(contract.last) and contract.last >= 0:
        return float(contract.last)
    raise ValueError(f"{contract.symbol} has no usable positive midpoint or last price.")


def calibrate_option_model(
    contract: OptionContract,
    risk_free_rate: float = 0.04,
    dividend_yield: float = 0.0,
) -> CalibratedOptionModel:
    """Calibrate Black–Scholes to the observed mark, with a transparent fallback.

    The preferred calibration solves for an implied volatility that reproduces
    the market mark. If a European implied-volatility solution does not exist,
    the vendor IV is retained and today's price difference is used as an
    additive offset that decays to zero at expiry.
    """
    mark = market_mark(contract)
    current_t = max(contract.dte / 365.0, 1.0 / (365.0 * 24.0))
    vendor_price: float | None = None
    if contract.implied_volatility is not None and contract.implied_volatility > 0:
        vendor_price = black_scholes(
            contract.underlying_spot,
            contract.strike,
            current_t,
            risk_free_rate,
            contract.implied_volatility,
            contract.option_type.value,
            dividend_yield,
        ).price

    try:
        calibrated_iv = implied_volatility(
            mark,
            contract.underlying_spot,
            contract.strike,
            current_t,
            risk_free_rate,
            contract.option_type.value,
            dividend_yield,
        )
        calibrated = black_scholes(
            contract.underlying_spot,
            contract.strike,
            current_t,
            risk_free_rate,
            calibrated_iv,
            contract.option_type.value,
            dividend_yield,
        ).price
        price_offset = mark - calibrated
        method = "Market-implied volatility"
    except ValueError:
        if contract.implied_volatility is None or contract.implied_volatility <= 0:
            raise ValueError(
                f"{contract.symbol} cannot be calibrated: the market mark has no European "
                "implied-volatility solution and no positive vendor IV is available."
            )
        calibrated_iv = float(contract.implied_volatility)
        calibrated = float(vendor_price)
        price_offset = mark - calibrated
        method = "Vendor IV plus decaying market-price offset"

    anchored_price = max(contract.intrinsic_value, calibrated + price_offset, 0.0)
    return CalibratedOptionModel(
        contract=contract,
        market_mark=mark,
        vendor_iv=contract.implied_volatility,
        base_iv=float(calibrated_iv),
        vendor_model_price=vendor_price,
        calibrated_model_price=float(anchored_price),
        price_offset=float(price_offset),
        calibration_method=method,
        calibration_error=float(anchored_price - mark),
        risk_free_rate=float(risk_free_rate),
        dividend_yield=float(dividend_yield),
    )


def _custom_iv_for_day(custom_iv_path: Mapping[int, float] | None, day: int) -> float:
    if not custom_iv_path:
        raise ValueError("Custom IV mode requires at least one day/IV observation.")
    points = sorted((int(key), float(value)) for key, value in custom_iv_path.items())
    days = np.asarray([point[0] for point in points], dtype=float)
    ivs = np.asarray([point[1] for point in points], dtype=float)
    if np.any(days < 0) or np.any(~np.isfinite(ivs)) or np.any(ivs <= 0):
        raise ValueError("Custom IV days must be non-negative and IV values must be positive.")
    return float(np.interp(float(day), days, ivs))


def scenario_iv(
    model: CalibratedOptionModel,
    spot: float,
    day: int,
    mode: PathIVMode,
    parallel_shift: float = 0.0,
    sticky_delta_slope: float = -0.10,
    custom_iv_path: Mapping[int, float] | None = None,
) -> float:
    base = model.base_iv
    if mode in {PathIVMode.CONSTANT, PathIVMode.STICKY_STRIKE}:
        value = base
    elif mode == PathIVMode.PARALLEL:
        value = base + float(parallel_shift)
    elif mode == PathIVMode.STICKY_DELTA:
        old_moneyness = np.log(model.contract.strike / model.contract.underlying_spot)
        new_moneyness = np.log(model.contract.strike / float(spot))
        value = base + float(sticky_delta_slope) * (new_moneyness - old_moneyness)
    else:
        value = _custom_iv_for_day(custom_iv_path, int(day))
    return float(max(value, 0.0001))


def revalue_option(
    model: CalibratedOptionModel,
    spot: float,
    day: int,
    mode: PathIVMode = PathIVMode.CONSTANT,
    parallel_shift: float = 0.0,
    sticky_delta_slope: float = -0.10,
    custom_iv_path: Mapping[int, float] | None = None,
) -> dict[str, float | int | str]:
    spot = float(spot)
    day = int(day)
    if not isfinite(spot) or spot <= 0:
        raise ValueError("Every path spot must be a positive finite number.")
    if day < 0:
        raise ValueError("Path days cannot be negative.")
    remaining_dte = max(model.contract.dte - day, 0)
    remaining_t = max(model.current_time_years - day / 365.0, 0.0)
    iv = scenario_iv(
        model, spot, day, mode, parallel_shift, sticky_delta_slope, custom_iv_path
    )
    greeks = black_scholes(
        spot,
        model.contract.strike,
        remaining_t,
        model.risk_free_rate,
        iv,
        model.contract.option_type.value,
        model.dividend_yield,
    )
    offset_weight = remaining_t / model.current_time_years
    intrinsic = (
        max(spot - model.contract.strike, 0.0)
        if model.contract.option_type.value == "call"
        else max(model.contract.strike - spot, 0.0)
    )
    price = max(intrinsic, greeks.price + model.price_offset * offset_weight, 0.0)
    return {
        "day": day,
        "remaining_dte": remaining_dte,
        "spot": spot,
        "iv": iv,
        "price": float(price),
        "delta": greeks.delta,
        "gamma": greeks.gamma,
        "vega": greeks.vega,
        "theta": greeks.theta,
        "rho": greeks.rho,
        "iv_mode": mode.value,
    }


def spot_sweep(
    model: CalibratedOptionModel,
    spots: Sequence[float] | np.ndarray,
    days_forward: Sequence[int] = (0, 1, 3, 5),
    mode: PathIVMode = PathIVMode.CONSTANT,
    parallel_shift: float = 0.0,
    sticky_delta_slope: float = -0.10,
    custom_iv_path: Mapping[int, float] | None = None,
) -> pd.DataFrame:
    rows = [
        revalue_option(
            model, float(spot), int(day), mode, parallel_shift,
            sticky_delta_slope, custom_iv_path,
        )
        for day in days_forward
        for spot in spots
    ]
    return pd.DataFrame(rows)


def time_sweep(
    model: CalibratedOptionModel,
    spots: Sequence[float] | np.ndarray,
    remaining_dtes: Sequence[int] | None = None,
    mode: PathIVMode = PathIVMode.CONSTANT,
    parallel_shift: float = 0.0,
    sticky_delta_slope: float = -0.10,
    custom_iv_path: Mapping[int, float] | None = None,
) -> pd.DataFrame:
    if remaining_dtes is None:
        remaining_dtes = range(0, model.contract.dte + 1)
    rows: list[dict[str, float | int | str]] = []
    for spot in spots:
        for remaining_dte in remaining_dtes:
            remaining_dte = int(remaining_dte)
            if remaining_dte < 0 or remaining_dte > model.contract.dte:
                raise ValueError("Remaining DTE must lie between zero and the current DTE.")
            day = model.contract.dte - remaining_dte
            rows.append(
                revalue_option(
                    model, float(spot), day, mode, parallel_shift,
                    sticky_delta_slope, custom_iv_path,
                )
            )
    return pd.DataFrame(rows)


def revalue_path(
    model: CalibratedOptionModel,
    path: pd.DataFrame,
    quantity: int = 1,
    mode: PathIVMode = PathIVMode.CONSTANT,
    parallel_shift: float = 0.0,
    sticky_delta_slope: float = -0.10,
) -> pd.DataFrame:
    if not {"day", "spot"}.issubset(path.columns):
        raise ValueError("A custom path needs `day` and `spot` columns.")
    clean = path.copy()
    clean["day"] = pd.to_numeric(clean["day"], errors="coerce")
    clean["spot"] = pd.to_numeric(clean["spot"], errors="coerce")
    if clean.empty:
        raise ValueError("Add at least one observation to the custom path.")
    if clean[["day", "spot"]].isna().any().any():
        raise ValueError("Path days and spots must be numeric.")
    if (clean.day < 0).any() or (clean.day % 1 != 0).any():
        raise ValueError("Path days must be non-negative whole numbers.")
    if clean.day.duplicated().any():
        raise ValueError("Each custom path day must be unique.")
    if (clean.spot <= 0).any():
        raise ValueError("Every path spot must be positive.")
    clean = clean.sort_values("day").reset_index(drop=True)

    custom_iv_path: dict[int, float] | None = None
    if mode == PathIVMode.CUSTOM:
        if "iv" not in clean:
            raise ValueError("Custom IV mode requires an `iv` column.")
        clean["iv"] = pd.to_numeric(clean["iv"], errors="coerce")
        if clean.iv.isna().any() or (clean.iv <= 0).any():
            raise ValueError("Every custom IV value must be positive and numeric.")
        custom_iv_path = {int(row.day): float(row.iv) for row in clean.itertuples()}

    rows = [
        revalue_option(
            model,
            float(row.spot),
            int(row.day),
            mode,
            parallel_shift,
            sticky_delta_slope,
            custom_iv_path,
        )
        for row in clean.itertuples()
    ]
    result = pd.DataFrame(rows)
    factor = int(quantity) * model.contract.multiplier
    result["mtm_pnl"] = (result.price - model.market_mark) * factor
    first_change = result.price.iloc[0] - model.market_mark
    result["daily_pnl"] = result.price.diff().fillna(first_change) * factor
    result["delta_exposure"] = result.delta * factor
    result["gamma_exposure"] = result.gamma * factor
    result["vega_exposure"] = result.vega * factor
    result["theta_exposure"] = result.theta * factor
    return result
