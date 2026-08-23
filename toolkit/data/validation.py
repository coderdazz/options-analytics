from __future__ import annotations

from datetime import datetime, timezone

from .contracts import OptionContract


def quote_quality_flags(
    contract: OptionContract,
    stale_after_seconds: int = 300,
    max_spread_pct: float = 0.25,
    min_open_interest: int = 10,
    min_volume: int = 1,
    now: datetime | None = None,
) -> tuple[str, ...]:
    flags: list[str] = []
    if contract.bid is None or contract.ask is None:
        flags.append("missing_market")
    else:
        if contract.bid == 0:
            flags.append("zero_bid")
        if contract.bid > contract.ask:
            flags.append("crossed_market")
        if contract.bid_ask_pct is not None and contract.bid_ask_pct > max_spread_pct:
            flags.append("wide_spread")
    if contract.open_interest is None or contract.open_interest < min_open_interest:
        flags.append("low_oi")
    if contract.volume is None or contract.volume < min_volume:
        flags.append("low_volume")
    if contract.implied_volatility is None:
        flags.append("missing_iv")
    if not contract.greeks.complete:
        flags.append("missing_greeks")
    if contract.feed == "indicative":
        flags.append("indicative_not_opra")
    now = now or datetime.now(timezone.utc)
    quote_time = contract.timestamp
    if quote_time.tzinfo is None:
        quote_time = quote_time.replace(tzinfo=timezone.utc)
    if (now - quote_time).total_seconds() > stale_after_seconds:
        flags.append("stale")
    return tuple(dict.fromkeys(flags))
