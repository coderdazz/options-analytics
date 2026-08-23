# Architecture and Phase Plan

## Repository audit

The first version already provides useful analytical primitives: Black–Scholes
pricing and Greeks, volatility estimates, SQLite portfolio storage, Monte Carlo
risk, option ranking, a short model backtest, and a provider abstraction.

The main gaps relative to a trader-grade workflow are architectural and semantic:

- `app.py` owns too much page logic and formatting.
- market data is represented as loose DataFrames rather than a canonical quote
  object with provenance and quality flags;
- the initial provider adapter did not make vendor marks/Greeks authoritative;
- scenario results begin from a theoretical Black–Scholes mark instead of being
  anchored to the executable market;
- number and percentage formatting are page-specific;
- option-chain presentation is a ranking table, not a calls/strike/puts terminal;
- deployment did not distinguish ephemeral cloud storage from durable user state.

The existing numerical modules remain useful and are retained behind new domain
and provider interfaces.

## Target architecture

```text
toolkit/
├── app.py                         # thin Streamlit router
├── config/
│   └── settings.py                # typed runtime settings
├── toolkit/
│   ├── data/
│   │   ├── contracts.py           # canonical market-data objects
│   │   ├── provider.py            # provider protocol
│   │   ├── alpaca.py              # Alpaca indicative/OPRA implementation
│   │   ├── demo.py                # deterministic offline provider
│   │   ├── validation.py          # quote-quality rules
│   │   └── cache.py               # provider-independent TTL cache
│   ├── models/
│   │   ├── black_scholes.py       # retained pricing engine
│   │   └── volatility_surface.py  # Phase 2 spline, later SVI
│   ├── analytics/
│   │   ├── trades.py              # generic multi-leg representation
│   │   ├── scenarios.py           # market-anchored full repricing
│   │   ├── probability.py         # Phase 2 real/risk-neutral distributions
│   │   └── relative_value.py      # Phase 2 residuals and vertical ranking
│   ├── strategies/                # presets producing generic Trade objects
│   ├── screeners/                 # Phase 3 signal and universe scanners
│   ├── portfolio/                 # Phase 4 book, stress and journal services
│   └── ui/
│       ├── formatting.py          # units and non-truncating metrics
│       ├── state.py               # explicit session state
│       └── pages/                  # one module per page
├── tests/
│   ├── unit/
│   ├── integration/
│   └── regression/
└── data/                          # ignored runtime SQLite/cache files
```

The migration is incremental: compatibility modules remain until their callers
move. Data acquisition never imports analytics, and analytics depends only on
canonical objects—not on Alpaca SDK models.

## Canonical market-data model

`OptionContract` stores contract identity, quote, liquidity, vendor IV/Greeks,
underlying mark, timestamp and provider. Derived values expose midpoint,
intrinsic/extrinsic value, moneyness and spread percentage. Every contract carries
quality flags for stale, crossed, zero-bid, wide, illiquid or incomplete quotes.

Three fill marks are explicit:

- `mid_price`: comparison mark, never labeled executable;
- `natural_price`: ask for a buy, bid for a sale;
- `conservative_fill_price`: configurable improvement from the natural price
  toward midpoint.

Current market display uses provider IV and Greeks when supplied. Black–Scholes is
used as an independent comparison and as the scenario evolution model. Scenario
P&L is **market anchored**:

```text
scenario mark = current market mark + (model scenario value - model current value)
```

This preserves the live starting mark while applying transparent model dynamics.

## Dependencies

Core runtime remains deliberately small: Streamlit, NumPy, pandas, SciPy, Plotly
and SQLAlchemy/SQLite, with `alpaca-py` for live data and PyArrow/DuckDB for local
market history. Phase 2 may add statsmodels only when diagnostics require it.
No package is added for functionality already implemented and tested locally.

## External data eventually required

Alpaca can provide underlying/option quotes, chains, vendor IV/Greeks and some
history. Its free option feed is indicative rather than OPRA. A credible historical options study still requires point-in-time
bid/ask chains including expired/delisted contracts, quote conditions, corporate
actions and event calendars. Sector/beta analytics need reference classifications
and benchmark histories. Interest-rate curves, discrete dividends, borrow and
earnings estimates need separate governed sources.

## Incremental implementation plan

### Phase 1 — working vertical slice

- provider protocol, canonical contract and quote validation;
- accurate Alpaca-to-canonical mapping with vendor values preserved;
- calls/strike/puts chain with filters and explicit units;
- generic single/vertical trade selection and fill assumptions;
- market-anchored spot/time/IV repricing and Greek evolution;
- deterministic demo provider and numerical/integration tests.

### Phase 2 — volatility and relative value

- robust per-expiry smile spline with quality weights and arbitrage diagnostics;
- skew, risk reversal, butterfly, term structure, IV residual/z-score;
- IV history/rank/percentile and volatility-risk-premium analysis;
- vertical enumerator exposing edge, execution, theta and convexity components.

### Phase 3 — signals and large-universe scanning

- pluggable momentum/mean-reversion/regime signals;
- option-expression optimiser across delta/expiry;
- resumable, rate-limit-aware S&P 500 scanner with liquidity gates.

### Phase 4 — portfolio and journal

- strategy/trade event model, aggregate and grouped exposures;
- correlated factor and sector stress tests;
- configurable management plan and full-loss position sizing;
- journal including signal/surface/assumption snapshots and realised outcomes.

### Phase 5 — validation and operations

- American pricing/discrete dividends, surface regression suite;
- historical-chain backtesting with realistic fills and costs;
- migrations, backups, model/data versioning, observability and access control.

## Smallest useful vertical slice

Select `AAPL` (or another underlying), load Alpaca contracts into canonical
objects, filter a professional chain, click a long option and optionally a short
same-expiry leg, choose a natural/conservative/mid assumption, then inspect the
trade's market-anchored P&L and Greek evolution across spot, time and IV. This is
the Phase 1 acceptance path.
