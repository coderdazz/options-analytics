from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class Settings:
    project_root: Path
    data_dir: Path
    moomoo_host: str = "127.0.0.1"
    moomoo_port: int = 11111
    stale_after_seconds: int = 300
    max_spread_pct: float = 0.25
    min_open_interest: int = 10
    min_volume: int = 1
    conservative_fill_fraction: float = 0.25
    alpaca_api_key: str | None = None
    alpaca_secret_key: str | None = None
    alpaca_option_feed: str = "indicative"
    alpaca_stock_feed: str = "iex"

    @classmethod
    def load(cls, project_root: Path, secrets: Mapping[str, Any] | None = None) -> "Settings":
        secrets = secrets or {}
        alpaca = secrets.get("alpaca", {}) if hasattr(secrets, "get") else {}
        data_dir = Path(os.environ.get("VOLEDGE_DATA_DIR", project_root / "data"))
        data_dir.mkdir(parents=True, exist_ok=True)
        return cls(
            project_root=project_root,
            data_dir=data_dir,
            moomoo_host=os.environ.get("MOOMOO_HOST", "127.0.0.1"),
            moomoo_port=int(os.environ.get("MOOMOO_PORT", "11111")),
            alpaca_api_key=(os.environ.get("ALPACA_API_KEY") or os.environ.get("APCA_API_KEY_ID")
                            or alpaca.get("api_key")),
            alpaca_secret_key=(os.environ.get("ALPACA_SECRET_KEY") or os.environ.get("APCA_API_SECRET_KEY")
                               or alpaca.get("secret_key")),
            alpaca_option_feed=(os.environ.get("ALPACA_OPTION_FEED") or alpaca.get("option_feed") or "indicative").lower(),
            alpaca_stock_feed=(os.environ.get("ALPACA_STOCK_FEED") or alpaca.get("stock_feed") or "iex").lower(),
        )
