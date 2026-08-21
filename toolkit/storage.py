from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .models import Position


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS portfolios (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, base_currency TEXT NOT NULL DEFAULT 'USD',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS positions (
  id INTEGER PRIMARY KEY, portfolio_id INTEGER NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
  symbol TEXT NOT NULL, instrument_type TEXT NOT NULL, quantity REAL NOT NULL,
  entry_price REAL NOT NULL, current_price REAL, currency TEXT NOT NULL,
  option_type TEXT, strike REAL, expiry TEXT, implied_vol REAL, underlying_price REAL,
  multiplier REAL NOT NULL, interest_rate REAL NOT NULL, dividend_yield REAL NOT NULL,
  notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS valuations (
  id INTEGER PRIMARY KEY, portfolio_id INTEGER NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
  valued_at TEXT NOT NULL, market_value REAL NOT NULL, pnl REAL NOT NULL,
  delta REAL NOT NULL, gamma REAL NOT NULL, vega REAL NOT NULL, theta REAL NOT NULL,
  details_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS market_prices (
  symbol TEXT NOT NULL, timestamp TEXT NOT NULL, open REAL, high REAL, low REAL, close REAL NOT NULL,
  volume REAL, source TEXT NOT NULL, PRIMARY KEY(symbol, timestamp, source)
);
CREATE INDEX IF NOT EXISTS idx_positions_portfolio ON positions(portfolio_id);
CREATE INDEX IF NOT EXISTS idx_valuations_portfolio_time ON valuations(portfolio_id, valued_at);
CREATE INDEX IF NOT EXISTS idx_prices_symbol_time ON market_prices(symbol, timestamp);
"""


class Repository:
    def __init__(self, path: str | Path = "data/options_toolkit.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _init(self) -> None:
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.executescript(SCHEMA)

    def create_portfolio(self, name: str, base_currency: str = "USD") -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO portfolios(name,base_currency,created_at,updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET updated_at=excluded.updated_at RETURNING id",
                (name.strip(), base_currency, now, now),
            )
            return int(cur.fetchone()[0])

    def portfolios(self) -> pd.DataFrame:
        with self.connect() as conn:
            return pd.read_sql_query("SELECT * FROM portfolios ORDER BY updated_at DESC", conn)

    def add_position(self, portfolio_id: int, position: Position) -> int:
        row = position.to_record()
        now = datetime.now(timezone.utc).isoformat()
        columns = list(row) + ["portfolio_id", "created_at"]
        values = list(row.values()) + [portfolio_id, now]
        with self.connect() as conn:
            cur = conn.execute(
                f"INSERT INTO positions({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                values,
            )
            conn.execute("UPDATE portfolios SET updated_at=? WHERE id=?", (now, portfolio_id))
            return int(cur.lastrowid)

    def positions(self, portfolio_id: int) -> pd.DataFrame:
        with self.connect() as conn:
            return pd.read_sql_query(
                "SELECT * FROM positions WHERE portfolio_id=? ORDER BY created_at", conn,
                params=(portfolio_id,),
            )

    def delete_position(self, position_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM positions WHERE id=?", (position_id,))

    def save_valuation(self, portfolio_id: int, summary: dict, details: list[dict]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO valuations(portfolio_id,valued_at,market_value,pnl,delta,gamma,vega,theta,details_json) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (portfolio_id, now, summary["market_value"], summary["pnl"], summary["delta"],
                 summary["gamma"], summary["vega"], summary["theta"], json.dumps(details, default=str)),
            )

    def valuation_history(self, portfolio_id: int) -> pd.DataFrame:
        with self.connect() as conn:
            return pd.read_sql_query(
                "SELECT * FROM valuations WHERE portfolio_id=? ORDER BY valued_at", conn,
                params=(portfolio_id,),
            )

    def upsert_prices(self, symbol: str, prices: pd.DataFrame, source: str = "csv") -> int:
        frame = prices.copy()
        if "timestamp" not in frame and isinstance(frame.index, pd.DatetimeIndex):
            frame = frame.reset_index().rename(columns={frame.index.name or "index": "timestamp"})
        frame.columns = [str(c).lower() for c in frame.columns]
        if not {"timestamp", "close"}.issubset(frame.columns):
            raise ValueError("Price data needs timestamp and close columns.")
        rows = []
        for _, r in frame.iterrows():
            rows.append((symbol, pd.Timestamp(r["timestamp"]).isoformat(), r.get("open"), r.get("high"),
                         r.get("low"), float(r["close"]), r.get("volume"), source))
        with self.connect() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO market_prices(symbol,timestamp,open,high,low,close,volume,source) "
                "VALUES(?,?,?,?,?,?,?,?)", rows,
            )
        return len(rows)

    def prices(self, symbol: str) -> pd.DataFrame:
        with self.connect() as conn:
            frame = pd.read_sql_query(
                "SELECT * FROM market_prices WHERE symbol=? ORDER BY timestamp", conn, params=(symbol,)
            )
        if not frame.empty:
            frame["timestamp"] = pd.to_datetime(frame["timestamp"])
        return frame
