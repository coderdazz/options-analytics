# Data Architecture

## Recommendation

Use two stores because market history and user state have different workloads.

| Data | Local store | Cloud store | Why |
|---|---|---|---|
| Users, portfolios, trades, journal, assumptions | SQLite in WAL mode | PostgreSQL (Neon or Supabase) | Transactional integrity, constraints, updates |
| Quotes, trades, bars, chains, surfaces | Partitioned Parquet queried by DuckDB | Object storage + DuckDB/warehouse | Append-heavy, compressed analytical scans |
| Current stream state | In-memory bounded cache | Redis only if multiple processes need it | Very low latency, disposable |

SQLite is not the tick store. DuckDB is not the multi-user transactional system.

## Local transactional database

SQLite is appropriate for a single-user local terminal. The repository enables
foreign keys, a five-second busy timeout and write-ahead logging. WAL permits
readers while a writer appends journal/valuation records. Keep:

- users or local profiles;
- portfolios and position lots;
- trade/order/fill events;
- risk and valuation snapshot metadata;
- scenario assumptions and model/data versions;
- ingestion manifests pointing to market-data files.

Use SQLAlchemy models and Alembic migrations before the schema grows further.
Do not store Alpaca secrets in SQLite; use environment variables, the OS keychain,
or Streamlit's encrypted Secrets panel.

## Local market-data lake

The implemented `MarketDataLake` writes append-only, compressed Parquet
micro-batches and queries them with DuckDB. Partition layout:

```text
data/market/
└── option_quotes/
    └── provider=alpaca_indicative/
        └── date=2026-08-20/
            └── underlying=AAPL/
                └── snapshot-....parquet
```

Each record should retain event time, ingestion time, provider/feed, underlying,
OCC symbol, bid/ask and sizes, trade, IV/Greeks, multiplier and quality flags.
Store raw vendor values before creating normalized surfaces.

For a stream, buffer Arrow-compatible rows and flush every 2–10 seconds or every
few thousand events. Use atomic rename after writing each micro-batch. Compact
small files after the session into larger partitions. Do not perform one SQLite
transaction or create one Parquet file per quote.

DuckDB can query partitioned Parquet directly with predicate and column pushdown,
making it suitable for local surface research and short backtests without a
database server.

## Cloud deployment

Streamlit Community Cloud files are not a durable portfolio database. For a
private hosted app:

- use a free serverless PostgreSQL database such as Neon or Supabase for
  portfolios, trades and journal records;
- keep connection strings in Streamlit Secrets;
- apply row-level ownership even if the initial app has one user;
- write larger market datasets to object storage, not Postgres rows indefinitely;
- never redistribute OPRA data unless the data license permits it.

Neon currently offers a no-card free PostgreSQL tier with scale-to-zero and
0.5 GB per project. Supabase currently offers two free projects and a 500 MB
database. Either is sufficient for a personal journal; Neon is the simpler pure
Postgres choice, while Supabase is attractive if integrated authentication and
object storage are desired.

## Retention

- Keep every executed trade/fill and decision snapshot indefinitely.
- Keep normalized daily bars indefinitely.
- Keep full option quote streams selectively around decision windows unless a
  licensed historical dataset is available.
- Record hashes/model versions so research outputs can be reproduced.
- Back up SQLite and the journal; Parquet partitions can be regenerated only if
  the source permits redownload.

