from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..data.contracts import FillConvention, OptionContract, OptionSide


@dataclass(frozen=True, slots=True)
class TradeLeg:
    contract: OptionContract
    quantity: int
    entry_price: float

    @property
    def is_buy(self) -> bool:
        return self.quantity > 0

    @property
    def cash_risk(self) -> float:
        return abs(self.quantity * self.entry_price * self.contract.multiplier)


@dataclass(slots=True)
class Trade:
    underlying: str
    legs: list[TradeLeg] = field(default_factory=list)
    name: str = "Custom strategy"
    fill_convention: FillConvention = FillConvention.CONSERVATIVE

    def __post_init__(self) -> None:
        if any(leg.contract.underlying != self.underlying for leg in self.legs):
            raise ValueError("Every leg must have the same underlying.")

    @property
    def net_debit(self) -> float:
        """Positive is debit paid; negative is credit received."""
        return float(sum(leg.quantity * leg.entry_price * leg.contract.multiplier for leg in self.legs))

    @property
    def current_mid_value(self) -> float:
        value = 0.0
        for leg in self.legs:
            mark = leg.contract.mid_price
            if mark is None:
                mark = leg.contract.last
            if mark is None:
                raise ValueError(f"{leg.contract.symbol} has no current mark.")
            value += leg.quantity * mark * leg.contract.multiplier
        return float(value)

    @property
    def current_pnl(self) -> float:
        return self.current_mid_value - self.net_debit

    def vendor_greeks(self) -> dict[str, float | None]:
        values: dict[str, float | None] = {}
        for name in ("delta", "gamma", "theta", "vega", "rho"):
            components = []
            for leg in self.legs:
                value = getattr(leg.contract.greeks, name)
                if value is None:
                    components = []
                    break
                components.append(leg.quantity * leg.contract.multiplier * value)
            values[name] = float(sum(components)) if components else None
        return values

    def expiry_payoff(self, spots: np.ndarray) -> np.ndarray:
        payoff = np.zeros_like(spots, dtype=float)
        for leg in self.legs:
            contract = leg.contract
            intrinsic = (np.maximum(spots - contract.strike, 0.0)
                         if contract.option_type == OptionSide.CALL
                         else np.maximum(contract.strike - spots, 0.0))
            payoff += leg.quantity * contract.multiplier * intrinsic
        return payoff - self.net_debit

    def expiry_statistics(self) -> dict[str, float | list[float] | None]:
        if not self.legs:
            return {"max_profit": None, "max_loss": None, "breakevens": []}
        expiries = {leg.contract.expiry for leg in self.legs}
        if len(expiries) > 1:
            return {"max_profit": None, "max_loss": None, "breakevens": [], "multi_expiry": True}
        strikes = [leg.contract.strike for leg in self.legs]
        spot = self.legs[0].contract.underlying_spot
        upper = max(max(strikes) * 3, spot * 3)
        grid = np.linspace(0.0, upper, 20_001)
        pnl = self.expiry_payoff(grid)
        roots: list[float] = []
        sign_change = np.where(np.signbit(pnl[:-1]) != np.signbit(pnl[1:]))[0]
        for idx in sign_change:
            x0, x1 = grid[idx], grid[idx + 1]
            y0, y1 = pnl[idx], pnl[idx + 1]
            roots.append(float(x0 - y0 * (x1 - x0) / (y1 - y0)))
        call_slope = sum(leg.quantity * leg.contract.multiplier
                         for leg in self.legs if leg.contract.option_type == OptionSide.CALL)
        max_profit = None if call_slope > 0 else float(np.max(pnl))
        max_loss = None if call_slope < 0 else float(max(0.0, -np.min(pnl)))
        return {"max_profit": max_profit, "max_loss": max_loss,
                "breakevens": sorted(set(round(x, 4) for x in roots)), "multi_expiry": False}

    def legs_frame(self) -> pd.DataFrame:
        return pd.DataFrame([{
            "side": "BUY" if leg.is_buy else "SELL", "quantity": abs(leg.quantity),
            "symbol": leg.contract.symbol, "type": leg.contract.option_type.value,
            "expiry": leg.contract.expiry, "strike": leg.contract.strike,
            "bid": leg.contract.bid, "ask": leg.contract.ask, "mid": leg.contract.mid_price,
            "entry_price": leg.entry_price, "iv": leg.contract.implied_volatility,
            "delta": leg.contract.greeks.delta, "quality": ", ".join(leg.contract.quality_flags) or "OK",
        } for leg in self.legs])


def trade_from_contracts(
    underlying: str,
    selections: list[tuple[OptionContract, int]],
    fill_convention: FillConvention = FillConvention.CONSERVATIVE,
    improvement_fraction: float = 0.25,
    name: str = "Custom strategy",
) -> Trade:
    legs = [TradeLeg(
        contract=contract, quantity=int(quantity),
        entry_price=contract.price_for_fill(quantity > 0, fill_convention, improvement_fraction),
    ) for contract, quantity in selections if quantity != 0]
    return Trade(underlying, legs, name, fill_convention)
