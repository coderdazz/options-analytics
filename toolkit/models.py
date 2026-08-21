from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal

InstrumentType = Literal["equity", "option", "cash"]
OptionType = Literal["call", "put"]


@dataclass(slots=True)
class Position:
    symbol: str
    instrument_type: InstrumentType
    quantity: float
    entry_price: float
    current_price: float | None = None
    currency: str = "USD"
    option_type: OptionType | None = None
    strike: float | None = None
    expiry: date | None = None
    implied_vol: float | None = None
    underlying_price: float | None = None
    multiplier: float = 1.0
    interest_rate: float = 0.04
    dividend_yield: float = 0.0
    notes: str = ""

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.entry_price * self.multiplier

    def to_record(self) -> dict:
        row = asdict(self)
        row["expiry"] = self.expiry.isoformat() if self.expiry else None
        return row

    @classmethod
    def from_record(cls, row: dict) -> "Position":
        clean = dict(row)
        clean.pop("id", None)
        clean.pop("portfolio_id", None)
        clean.pop("created_at", None)
        if clean.get("expiry"):
            clean["expiry"] = date.fromisoformat(str(clean["expiry"]))
        return cls(**{k: v for k, v in clean.items() if k in cls.__dataclass_fields__})

