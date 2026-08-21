# VolEdge Options Analytics

VolEdge is a local, analysis-first Streamlit terminal for US equity, ETF and
index-option research. Its first production slice is deliberately narrow and
reliable:

**Alpaca data → canonical option chain → arbitrary option/vertical trade →
market-anchored dynamic P&L and Greek scenarios.**

It is research and decision-support software, not investment advice or an order
router.

## What changed in Phase 1

- Alpaca bid, ask, IV, delta, gamma, theta, vega and rho are preserved as
  authoritative current market/vendor fields.
- Black–Scholes values are displayed separately. No model value silently
  overwrites the Alpaca mark or Greeks.
- Scenario prices are anchored to the observed market:

  ```text
  scenario mark = current market midpoint
                + model value(scenario) - model value(now)
  ```

- A canonical `OptionContract` isolates analytics from Alpaca SDK models.
- Every quote is flagged for staleness, crossed/zero markets, excessive spread,
  low volume/OI, or missing IV/Greeks. Missing Greeks are never manufactured.
- Entry prices explicitly use natural, conservative, or midpoint conventions.
  Midpoint is always labeled non-executable.
- Calls/strike/puts chain filters include expiry, DTE, strike, delta, OI,
  volume, width, and quote quality.
- Trade scenarios cover −20% to +20% underlying moves; 0/1/2/5/10/20 days;
  and −20/−10/−5/0/+5/+10/+20 volatility-point shocks.
- Parallel, sticky-strike, local sticky-delta, mean-reverting and user-shift IV
  assumptions are selectable and labeled.
- Dollar figures render in full with separators (`$50,000.00`), while IV,
  rates, dividend yields, returns and spreads are displayed as percentages.

## Run locally

```bash
cd /Users/dazz/Desktop/strategies/toolkit
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py --server.address 127.0.0.1 --server.port 8512
```

The demo provider works immediately. Alpaca data requires free account keys:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Add Alpaca key and secret, then restart Streamlit.
```

Select **Data & Settings → Alpaca**. Basic ($0) supplies IEX equities and an
indicative options feed. Indicative options are modified/calculated research
marks, not executable OPRA quotes. Real-time OPRA currently requires Alpaca's
paid Algo Trader Plus market-data plan. The application is quote-only and does
not construct an order client.

## Workflow

1. Load an underlying and expiry range from **Data & Settings**.
2. Inspect provider provenance and quality flags in **Market Overview**.
3. Filter the professional **Option Chain** and add buy/sell legs.
4. Open **Trade Builder**, choose an entry-fill convention, and compare Alpaca
   with Black–Scholes without forcing reconciliation.
5. Inspect spot P&L, price/time and price/IV heatmaps, and delta/gamma/theta/vega
   evolution.
6. Size using full contractual maximum loss, not an assumed stop fill.
7. Save positions and valuation snapshots under **Portfolio & Risk**.

## Repository layout

```text
app.py                         thin Streamlit router
toolkit/config/                typed runtime settings
toolkit/data/                  provider protocol, canonical contracts, validation
toolkit/analytics/             generic trades and market-anchored scenarios
toolkit/ui/pages/              modular page renderers
toolkit/pricing.py             Black–Scholes and IV solver
toolkit/storage.py             local SQLite repository
tests/                         numerical and integration regression tests
docs/ARCHITECTURE.md           audit, target tree and phased plan
docs/DEPLOYMENT.md             safe local/cloud/private deployment boundary
```

See [Architecture and Phase Plan](docs/ARCHITECTURE.md) for the full design,
external-data needs and Phase 2–5 roadmap.

## Price and Greek interpretation

Current market values may differ materially from Black–Scholes because of quote
timing, American exercise, discrete dividends, borrow, the live rate curve,
surface/skew conventions, settlement details and vendor methodology. VolEdge
keeps this difference visible.

Current Alpaca Greeks are vendor observations. Scenario Greeks are
Black–Scholes estimates at the shocked state. The initial scenario price is the
market midpoint reference; trade P&L is measured against the selected estimated
fill. Neither midpoint nor a model mark is guaranteed executable.

Sticky delta is a local-skew approximation in Phase 1. Phase 2 will fit a
quality-weighted per-expiry spline and use the fitted surface for smile-aware
scenario dynamics. The approximation is labeled in the interface.

## Data and research integrity

SQLite stores portfolios, position inputs and valuation snapshots locally. Live
option chains remain in session in Phase 1. Serious historical research needs
point-in-time bid/ask chains including expired/delisted contracts, quote
conditions, multipliers, corporate actions and events. Today's chain must never
be substituted into a historical backtest.

The app does not equate delta with literal probability, treat midpoint as a
fill, silently fill Greeks, or claim expected P&L from option prices alone.

## Deployment

The included `Dockerfile` and `render.yaml` support a demo/upload cloud preview.
Streamlit Community Cloud is the recommended free deployment and permits one
private app. Put Alpaca keys in its Secrets panel, never GitHub. Its filesystem
is ephemeral, so use an external free PostgreSQL service for durable cloud
portfolios. See [Deployment Design](docs/DEPLOYMENT.md) and
[Data Architecture](docs/DATA_ARCHITECTURE.md).

## Validation

```bash
python3 -m pytest -q
```

The suite validates analytical prices/Greeks, put-call parity, implied-vol
recovery, fill conventions, quote flags, Alpaca/OCC mapping, vendor-Greek
aggregation, market anchoring, vertical bounds, scenario grids, volatility,
risk tails and SQLite persistence. Streamlit integration tests exercise every
page without a browser.

## Planned phases

- **Phase 2:** fitted volatility smile/surface, IV history/rank, skew and
  term-structure diagnostics, normalized residuals, vertical relative value.
- **Phase 3:** pluggable momentum/mean-reversion signals, contract expression
  optimizer, rate-limit-aware S&P 500 scanner.
- **Phase 4:** trade journal, management rules, grouped portfolio exposures and
  correlated factor/sector stress tests.
- **Phase 5:** American pricing/discrete dividends, historical chain backtests,
  model/data versioning, operational hardening and validation.
