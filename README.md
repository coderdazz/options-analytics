# VolEdge Options Analytics

VolEdge is a local, analysis-first Streamlit terminal for US equity, ETF and
index-option research. Its first production slice is deliberately narrow and
reliable:

**Manual or API market inputs → canonical option contracts → arbitrary option
structure → local delta–gamma and market-anchored dynamic P&L scenarios.**

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
- The Trade Builder accepts manually copied price, bid/ask, IV, delta, gamma,
  theta, vega and rho values without making any API call.
- A trade can be sized by signed contract count or a capital budget. Contract
  multipliers are explicit, so 100 US option contracts at $7 cost $70,000.
- Moomoo and Alpaca are optional read-only quote providers; neither routes
  orders.
- The Option Path Lab calibrates one selected contract to its current market
  mark and shows pre-expiry price and Greek evolution through ordered spot/time
  paths.

## Run locally

```bash
cd "/Users/dazz/Desktop/Dev Projects/options-platform"
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

### Which Alpaca API?

Use Alpaca's **Trading API** account and market-data credentials for this
personal research tool. Do not use the Broker API: that product is intended for
broker-dealers, RIAs and applications that create and manage brokerage accounts
for end users. VolEdge currently uses only market-data endpoints, so paper/live
trading permissions are not needed and no orders are submitted.

The free Basic plan is sufficient to test the integration, but its US option
quotes are indicative rather than consolidated real-time OPRA. Manual Moomoo
values are therefore often the better input for a real trade study when you do
not want a paid Alpaca market-data subscription.

### Optional Moomoo SG connection

Moomoo data arrives through the desktop/local gateway **OpenD**, not through a
key pasted into the app. Install the optional SDK separately so cloud demo
deployments do not carry an unused dependency:

```bash
source .venv/bin/activate
pip install -r requirements-moomoo.txt
# Install and start OpenD, log in to your Moomoo account, then:
MOOMOO_HOST=127.0.0.1 MOOMOO_PORT=11111 streamlit run app.py
```

In **Data & Settings**, select **Moomoo**, use a qualified symbol such as
`US.AAPL`, choose an expiry range and press **Load option chain**. The provider
creates only an `OpenQuoteContext`; it never creates a trade context. It loads
the static option chain once, batches market snapshots in groups of up to 200,
and preserves Moomoo bid, ask, IV and Greeks. Your Moomoo account must have the
relevant quote entitlement. OpenD must remain running and logged in.

An internet-hosted free Streamlit instance normally cannot connect directly to
OpenD running on your laptop. Manual mode works anywhere. A future hosted
Moomoo connection would require a secured, private network path to an always-on
OpenD host; do not expose the OpenD port publicly.

## Workflow

1. For the lowest-friction workflow, open **Trade Builder** and copy an option's
   mark, bid/ask, IV and Greeks from Moomoo or another broker. This makes no API
   request. Alternatively load an option chain from **Data & Settings**.
2. Inspect provider provenance and quality flags in **Market Overview**.
3. Filter the professional **Option Chain** and add buy/sell legs.
4. Open **Trade Builder**, choose an entry-fill convention, and compare Alpaca
   with Black–Scholes without forcing reconciliation.
5. Inspect spot P&L, price/time and price/IV heatmaps, and delta/gamma/theta/vega
   evolution.
6. Open **Option Path Lab** for a single-contract spot sweep, time sweep or
   user-entered daily spot/IV path. The charts focus on option MTM rather than
   exercise payoff.
7. Size using full contractual maximum loss, not an assumed stop fill.
8. Save positions and valuation snapshots under **Portfolio & Risk**.

### Path calibration and IV assumptions

For a selected Moomoo, Alpaca, demo or manually entered contract, the path
engine reads the current spot, market midpoint/mark, vendor IV and Greeks, DTE
and contract terms. It first solves for the Black–Scholes IV that reproduces
the market option price. If no European implied-volatility solution exists, it
uses vendor IV plus a clearly labelled additive price offset that decays to zero
at expiry.

The current vendor Greeks are shown as observed anchor points. Projected Greeks
are model estimates; the app does not force Black–Scholes delta, gamma, vega and
theta to equal vendor values after fitting only one parameter to price.

Available path assumptions are:

- **Constant IV:** the calibrated IV is unchanged.
- **Parallel IV shift:** add a fixed number of volatility points.
- **Sticky strike:** preserve the selected strike's IV. For one fixed contract
  this is numerically the same as constant IV until a fitted surface exists.
- **Sticky delta:** use the labelled local-skew approximation already present
  in the scenario engine.
- **Custom IV path:** enter IV by future day; intermediate days are linearly
  interpolated.

The spot sweep displays price, delta, gamma and vega for today, +1d, +3d and
+5d. The time sweep plots the same measures across remaining DTE for selected
spot levels. The custom path additionally displays underlying price, cumulative
MTM P&L and theta. At expiry the price converges to intrinsic value; all earlier
points are pre-expiry mark-to-market projections.

### Manual example: $7 option, 100 contracts

For a current option mark of $7, delta 0.20, gamma 0.00034, quantity 100 and a
standard multiplier of 100:

```text
premium paid = $7 × 100 contracts × 100 multiplier = $70,000
new option mark ≈ 7 + 0.20×ΔS + 0.5×0.00034×ΔS²
```

For a $1 rise in the underlying, the estimated new mark is $7.20017 and MTM
P&L is approximately $2,001.70. For a $10 rise, the local estimate is $9.017
and P&L is approximately $20,170. The latter is much less reliable because
delta and gamma themselves change as spot moves. Use the full dynamic scenario
engine for larger moves, elapsed time and IV shocks.

Be precise about units: **100 contracts** represent 10,000 underlying shares
with a standard 100 multiplier. If you mean exposure to 100 shares, enter one
contract.

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
