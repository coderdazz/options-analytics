from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import pandas as pd

from ..data.contracts import OptionContract
from ..pricing import black_scholes
from .trades import Trade


class IVScenario(StrEnum):
    PARALLEL = "Parallel shift"
    STICKY_STRIKE = "Sticky strike"
    STICKY_DELTA = "Sticky delta (local-skew approximation)"
    MEAN_REVERTING = "Mean reverting"
    USER_DEFINED = "User-defined shift"


@dataclass(frozen=True, slots=True)
class ScenarioAssumptions:
    days_forward: int = 0
    spot_return: float = 0.0
    iv_shift: float = 0.0
    iv_scenario: IVScenario = IVScenario.PARALLEL
    risk_free_rate: float = 0.04
    dividend_yield: float = 0.0
    long_run_iv: float = 0.25
    mean_reversion_speed: float = 3.0
    local_skew_slope: float = -0.10


def scenario_iv(contract: OptionContract, scenario_spot: float, assumptions: ScenarioAssumptions) -> float:
    base = contract.implied_volatility
    if base is None:
        raise ValueError(f"{contract.symbol} has no vendor implied volatility.")
    if assumptions.iv_scenario in {IVScenario.PARALLEL, IVScenario.STICKY_STRIKE, IVScenario.USER_DEFINED}:
        value = base + assumptions.iv_shift
    elif assumptions.iv_scenario == IVScenario.STICKY_DELTA:
        old_m = np.log(contract.strike / contract.underlying_spot)
        new_m = np.log(contract.strike / scenario_spot)
        value = base + assumptions.local_skew_slope * (new_m - old_m) + assumptions.iv_shift
    else:
        years = max(assumptions.days_forward / 365.0, 0.0)
        reverted = assumptions.long_run_iv + (base - assumptions.long_run_iv) * np.exp(
            -assumptions.mean_reversion_speed * years
        )
        value = reverted + assumptions.iv_shift
    return float(max(value, 0.0001))


def _current_mark(contract: OptionContract) -> float:
    mark = contract.mid_price if contract.mid_price is not None else contract.last
    if mark is None:
        raise ValueError(f"{contract.symbol} has no current mark.")
    return float(mark)


def revalue_contract(contract: OptionContract, assumptions: ScenarioAssumptions) -> dict[str, float]:
    scenario_spot = max(0.01, contract.underlying_spot * (1 + assumptions.spot_return))
    current_t = max(contract.dte / 365.0, 1 / (365 * 24))
    scenario_t = max((contract.dte - assumptions.days_forward) / 365.0, 0.0)
    base_iv = contract.implied_volatility
    if base_iv is None:
        raise ValueError(f"{contract.symbol} has no provider IV for scenario repricing.")
    new_iv = scenario_iv(contract, scenario_spot, assumptions)
    model_now = black_scholes(
        contract.underlying_spot, contract.strike, current_t, assumptions.risk_free_rate,
        base_iv, contract.option_type.value, assumptions.dividend_yield,
    )
    model_scenario = black_scholes(
        scenario_spot, contract.strike, scenario_t, assumptions.risk_free_rate,
        new_iv, contract.option_type.value, assumptions.dividend_yield,
    )
    # Anchor the scenario to the observed market rather than replacing the vendor
    # quote with a theoretical value at t=0.
    anchored = _current_mark(contract) + (model_scenario.price - model_now.price)
    intrinsic = (max(scenario_spot - contract.strike, 0.0)
                 if contract.option_type.value == "call"
                 else max(contract.strike - scenario_spot, 0.0))
    price = max(intrinsic, anchored, 0.0)
    return {
        "price": float(price), "model_price": model_scenario.price,
        "spot": scenario_spot, "iv": new_iv, "delta": model_scenario.delta,
        "gamma": model_scenario.gamma, "theta": model_scenario.theta,
        "vega": model_scenario.vega, "rho": model_scenario.rho,
    }


def scenario_trade(trade: Trade, assumptions: ScenarioAssumptions) -> dict[str, float]:
    market_value = delta = gamma = theta = vega = rho = 0.0
    for leg in trade.legs:
        valued = revalue_contract(leg.contract, assumptions)
        factor = leg.quantity * leg.contract.multiplier
        market_value += valued["price"] * factor
        delta += valued["delta"] * factor
        gamma += valued["gamma"] * factor
        theta += valued["theta"] * factor
        vega += valued["vega"] * factor
        rho += valued["rho"] * factor
    return {
        "spot_return": assumptions.spot_return, "days_forward": assumptions.days_forward,
        "iv_shift": assumptions.iv_shift, "market_value": market_value,
        "pnl": market_value - trade.net_debit, "delta": delta, "gamma": gamma,
        "theta": theta, "vega": vega, "rho": rho,
    }


def scenario_grid(
    trade: Trade,
    spot_returns: list[float] | np.ndarray,
    days_forward: list[int] | np.ndarray,
    iv_shifts: list[float] | np.ndarray,
    base_assumptions: ScenarioAssumptions,
) -> pd.DataFrame:
    rows = []
    for day in days_forward:
        for shift in iv_shifts:
            for spot_return in spot_returns:
                assumptions = ScenarioAssumptions(
                    days_forward=int(day), spot_return=float(spot_return), iv_shift=float(shift),
                    iv_scenario=base_assumptions.iv_scenario,
                    risk_free_rate=base_assumptions.risk_free_rate,
                    dividend_yield=base_assumptions.dividend_yield,
                    long_run_iv=base_assumptions.long_run_iv,
                    mean_reversion_speed=base_assumptions.mean_reversion_speed,
                    local_skew_slope=base_assumptions.local_skew_slope,
                )
                rows.append(scenario_trade(trade, assumptions))
    return pd.DataFrame(rows)
