from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

import pandas as pd

from .contracts import OptionContract, UnderlyingQuote


class ProviderError(RuntimeError):
    """Market-data provider failed or returned an unusable payload."""


@runtime_checkable
class MarketDataProvider(Protocol):
    name: str

    def underlying_quote(self, symbol: str) -> UnderlyingQuote: ...

    def option_chain(
        self, symbol: str, start: date | None = None, end: date | None = None
    ) -> list[OptionContract]: ...

    def historical_prices(self, symbol: str, start: date, end: date) -> pd.DataFrame: ...

    def close(self) -> None: ...

