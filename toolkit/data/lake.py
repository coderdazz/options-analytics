from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd

from .contracts import OptionContract


def _safe_partition(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.=-]", "_", value)


class MarketDataLake:
    """Append-only Parquet micro-batches with optional DuckDB queries.

    Intended for market observations, not transactional portfolio/user state.
    A collector should buffer stream events and flush batches rather than create
    one file or database transaction per tick.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def append_option_snapshot(self, contracts: list[OptionContract]) -> Path | None:
        if not contracts:
            return None
        frame = pd.DataFrame([contract.as_row() for contract in contracts])
        frame["observed_at"] = pd.to_datetime(frame["timestamp"], utc=True)
        frame["ingested_at"] = datetime.now(timezone.utc)
        frame["quality_flags"] = frame["quality"]
        first = contracts[0]
        observed_date = first.timestamp.astimezone(timezone.utc).date().isoformat()
        partition = (
            self.root / "option_quotes" / f"provider={_safe_partition(first.provider)}"
            / f"date={observed_date}" / f"underlying={_safe_partition(first.underlying)}"
        )
        partition.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%H%M%S-%f")
        target = partition / f"snapshot-{stamp}-{uuid4().hex[:8]}.parquet"
        temporary = target.with_suffix(".parquet.tmp")
        frame.to_parquet(temporary, index=False, compression="zstd")
        os.replace(temporary, target)
        return target

    def query_option_quotes(
        self,
        underlying: str | None = None,
        provider: str | None = None,
        limit: int = 10_000,
    ) -> pd.DataFrame:
        try:
            import duckdb
        except ImportError as exc:
            raise RuntimeError("Install `duckdb` to query the local market-data lake.") from exc
        glob = str(self.root / "option_quotes" / "provider=*" / "date=*" / "underlying=*" / "*.parquet")
        filters, parameters = [], []
        if underlying:
            filters.append("underlying = ?")
            parameters.append(underlying)
        if provider:
            filters.append("provider = ?")
            parameters.append(provider)
        where = " WHERE " + " AND ".join(filters) if filters else ""
        query = (
            "SELECT * FROM read_parquet(?, hive_partitioning=true, union_by_name=true)"
            f"{where} ORDER BY observed_at DESC LIMIT {int(max(1, limit))}"
        )
        return duckdb.connect().execute(query, [glob, *parameters]).df()

